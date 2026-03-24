"""
KIS 주도주 스크리너 서비스 (프로덕션)
- Flask 통합용 (app/services/)
- 장중 3초 폴링, 장외 마지막 결과 반환
"""
import requests
import time
import os
import json
import glob
import logging
from datetime import datetime
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)

from app.utils.paths import DATA_DIR

# ─── 설정 ───
_paper = os.environ.get("KIS_PAPER", "true").lower() in ("true", "1")
BASE_URL = "https://openapivts.koreainvestment.com:29443" if _paper else "https://openapi.koreainvestment.com:9443"
APP_KEY = os.environ.get("KIS_APP_KEY", "")
APP_SECRET = os.environ.get("KIS_APP_SECRET", "")

ETF_KEYWORDS = [
    "KODEX", "TIGER", "KBSTAR", "KOSEF", "ARIRANG", "HANARO",
    "SOL", "ACE", "RISE", "PLUS", "BNK", "ETN", "인버스", "레버리지",
    "선물", "2X", "3X", "KINDEX", "TIMEFOLIO", "WOORI",
]

# ─── 토큰 관리 ───
_token_lock = Lock()
_token_cache = {"token": None, "expires_at": 0}
_TOKEN_CACHE_FILE = os.path.join(DATA_DIR, "kis_token_cache.json")


def _load_cached_token():
    if os.path.exists(_TOKEN_CACHE_FILE):
        try:
            with open(_TOKEN_CACHE_FILE, "r") as f:
                data = json.load(f)
            if data.get("expires_at", 0) > time.time():
                return data["token"]
        except Exception:
            pass
    return None


def _save_token_cache(token):
    try:
        os.makedirs(os.path.dirname(_TOKEN_CACHE_FILE), exist_ok=True)
        with open(_TOKEN_CACHE_FILE, "w") as f:
            json.dump({"token": token, "expires_at": time.time() + 23 * 3600}, f)
    except Exception:
        pass


def get_token():
    with _token_lock:
        if _token_cache["token"] and _token_cache["expires_at"] > time.time():
            return _token_cache["token"]
        cached = _load_cached_token()
        if cached:
            _token_cache["token"] = cached
            _token_cache["expires_at"] = time.time() + 23 * 3600
            return cached
        if not APP_KEY or not APP_SECRET:
            logger.error("KIS_APP_KEY / KIS_APP_SECRET 환경변수 없음")
            return None
        try:
            res = requests.post(f"{BASE_URL}/oauth2/tokenP", json={
                "grant_type": "client_credentials",
                "appkey": APP_KEY, "appsecret": APP_SECRET,
            }, timeout=10)
            if res.status_code != 200:
                logger.error(f"KIS 토큰 발급 실패: {res.status_code}")
                return None
            token = res.json().get("access_token")
            if token:
                _token_cache["token"] = token
                _token_cache["expires_at"] = time.time() + 23 * 3600
                _save_token_cache(token)
            return token
        except Exception as e:
            logger.error(f"KIS 토큰 발급 에러: {e}")
            return None


def invalidate_token():
    with _token_lock:
        _token_cache["token"] = None
        _token_cache["expires_at"] = 0
        if os.path.exists(_TOKEN_CACHE_FILE):
            os.remove(_TOKEN_CACHE_FILE)


# ─── API 호출 ───

def _headers(token, tr_id):
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET,
        "tr_id": tr_id, "custtype": "P",
    }


def _safe_int(val, default=0):
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    try:
        return float(val or default)
    except (ValueError, TypeError):
        return default


def _api_get(token, path, tr_id, params, retry=True):
    try:
        res = requests.get(f"{BASE_URL}{path}",
                           headers=_headers(token, tr_id),
                           params=params, timeout=10)
        if res.status_code == 401 and retry:
            invalidate_token()
            new_token = get_token()
            if new_token:
                return _api_get(new_token, path, tr_id, params, retry=False)
        return res.json().get("output", [])
    except Exception as e:
        logger.warning(f"KIS API 호출 실패 {path}: {e}")
        return []


def fetch_volume_rank(token, blng_code="3"):
    return _api_get(token,
                    "/uapi/domestic-stock/v1/quotations/volume-rank",
                    "FHPST01710000", {
                        "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171",
                        "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0",
                        "FID_BLNG_CLS_CODE": blng_code,
                        "FID_TRGT_CLS_CODE": "000000", "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                        "FID_INPUT_PRICE_1": "", "FID_INPUT_PRICE_2": "",
                        "FID_VOL_CNT": "", "FID_INPUT_DATE_1": "",
                    })


