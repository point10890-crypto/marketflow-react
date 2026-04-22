"""
키움증권 REST API 클라이언트
- 토큰 자동 캐싱 (data/kiwoom_token.json)
- 만료 1시간 전 자동 갱신
- KIS API 폴백용 데이터 조회
"""
import os
import json
import time
import logging
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

try:
    from app.utils.atomic_json import write_json_atomic
except ImportError:
    import tempfile as _tempfile
    def write_json_atomic(filepath, data, indent=2, ensure_ascii=False, **kw):
        d = os.path.dirname(os.path.abspath(filepath)) or '.'
        os.makedirs(d, exist_ok=True)
        fd, tmp = _tempfile.mkstemp(prefix='.tmp_', suffix='.json', dir=d)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii, **kw)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp, os.path.abspath(filepath))
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise

load_dotenv()
logger = logging.getLogger(__name__)

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
DATA_DIR = BASE_DIR / "data"
TOKEN_FILE = DATA_DIR / "kiwoom_token.json"

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
KIWOOM_APP_KEY = os.getenv("KIWOOM_APP_KEY", "")
KIWOOM_APP_SECRET = os.getenv("KIWOOM_APP_SECRET", "")

# 외부 프로젝트(autotrading_project 등)와 동일 appkey 를 공유할 때 토큰 경합 방지.
# 우선순위: 자체 캐시 → 외부 캐시 → 신규 발급.
# 외부 캐시가 유효하면 /oauth2/token 호출을 건너뛰어 상대 프로젝트의 활성 토큰을 무효화하지 않는다.
EXTERNAL_TOKEN_CACHE = os.getenv(
    "KIWOOM_EXTERNAL_TOKEN_CACHE",
    r"C:\autotrading_project\data\token_cache.json"
)


def _load_cached_token() -> dict | None:
    """캐시된 토큰 로드. 만료 1시간 전이면 None 반환."""
    if not TOKEN_FILE.exists():
        return None
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        expires_dt = cached.get("expires_dt", "")
        if not expires_dt:
            return None
        exp_time = datetime.strptime(expires_dt, "%Y%m%d%H%M%S")
        # 만료 1시간 전이면 갱신
        remaining = (exp_time - datetime.now()).total_seconds()
        if remaining < 3600:
            logger.info(f"[kiwoom] 토큰 만료 임박 ({remaining:.0f}s 남음), 재발급")
            return None
        return cached
    except Exception as e:
        logger.warning(f"[kiwoom] 토큰 캐시 로드 실패: {e}")
        return None


