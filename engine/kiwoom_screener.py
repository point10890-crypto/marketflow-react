"""
키움증권 OpenAPI 조건검색 (WebSocket)
- CNSRLST: HTS에 저장된 조건식 목록 조회
- CNSRREQ: 조건식 단발 실행 → 종목 리스트 반환
- 사전조건: HTS(영웅문)에서 조건식 미리 저장 + OpenAPI 사용신청

사양:
  WS URL : wss://api.kiwoom.com:10000/api/dostk/websocket
  Auth   : 최초 {"trnm":"LOGIN","token":<bearer>} → return_code:0 확인
  PING   : 서버가 {"trnm":"PING"} 보내면 그대로 echo
  Limits : 시세류 1초 5회 / 조건식당 1분 1회

이 모듈은 단발(search_type=0)만 사용. 실시간 등록은 별도 모듈에서 처리.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

try:
    import websockets
except ImportError as e:
    raise RuntimeError("websockets package required: pip install websockets") from e

from engine.kiwoom_client import get_token

logger = logging.getLogger(__name__)

WS_URL = os.getenv("KIWOOM_WS_URL", "wss://api.kiwoom.com:10000/api/dostk/websocket")
LOGIN_TIMEOUT = 10
RECV_TIMEOUT = 8
CNSRREQ_TIMEOUT = 15  # 장중에는 1~3초 / 장외엔 무응답


class KiwoomScreenerError(Exception):
    pass


async def _login(ws, token: str) -> None:
    await ws.send(json.dumps({"trnm": "LOGIN", "token": token}))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=LOGIN_TIMEOUT)
        msg = json.loads(raw)
        trnm = msg.get("trnm")
        if trnm == "PING":
            await ws.send(raw)
            continue
        if trnm == "LOGIN":
            rc = msg.get("return_code", -1)
            if rc != 0:
                raise KiwoomScreenerError(f"LOGIN failed rc={rc} msg={msg.get('return_msg')}")
            return
        # 그 외 예상치 못한 응답은 무시하고 LOGIN 응답 대기


async def _recv_until(ws, want_trnm: str, timeout: float = RECV_TIMEOUT) -> dict:
    """want_trnm 응답이 올 때까지 PING은 echo, 다른 메시지는 진단 로그."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remain = deadline - asyncio.get_event_loop().time()
        if remain <= 0:
            raise asyncio.TimeoutError(f"timeout waiting for {want_trnm}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remain)
        msg = json.loads(raw)
        trnm = msg.get("trnm")
        if trnm == "PING":
            await ws.send(raw)
            continue
        if trnm == want_trnm:
            return msg
        # 다른 trnm은 진단을 위해 로그
        logger.debug("[ws] unexpected trnm=%s msg=%s", trnm, str(msg)[:200])


async def fetch_condition_list(token: Optional[str] = None) -> list[dict]:
    """HTS 등록 조건식 목록 [{"seq":"0","name":"..."}, ...] 반환."""
    if token is None:
        token = get_token()
    if not token:
        raise KiwoomScreenerError("no token")
    async with websockets.connect(WS_URL, open_timeout=LOGIN_TIMEOUT) as ws:
        await _login(ws, token)
        await ws.send(json.dumps({"trnm": "CNSRLST"}))
        msg = await _recv_until(ws, "CNSRLST")
        rc = msg.get("return_code", -1)
        if rc != 0:
            raise KiwoomScreenerError(f"CNSRLST rc={rc} msg={msg.get('return_msg')}")
        data = msg.get("data") or []
        out: list[dict] = []
        for row in data:
            if isinstance(row, list) and len(row) >= 2:
                out.append({"seq": str(row[0]), "name": str(row[1])})
            elif isinstance(row, dict):
                seq = row.get("seq") or row.get("Seq") or row.get("0")
                name = row.get("name") or row.get("Name") or row.get("1")
                if seq is not None:
                    out.append({"seq": str(seq), "name": str(name or "")})
        return out


def _extract_code(row: dict) -> Optional[str]:
    """다양한 키 명세 대응 (FID 9001 / jmcode / stk_cd 등)."""
    for k in ("9001", "jmcode", "stk_cd", "stkCd", "code"):
        v = row.get(k)
        if v:
            s = str(v).strip()
            # 일부 응답은 "A005930" 처럼 prefix 붙음
            if s.startswith(("A", "a")) and s[1:].isdigit():
                s = s[1:]
            return s
    return None


def _extract_field(row: dict, *keys) -> Optional[str]:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


async def fetch_condition_candidates(
    seq: Optional[str] = None,
    name: Optional[str] = None,
    stex_tp: str = "K",
    token: Optional[str] = None,
) -> list[dict]:
    """조건식 1개를 단발 실행하여 후보 종목 리스트를 반환.
    seq 또는 name 중 하나는 필수. name 지정 시 CNSRLST에서 매칭.

    반환 row 예: {"code":"005930","name":"삼성전자","price":..,"change_pct":..,"raw":{...}}
    HTS에 조건식 미등록이면 [] 반환 (예외 아님).
    """
    if token is None:
        token = get_token()
    if not token:
        raise KiwoomScreenerError("no token")

    async with websockets.connect(WS_URL, open_timeout=LOGIN_TIMEOUT) as ws:
        await _login(ws, token)

        # seq 결정
        if seq is None:
            await ws.send(json.dumps({"trnm": "CNSRLST"}))
            lst_msg = await _recv_until(ws, "CNSRLST")
            data = lst_msg.get("data") or []
            if not data:
                logger.warning("[kiwoom_screener] HTS 조건식 0개. PoC 빈 결과")
                return []
            target = None
            for row in data:
                row_seq = row[0] if isinstance(row, list) else (row.get("seq") or row.get("Seq"))
                row_name = row[1] if isinstance(row, list) and len(row) > 1 else (row.get("name") or row.get("Name"))
                if name and row_name and name in str(row_name):
                    target = str(row_seq)
                    break
            if target is None:
                # 첫 번째 조건식 사용
                first = data[0]
                target = str(first[0] if isinstance(first, list) else (first.get("seq") or first.get("Seq")))
            seq = target

        # CNSRREQ 단발
        await ws.send(json.dumps({
            "trnm": "CNSRREQ",
            "seq": str(seq),
            "search_type": "0",
            "stex_tp": stex_tp,
            "cont_yn": "N",
            "next_key": "",
        }))
        try:
            msg = await _recv_until(ws, "CNSRREQ", timeout=CNSRREQ_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[kiwoom_screener] CNSRREQ 무응답 (장외시간 추정 또는 권한 미부여). 빈 결과 반환")
            return []
        rc = msg.get("return_code", -1)
        if rc != 0:
            logger.warning("[kiwoom_screener] CNSRREQ rc=%s msg=%s", rc, msg.get("return_msg"))
            return []

        rows = msg.get("data") or []
        out: list[dict] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            code = _extract_code(r)
            if not code:
                continue
            entry = {
                "code": code,
                "name": _extract_field(r, "302", "name", "stk_nm", "Name") or "",
                "price": _extract_field(r, "10", "price", "cur_prc"),
                "change_pct": _extract_field(r, "12", "change_pct", "flu_rt"),
                "volume": _extract_field(r, "13", "volume", "trde_qty"),
                "raw": r,
            }
            out.append(entry)
        return out


def to_stockdata_list(rows: list[dict], market: str = "KOSPI"):
    """조건검색 결과 → engine.collectors.StockData 리스트.
    누락 필드는 0/빈값. 후속 _analyze_stock에서 차트/호가로 보강됨."""
    from engine.collectors import StockData
    out = []
    for r in rows:
        code = r.get("code")
        if not code:
            continue
        # 부호 처리: 키움 등락률은 "+1.23" 또는 "-2.34" 형식 가능
        def _f(v, default=0.0):
            if v is None or v == "":
                return default
            try:
                s = str(v).replace("+", "").strip()
                return float(s) if s else default
            except (ValueError, TypeError):
                return default
        def _i(v, default=0):
            try:
                s = str(v or "").replace("+", "").replace(",", "").strip()
                return int(float(s)) if s else default
            except (ValueError, TypeError):
                return default
        out.append(StockData(
            code=str(code),
            name=str(r.get("name") or ""),
            market=market,
            close=_i(r.get("price")),
            volume=_i(r.get("volume")),
            change_pct=_f(r.get("change_pct")),
        ))
    return out


async def fetch_kiwoom_candidates_safe(
    seq: Optional[str] = None,
    name: Optional[str] = None,
    market: str = "KOSPI",
) -> list:
    """예외 안전 래퍼. 실패/타임아웃/조건미등록 시 [] 반환."""
    try:
        rows = await asyncio.wait_for(
            fetch_condition_candidates(seq=seq, name=name),
            timeout=CNSRREQ_TIMEOUT + 5,
        )
    except (asyncio.TimeoutError, KiwoomScreenerError, OSError, websockets.exceptions.WebSocketException) as e:
        logger.warning("[kiwoom_screener] 조건검색 폴백 (%s: %s)", type(e).__name__, e)
        return []
    return to_stockdata_list(rows, market=market)


# ─── CLI ───
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def _main():
        print("=== 키움 조건검색 PoC ===")
        try:
            lst = await fetch_condition_list()
        except Exception as e:
            print(f"[CNSRLST] 실패: {e!r}")
            return
        print(f"[CNSRLST] 등록된 조건식 {len(lst)}개:")
        for it in lst[:20]:
            print(f"  seq={it['seq']:>3}  name={it['name']}")
        if not lst:
            print("→ HTS(영웅문)에서 조건식을 먼저 등록해야 합니다.")
            return

        first_seq = lst[0]["seq"]
        print(f"\n[CNSRREQ] seq={first_seq} 단발 조회...")
        try:
            picks = await fetch_condition_candidates(seq=first_seq)
        except Exception as e:
            print(f"실패: {e!r}")
            return
        print(f"종목 {len(picks)}개:")
        for p in picks[:15]:
            print(f"  {p['code']:>7}  {p['name']:12}  "
                  f"price={p['price']}  chg={p['change_pct']}  vol={p['volume']}")

    asyncio.run(_main())