def fetch_fluctuation_rank(token):
    return _api_get(token,
                    "/uapi/domestic-stock/v1/ranking/fluctuation",
                    "FHPST01700000", {
                        "fid_cond_mrkt_div_code": "J", "fid_cond_scr_div_code": "20170",
                        "fid_input_iscd": "0000", "fid_rank_sort_cls_code": "0",
                        "fid_input_cnt_1": "30", "fid_prc_cls_code": "0",
                        "fid_input_price_1": "0", "fid_input_price_2": "1000000",
                        "fid_vol_cnt": "10000", "fid_trgt_cls_code": "0",
                        "fid_trgt_exls_cls_code": "0", "fid_div_cls_code": "0",
                        "fid_rsfl_rate1": "0", "fid_rsfl_rate2": "30",
                    })


def fetch_investor(token, stock_code):
    return _api_get(token,
                    "/uapi/domestic-stock/v1/quotations/inquire-investor",
                    "FHKST01010900", {
                        "FID_COND_MRKT_DIV_CODE": "J",
                        "FID_INPUT_ISCD": stock_code,
                    })


# ─── 채점 ───

def _is_etf(name):
    upper = name.upper()
    return any(kw.upper() in upper for kw in ETF_KEYWORDS)


def _score_trading_value(tr_amt):
    eok = tr_amt / 1_0000_0000
    if eok >= 500: return 30
    if eok >= 200: return 25
    if eok >= 100: return 20
    if eok >= 50: return 15
    if eok >= 20: return 10
    return 0


def _score_change_pct(pct):
    if pct >= 15: return 25
    if pct >= 10: return 22
    if pct >= 7: return 18
    if pct >= 5: return 14
    if pct >= 3: return 10
    if pct >= 1: return 5
    return 0


def _score_investor(investor_data):
    if not investor_data:
        return 0, 0, 0
    today = investor_data[0]
    foreign = _safe_int(today.get("frgn_ntby_qty"))
    inst = _safe_int(today.get("orgn_ntby_qty"))
    if foreign > 0 and inst > 0:
        score = 25
    elif foreign > 1000:
        score = 18
    elif inst > 1000:
        score = 15
    elif foreign > 0 or inst > 0:
        score = 8
    else:
        score = 0
    return score, foreign, inst


def _score_volume_surge(item):
    vol = _safe_int(item.get("acml_vol"))
    prdy = _safe_int(item.get("prdy_vol"), 1) or 1
    ratio = (vol / prdy) * 100
    if ratio >= 500: return 10, round(ratio, 1)
    if ratio >= 300: return 8, round(ratio, 1)
    if ratio >= 200: return 6, round(ratio, 1)
    if ratio >= 100: return 3, round(ratio, 1)
    return 0, round(ratio, 1)


def _score_sector(sector_map, sector):
    if not sector or sector not in sector_map:
        return 0, 0
    cnt = sector_map[sector]
    if cnt >= 3: return 10, cnt
    if cnt >= 2: return 7, cnt
    if cnt >= 1: return 3, cnt
    return 0, cnt


def _time_weight():
    h, m = datetime.now().hour, datetime.now().minute
    t = h + m / 60
    if 9.0 <= t < 9.5: return 1.2
    if 9.5 <= t < 10.5: return 1.0
    if 10.5 <= t < 11.5: return 1.1
    if 13.0 <= t < 14.0: return 1.15
    if 14.0 <= t < 15.33: return 0.8
    return 1.0


def _grade(total):
    if total >= 80: return "S"
    if total >= 60: return "A"
    if total >= 40: return "B"
    return "C"


def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour + now.minute / 60
    return 9.0 <= t < 15.5


def get_market_status():
    now = datetime.now()
    t = now.hour + now.minute / 60
    if is_market_open():
        return "open"
    if 8.5 <= t < 9.0:
        return "pre_market"
    return "closed"


# ─── 메인 스크리닝 ───

_result_cache = {"data": None, "ts": 0}
_result_lock = Lock()
_CACHE_TTL = 3