def _load_external_token() -> dict | None:
    """외부 프로젝트(autotrading_project) 의 token_cache.json 에서 유효 토큰 조회.

    포맷: {"<mode>:<appkey_prefix>": {"token": ..., "expires_at": epoch_float, ...}}
    MarketFlow 자체 포맷 {"token": ..., "expires_dt": "YYYYMMDDHHMMSS"} 로 변환 반환.
    유효 토큰 없거나 파일 없으면 None.
    """
    if not EXTERNAL_TOKEN_CACHE or not os.path.exists(EXTERNAL_TOKEN_CACHE):
        return None
    if not KIWOOM_APP_KEY:
        return None
    try:
        with open(EXTERNAL_TOKEN_CACHE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # mode 는 KIWOOM_BASE_URL 로 판정
        mode = "paper" if "mockapi" in (KIWOOM_BASE_URL or "") else "live"
        cache_key = f"{mode}:{KIWOOM_APP_KEY[:8]}"
        entry = raw.get(cache_key)
        if not entry:
            return None
        expires_at = float(entry.get("expires_at", 0))
        # 만료 5분 전까지만 유효 (autotrading 과 동일 마진)
        if expires_at - time.time() < 300:
            return None
        token = entry.get("token")
        if not token:
            return None
        expires_dt = datetime.fromtimestamp(expires_at).strftime("%Y%m%d%H%M%S")
        logger.info(f"[kiwoom] 외부 캐시(autotrading) 토큰 재사용 — 만료까지 {int(expires_at - time.time())}s")
        return {"token": token, "expires_dt": expires_dt, "return_code": 0, "shared_from": EXTERNAL_TOKEN_CACHE}
    except Exception as e:
        logger.warning(f"[kiwoom] 외부 토큰 캐시 로드 실패: {e}")
        return None


def _save_token(token_data: dict):
    """토큰을 파일에 저장."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        write_json_atomic(str(TOKEN_FILE), token_data)
        logger.info(f"[kiwoom] 토큰 저장 완료 (만료: {token_data.get('expires_dt')})")
    except Exception as e:
        logger.warning(f"[kiwoom] 토큰 저장 실패: {e}")


def _expires_dt_to_epoch(expires_dt: str) -> float:
    """MarketFlow 자체 캐시의 expires_dt ('YYYYMMDDHHMMSS') → epoch float."""
    try:
        return datetime.strptime(expires_dt, "%Y%m%d%H%M%S").timestamp()
    except Exception:
        return 0.0


def get_token() -> str | None:
    """유효한 토큰 반환.

    동일 appkey 를 쓰는 외부 프로젝트(autotrading_project)와 경합 방지 —
    **더 늦게 발급된(expires 가 더 먼) 토큰이 실제로 Kiwoom 에서 유효** 하므로
    양 캐시를 비교해 최신 토큰을 선택.

    우선순위:
      1. 외부/자체 캐시 둘 중 expires 가 더 먼 유효 토큰
      2. 유효 캐시 없으면 /oauth2/token 신규 발급 (자체 캐시에만 저장)

    외부 토큰은 자체 캐시에 저장하지 않음 — autotrading 이 재발급해 stale 된
    자체 캐시를 덮어쓰지 않도록, 항상 양쪽을 다시 비교.
    """
    if not KIWOOM_APP_KEY or not KIWOOM_APP_SECRET:
        logger.warning("[kiwoom] KIWOOM_APP_KEY/SECRET 미설정")
        return None

    external = _load_external_token()
    own = _load_cached_token()

    ext_exp = _expires_dt_to_epoch(external.get("expires_dt", "")) if external else 0.0
    own_exp = _expires_dt_to_epoch(own.get("expires_dt", "")) if own else 0.0

    # 둘 중 expires 가 더 먼 토큰 선택 (더 최근 발급 = 실제 활성 토큰)
    if ext_exp > own_exp and external:
        logger.info(f"[kiwoom] 외부(autotrading) 토큰 선택 — 만료까지 {int(ext_exp - time.time())}s")
        return external["token"]
    if own:
        return own["token"]
    if external:  # own 없고 외부만 있을 때
        return external["token"]

    # 신규 발급
    return _refresh_token()


def _refresh_token() -> str | None:
    """자체 캐시 무시하고 /oauth2/token 신규 발급 후 저장."""
    try:
        resp = requests.post(
            f"{KIWOOM_BASE_URL}/oauth2/token",
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json={
                "grant_type": "client_credentials",
                "appkey": KIWOOM_APP_KEY,
                "secretkey": KIWOOM_APP_SECRET,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("return_code") != 0:
            logger.error(f"[kiwoom] 토큰 발급 실패: {data.get('return_msg')}")
            return None
        _save_token(data)
        logger.info("[kiwoom] 토큰 신규 발급 성공")
        return data["token"]
    except Exception as e:
        logger.error(f"[kiwoom] 토큰 발급 에러: {e}")
        return None


def force_refresh_token() -> str | None:
    """캐시 무시하고 강제 재발급. 외부 프로젝트와 토큰 경합으로 인한
    'Token이 유효하지 않습니다(8005)' 복구용. 호출 후 autotrading 이 다음 call
    때 자신의 캐시가 유효해도 실패할 수 있지만, autotrading 은 자동 재발급하므로
    양쪽 자가 복구.
    """
    if not KIWOOM_APP_KEY or not KIWOOM_APP_SECRET:
        return None
    logger.warning("[kiwoom] 토큰 강제 재발급 — 외부 경합 의심")
    try:
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
    except Exception:
        pass
    return _refresh_token()


def _make_headers(api_id: str, cont_yn: str = "N", next_key: str = "") -> dict | None:
    """API 호출용 공통 헤더 생성."""
    token = get_token()
    if not token:
        return None
    return {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "cont-yn": cont_yn,
        "next-key": next_key,
        "api-id": api_id,
    }


def call_api(api_id: str, body: dict, cont_yn: str = "N", next_key: str = "") -> dict | None:
    """키움 REST API 범용 호출."""
    headers = _make_headers(api_id, cont_yn, next_key)
    if not headers:
        return None
    try:
        resp = requests.post(
            f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
            headers=headers,
            json=body,
            timeout=15,
        )
        data = resp.json()
        if data.get("return_code", -1) != 0:
            logger.warning(f"[kiwoom] API {api_id} 에러: {data.get('return_msg')}")
            return None
        return data
    except Exception as e:
        logger.error(f"[kiwoom] API {api_id} 호출 실패: {e}")
        return None


# ─── 편의 함수 ───

def get_stock_quote(stk_cd: str) -> dict | None:
    """주식 호가 조회 (ka10004)."""
    return call_api("ka10004", {"stk_cd": stk_cd})


def get_daily_chart(stk_cd: str, qry_dt: str = "", indc_tp: str = "0") -> dict | None:
    """일별 주가 조회 (ka10086). qry_dt: YYYYMMDD, indc_tp: 0=수량, 1=금액(백만)."""
    if not qry_dt:
        qry_dt = datetime.now().strftime("%Y%m%d")
    return call_api("ka10086", {"stk_cd": stk_cd, "qry_dt": qry_dt, "indc_tp": indc_tp})


def get_daily_ohlcv(stk_cd: str) -> dict | None:
    """주식일주월시분요청 (ka10005) — 일봉 OHLCV."""
    return call_api("ka10005", {"stk_cd": stk_cd})


def get_investor_trading_market(mrkt_tp: str = "000", stex_tp: str = "3") -> dict | None:
    """장중 투자자별 매매 — 시장 전체 (ka10063).
    mrkt_tp: 000=전체, 001=코스피, 002=코스닥
    stex_tp: 3=KRX"""
    return call_api("ka10063", {
        "mrkt_tp": mrkt_tp, "amt_qty_tp": "1", "invsr": "6",
        "frgn_all": "0", "smtm_netprps_tp": "0", "stex_tp": stex_tp,
    })


def get_investor_after_close(mrkt_tp: str = "000", stex_tp: str = "3") -> dict | None:
    """장마감후 투자자별 매매 (ka10066).
    mrkt_tp: 000=전체, 001=코스피, 002=코스닥"""
    return call_api("ka10066", {
        "mrkt_tp": mrkt_tp, "amt_qty_tp": "1",
        "trde_tp": "0", "stex_tp": stex_tp,
    })


def get_institution_daily(strt_dt: str, end_dt: str, mrkt_tp: str = "001") -> dict | None:
    """일별 기관 매매 종목 (ka10044). trde_tp: 1=순매수."""
    return call_api("ka10044", {
        "strt_dt": strt_dt, "end_dt": end_dt,
        "trde_tp": "1", "mrkt_tp": mrkt_tp, "stex_tp": "3",
    })


def get_institution_trend(stk_cd: str, strt_dt: str = "", end_dt: str = "") -> dict | None:
    """종목별 기관 매매 추이 (ka10045)."""
    if not end_dt:
        end_dt = datetime.now().strftime("%Y%m%d")
    if not strt_dt:
        from datetime import timedelta
        strt_dt = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    return call_api("ka10045", {
        "stk_cd": stk_cd, "strt_dt": strt_dt, "end_dt": end_dt,
        "orgn_prsm_unp_tp": "1", "for_prsm_unp_tp": "1",
    })


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== 키움 REST API 테스트 ===")

    token = get_token()
    if token:
        print(f"토큰: {token[:20]}...")
    else:
        print("토큰 발급 실패")
        exit(1)

    # 삼성전자 호가 테스트
    quote = get_stock_quote("005930")
    if quote:
        print(f"\n삼성전자 호가:")
        print(f"  매도1호가: {quote.get('sel_fpr_bid')}")
        print(f"  매수1호가: {quote.get('buy_fpr_bid')}")
        print(f"  매도잔량: {quote.get('sel_fpr_req')}")
        print(f"  매수잔량: {quote.get('buy_fpr_req')}")
    else:
        print("호가 조회 실패")

    # 일별 주가 테스트
    daily = get_daily_chart("005930")
    if daily:
        print(f"\n삼성전자 일별 주가: 데이터 키 {len(daily)}개")
    else:
        print("일별 주가 조회 실패")

    print("\n=== 완료 ===")
