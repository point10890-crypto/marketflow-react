"""
OpenDART 호재공시 수집기

전자공시시스템(DART) API를 통해 종목별 호재/악재 공시를 조회하고
종가베팅 분석에 활용합니다.

API 문서: https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS001
"""

import os
import json
import asyncio
import zipfile
import io
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# ── 호재/악재 공시 분류 ──────────────────────────────────────
STRONG_POSITIVE = [
    "자기주식취득결정", "자기주식취득",
    "무상증자결정", "무상증자",
    "주식배당결정",
]

MODERATE_POSITIVE = [
    "현금배당", "배당",
    "합병결정", "분할합병결정",
    "영업양수결정", "영업양도결정",
    "타법인주식및출자증권취득결정",
]

# 공시 제목에서 호재를 감지하는 키워드
TITLE_STRONG_KEYWORDS = [
    "자기주식", "자사주", "무상증자", "주식배당",
    "단일판매", "공급계약", "수주", "납품계약",
    "대규모", "공급계약체결",
]

TITLE_MODERATE_KEYWORDS = [
    "현금배당", "배당결정", "합병", "영업양수",
    "주식매수선택권", "전환사채", "신주인수권",
    "타법인주식", "출자증권취득",
]

TITLE_NEGATIVE_KEYWORDS = [
    "감자", "자본감소", "부도", "파산", "상장폐지",
    "영업정지", "회생절차", "워크아웃", "관리절차",
    "횡령", "배임", "유상증자",
]

# ── 공시 유형 코드 ────────────────────────────────────────────
DISCLOSURE_TYPE_MAJOR = "B"   # 주요사항보고
DISCLOSURE_TYPE_EQUITY = "D"  # 지분공시