def run_screening():
    now = time.time()
    with _result_lock:
        if _result_cache["data"] and (now - _result_cache["ts"]) < _CACHE_TTL:
            return _result_cache["data"]

    t_start = time.time()
    token = get_token()
    if not token:
        return {"error": "토큰 발급 실패", "results": [], "timestamp": datetime.now().isoformat(),
                "market_status": get_market_status(), "by_grade": {}, "total_candidates": 0,
                "time_weight": 1.0, "api_calls": 0, "elapsed_ms": 0}

    volume_by_amt = fetch_volume_rank(token, "3")
    fluct_data = fetch_fluctuation_rank(token)
    volume_by_surge = fetch_volume_rank(token, "1")

    candidates = {}
    for item in volume_by_amt:
        code = item.get("mksc_shrn_iscd", "")
        name = item.get("hts_kor_isnm", "")
        if not code or _is_etf(name):
            continue
        tr_amt = _safe_int(item.get("acml_tr_pbmn"))
        if tr_amt < 20_0000_0000:
            continue
        candidates[code] = {
            "code": code, "name": name,
            "price": _safe_int(item.get("stck_prpr")),
            "change_pct": _safe_float(item.get("prdy_ctrt")),
            "tr_amt": tr_amt,
            "volume": _safe_int(item.get("acml_vol")),
            "prdy_vol": _safe_int(item.get("prdy_vol"), 1),
            "sector": item.get("bstp_cls_code", ""),
            "raw": item,
        }

    for item in fluct_data:
        code = item.get("mksc_shrn_iscd", item.get("stck_shrn_iscd", ""))
        name = item.get("hts_kor_isnm", "")
        if not code or code in candidates or _is_etf(name):
            continue
        pct = _safe_float(item.get("prdy_ctrt"))
        tr_amt = _safe_int(item.get("acml_tr_pbmn"))
        if pct < 1 or tr_amt < 20_0000_0000:
            continue
        candidates[code] = {
            "code": code, "name": name,
            "price": _safe_int(item.get("stck_prpr")),
            "change_pct": pct, "tr_amt": tr_amt,
            "volume": _safe_int(item.get("acml_vol")),
            "prdy_vol": _safe_int(item.get("prdy_vol"), 1),
            "sector": item.get("bstp_cls_code", ""),
            "raw": item,
        }

    surge_map = {item.get("mksc_shrn_iscd", ""): item for item in volume_by_surge}

    sector_rising = defaultdict(int)
    for c in candidates.values():
        if c["change_pct"] >= 3 and c["sector"]:
            sector_rising[c["sector"]] += 1

    pre_scored = sorted(
        candidates.values(),
        key=lambda c: _score_trading_value(c["tr_amt"]) + _score_change_pct(c["change_pct"]),
        reverse=True
    )[:15]

    investor_results = {}
    for c in pre_scored:
        try:
            inv = fetch_investor(token, c["code"])
            investor_results[c["code"]] = inv
            time.sleep(0.08)
        except Exception:
            pass

    tw = _time_weight()
    results = []
    for c in candidates.values():
        s1 = _score_trading_value(c["tr_amt"])
        s2 = _score_change_pct(c["change_pct"])
        s3, foreign, inst = _score_investor(investor_results.get(c["code"], []))
        s4, vol_ratio = _score_volume_surge(surge_map.get(c["code"], c["raw"]))
        s5, sector_count = _score_sector(sector_rising, c["sector"])

        raw_total = s1 + s2 + s3 + s4 + s5
        total = min(100, round(raw_total * tw))
        grade = _grade(total)
        if grade == "C":
            continue

        results.append({
            "rank": 0, "grade": grade, "code": c["code"], "name": c["name"],
            "price": c["price"], "change_pct": c["change_pct"],
            "trading_value": c["tr_amt"],
            "trading_value_eok": round(c["tr_amt"] / 1_0000_0000),
            "volume": c["volume"],
            "score": {"total": total, "trading_value": s1, "momentum": s2,
                      "smart_money": s3, "volume_surge": s4, "sector": s5},
            "investor": {"foreign_net": foreign, "inst_net": inst},
            "volume_ratio": vol_ratio, "sector_rising_count": sector_count,
        })

    results.sort(key=lambda x: x["score"]["total"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    by_grade = {}
    for r in results:
        by_grade[r["grade"]] = by_grade.get(r["grade"], 0) + 1

    output = {
        "timestamp": datetime.now().isoformat(),
        "market_status": get_market_status(),
        "time_weight": tw,
        "total_candidates": len(candidates),
        "results": results,
        "by_grade": by_grade,
        "api_calls": 3 + len(pre_scored),
        "elapsed_ms": round((time.time() - t_start) * 1000),
    }

    with _result_lock:
        _result_cache["data"] = output
        _result_cache["ts"] = time.time()

    # 결과 저장
    _save_result(output)

    return output


def _save_result(result):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        latest = os.path.join(DATA_DIR, "screener_leading_latest.json")
        with open(latest, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        date_str = datetime.now().strftime("%Y%m%d")
        archive = os.path.join(DATA_DIR, f"screener_leading_{date_str}.json")
        with open(archive, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"스크리너 결과 저장 실패: {e}")


def load_latest():
    path = os.path.join(DATA_DIR, "screener_leading_latest.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def load_history(date_str):
    path = os.path.join(DATA_DIR, f"screener_leading_{date_str}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def list_dates():
    pattern = os.path.join(DATA_DIR, "screener_leading_*.json")
    files = glob.glob(pattern)
    dates = []
    for f in files:
        name = os.path.basename(f)
        if name == "screener_leading_latest.json":
            continue
        d = name.replace("screener_leading_", "").replace(".json", "")
        if len(d) == 8 and d.isdigit():
            dates.append(d)
    return sorted(dates, reverse=True)