class DARTCollector:
    """OpenDART 전자공시 수집기"""

    BASE_URL = "https://opendart.fss.or.kr/api"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("DART_API_KEY")
        self._corp_code_map: Dict[str, str] = {}  # stock_code -> corp_code
        self._corp_code_loaded = False
        self._data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
        )

    # ── corp_code 매핑 ───────────────────────────────────────

    async def _ensure_corp_codes(self):
        """corp_code 매핑 테이블 로드 (캐시 우선)"""
        if self._corp_code_loaded:
            return

        cache_path = os.path.join(self._data_dir, "dart_corp_codes.json")

        # 캐시가 있고 7일 이내면 재사용
        if os.path.exists(cache_path):
            mtime = os.path.getmtime(cache_path)
            age_days = (datetime.now().timestamp() - mtime) / 86400
            if age_days < 7:
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        self._corp_code_map = json.load(f)
                    self._corp_code_loaded = True
                    print(f"[DART] corp_code 캐시 로드: {len(self._corp_code_map)}개")
                    return
                except Exception:
                    pass

        # API에서 다운로드
        await self._download_corp_codes(cache_path)

    async def _download_corp_codes(self, cache_path: str):
        """OpenDART에서 corp_code ZIP 다운로드 및 파싱"""
        if not self.api_key:
            print("[DART] API Key 미설정 - corp_code 다운로드 스킵")
            return

        url = f"{self.BASE_URL}/corpCode.xml"
        params = {"crtfc_key": self.api_key}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    print(f"[DART] corp_code 다운로드 실패: HTTP {resp.status_code}")
                    return

                # ZIP 파일에서 XML 추출
                zf = zipfile.ZipFile(io.BytesIO(resp.content))
                xml_name = zf.namelist()[0]
                xml_data = zf.read(xml_name)

                # XML 파싱
                root = ET.fromstring(xml_data)
                corp_map = {}
                for item in root.findall(".//list"):
                    corp_code = item.findtext("corp_code", "")
                    stock_code = item.findtext("stock_code", "").strip()
                    if stock_code and len(stock_code) == 6:
                        corp_map[stock_code] = corp_code

                self._corp_code_map = corp_map
                self._corp_code_loaded = True

                # 캐시 저장
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(corp_map, f, ensure_ascii=False)

                print(f"[DART] corp_code 다운로드 완료: {len(corp_map)}개 종목")

        except Exception as e:
            print(f"[DART] corp_code 다운로드 에러: {e}")

    def _get_corp_code(self, stock_code: str) -> Optional[str]:
        """종목코드(6자리) → DART 고유번호(8자리) 변환"""
        return self._corp_code_map.get(stock_code)

    # ── 공시 조회 ────────────────────────────────────────────

    async def get_positive_disclosures(
        self, stock_code: str, days: int = 7
    ) -> Dict:
        """
        종목의 최근 호재공시 조회 및 점수화

        Args:
            stock_code: 6자리 종목코드
            days: 조회 기간 (기본 7일)

        Returns:
            {
                "has_disclosure": bool,
                "score": int (0~2),
                "disclosures": [{"type", "title", "date", "sentiment"}],
                "types": ["자사주취득", ...],
                "negative": bool
            }
        """
        result = {
            "has_disclosure": False,
            "score": 0,
            "disclosures": [],
            "types": [],
            "negative": False,
        }

        if not self.api_key:
            return result

        await self._ensure_corp_codes()

        corp_code = self._get_corp_code(stock_code)
        if not corp_code:
            print(f"[DART] corp_code 조회 실패: {stock_code} — 매핑 없음, 빈 결과 반환")
            return result

        # 날짜 범위
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        # 주요사항보고(B) 공시 검색
        disclosures = await self._search_disclosures(
            corp_code=corp_code,
            bgn_de=start_date.strftime("%Y%m%d"),
            end_de=end_date.strftime("%Y%m%d"),
            pblntf_ty=DISCLOSURE_TYPE_MAJOR,
        )

        if not disclosures:
            return result

        # 호재/악재 분류
        strong_found = []
        moderate_found = []
        negative_found = []

        for disc in disclosures:
            title = disc.get("report_nm", "")
            sentiment = self._classify_disclosure(title)

            entry = {
                "type": sentiment["type"],
                "title": title,
                "date": disc.get("rcept_dt", ""),
                "sentiment": sentiment["sentiment"],
                "rcept_no": disc.get("rcept_no", ""),
            }

            if sentiment["sentiment"] == "strong_positive":
                strong_found.append(entry)
            elif sentiment["sentiment"] == "moderate_positive":
                moderate_found.append(entry)
            elif sentiment["sentiment"] == "negative":
                negative_found.append(entry)

        # 결과 조합
        all_positive = strong_found + moderate_found
        all_disclosures = all_positive + negative_found

        if not all_disclosures:
            return result

        result["has_disclosure"] = True
        result["disclosures"] = all_disclosures[:10]  # 최대 10개

        # 유형 목록
        types = list(set(d["type"] for d in all_positive if d["type"]))
        result["types"] = types

        # 점수 계산
        if negative_found:
            result["score"] = -2
            result["negative"] = True
        elif strong_found:
            result["score"] = 2
        elif moderate_found:
            result["score"] = 1
        else:
            result["score"] = 0

        return result

    async def _search_disclosures(
        self,
        corp_code: str,
        bgn_de: str,
        end_de: str,
        pblntf_ty: str = "",
        page_count: int = 20,
    ) -> List[Dict]:
        """OpenDART 공시검색 API 호출"""
        url = f"{self.BASE_URL}/list.json"
        params = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_count": str(page_count),
            "sort": "date",
            "sort_mth": "desc",
        }
        if pblntf_ty:
            params["pblntf_ty"] = pblntf_ty

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    return []

                data = resp.json()

                # 에러 체크 (status: "000" = 정상)
                status = data.get("status", "")
                if status != "000":
                    # 013 = 조회된 데이터가 없음 (정상)
                    if status != "013":
                        print(f"[DART] API 에러: {data.get('message', status)}")
                    return []

                return data.get("list", [])

        except Exception as e:
            print(f"[DART] 공시검색 에러: {e}")
            return []

    def _classify_disclosure(self, title: str) -> Dict:
        """공시 제목으로 호재/악재 분류"""

        # 악재 체크 (우선)
        for kw in TITLE_NEGATIVE_KEYWORDS:
            if kw in title:
                return {"type": kw, "sentiment": "negative"}

        # 강한 호재 체크
        for kw in TITLE_STRONG_KEYWORDS:
            if kw in title:
                return {"type": kw, "sentiment": "strong_positive"}

        # 보통 호재 체크
        for kw in TITLE_MODERATE_KEYWORDS:
            if kw in title:
                return {"type": kw, "sentiment": "moderate_positive"}

        # 분류 불가
        return {"type": "기타", "sentiment": "neutral"}

    # ── 유틸리티 ─────────────────────────────────────────────

    async def get_financial_health(self, stock_code: str) -> Dict:
        """DART 재무제표 기반 재무건전성 점수 (0~3점)"""
        result = {
            "has_data": False, "score": 0,
            "roe": 0, "debt_ratio": 0, "revenue_growth": 0, "op_margin": 0,
            "detail": ""
        }
        if not self.api_key:
            return result

        await self._ensure_corp_codes()
        corp_code = self._get_corp_code(stock_code)
        if not corp_code:
            print(f"[DART] corp_code 조회 실패: {stock_code} — 매핑 없음")
            return result

        try:
            year = date.today().year
            data = None
            for y in [year, year - 1]:
                for reprt in ["11011", "11012", "11013"]:
                    data = await self._fetch_financial(corp_code, str(y), reprt)
                    if data:
                        break
                if data:
                    break

            if not data:
                return result

            accounts = {}
            for item in data:
                nm = item.get("account_nm", "")
                if item.get("fs_div") == "OFS" and accounts.get(nm):
                    continue
                amt = self._parse_amount(item.get("thstrm_amount", "0"))
                prev = self._parse_amount(item.get("frmtrm_amount", "0"))
                accounts[nm] = {"current": amt, "previous": prev}

            revenue = accounts.get("매출액", accounts.get("수익(매출액)", {}))
            op_profit = accounts.get("영업이익", accounts.get("영업이익(손실)", {}))
            net_income = accounts.get("당기순이익", accounts.get("당기순이익(손실)", {}))
            total_equity = accounts.get("자본총계", {})
            total_liab = accounts.get("부채총계", {})

            rev_cur, rev_prev = revenue.get("current", 0), revenue.get("previous", 0)
            op_cur, ni_cur = op_profit.get("current", 0), net_income.get("current", 0)
            eq_cur, liab_cur = total_equity.get("current", 0), total_liab.get("current", 0)

            if eq_cur > 0:
                result["roe"] = round(ni_cur / eq_cur * 100, 1)
                result["debt_ratio"] = round(liab_cur / eq_cur * 100, 1)
            if rev_prev > 0:
                result["revenue_growth"] = round((rev_cur - rev_prev) / rev_prev * 100, 1)
            if rev_cur > 0:
                result["op_margin"] = round(op_cur / rev_cur * 100, 1)

            result["has_data"] = True
            score, details = 0, []

            if result["roe"] >= 15:
                score += 1; details.append(f"ROE {result['roe']}%↑")
            elif result["roe"] >= 10:
                score += 0.5; details.append(f"ROE {result['roe']}%")
            if 0 < result["debt_ratio"] <= 100:
                score += 1; details.append(f"부채{result['debt_ratio']}%↓")
            elif 0 < result["debt_ratio"] <= 200:
                score += 0.5; details.append(f"부채{result['debt_ratio']}%")
            if result["revenue_growth"] >= 10:
                score += 0.5; details.append(f"매출+{result['revenue_growth']}%")
            if result["op_margin"] >= 10:
                score += 0.5; details.append(f"영익률{result['op_margin']}%")

            result["score"] = min(3, round(score))
            result["detail"] = ", ".join(details) if details else "재무 보통"
            return result
        except Exception as e:
            print(f"[DART] 재무제표 에러 ({stock_code}): {e}")
            return result

    async def _fetch_financial(self, corp_code: str, bsns_year: str, reprt_code: str):
        """DART 단일회사 주요계정 API 호출"""
        url = f"{self.BASE_URL}/fnlttSinglAcnt.json"
        params = {"crtfc_key": self.api_key, "corp_code": corp_code,
                  "bsns_year": bsns_year, "reprt_code": reprt_code}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                return data.get("list", []) if data.get("status") == "000" else None
        except Exception:
            return None

    @staticmethod
    def _parse_amount(s: str) -> float:
        """금액 문자열 → float ('247,684,612,000' → float)"""
        try:
            return float(str(s).replace(",", "").strip() or "0")
        except (ValueError, TypeError):
            return 0

    def format_for_llm(self, dart_result: Dict) -> str:
        """DART 결과를 LLM 프롬프트용 텍스트로 변환"""
        if not dart_result.get("has_disclosure"):
            return ""

        lines = ["[공식 공시 정보 (DART 전자공시)]"]
        for d in dart_result.get("disclosures", [])[:5]:
            emoji = "🟢" if "positive" in d.get("sentiment", "") else "🔴"
            lines.append(f"  {emoji} [{d.get('date', '')}] {d.get('title', '')}")

        if dart_result.get("types"):
            lines.append(f"  → 핵심: {', '.join(dart_result['types'])}")

        return "\n".join(lines)


# ── 테스트 ───────────────────────────────────────────────────
if __name__ == "__main__":
    async def test():
        collector = DARTCollector()
        # 삼성전자 (005930) 테스트
        result = await collector.get_positive_disclosures("005930", days=30)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(test())
