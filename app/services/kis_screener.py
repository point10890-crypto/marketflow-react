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
import hashlib
import logging
import math
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from collections import defaultdict
from threading import Lock, local

from filelock import FileLock, Timeout
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

from app.utils.paths import DATA_DIR
from app.utils.atomic_json import write_json_atomic


def _load_runtime_env():
    """Load repo .env when this module is invoked outside Flask/scheduler."""
    try:
        from dotenv import load_dotenv
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        load_dotenv(os.path.join(root_dir, ".env"), override=False)
    except Exception as e:
        logger.debug("kis_screener dotenv load skipped: %s", e)


_load_runtime_env()

# ─── 설정 ───
_paper = os.environ.get("KIS_PAPER", "true").lower() in ("true", "1")
BASE_URL = "https://openapivts.koreainvestment.com:29443" if _paper else "https://openapi.koreainvestment.com:9443"
def _app_key():
    return os.environ.get("KIS_APP_KEY", "")

def _app_secret():
    return os.environ.get("KIS_APP_SECRET", "")

ETF_KEYWORDS = [
    "KODEX", "TIGER", "KBSTAR", "KOSEF", "ARIRANG", "HANARO",
    "SOL", "ACE", "RISE", "PLUS", "BNK", "ETN", "인버스", "레버리지",
    "선물", "2X", "3X", "KINDEX", "TIMEFOLIO", "WOORI",
]

# ─── 토큰 관리 ───
_token_lock = Lock()
_token_cache = {"token": None, "expires_at": 0, "namespace": None}
_TOKEN_CACHE_FILE = os.path.join(DATA_DIR, "kis_token_cache.json")
_TOKEN_EXPIRY_MARGIN_SECONDS = 60
_DEFAULT_TOKEN_TTL_SECONDS = 23 * 3600
_TOKEN_CACHE_VERSION = 2
_TOKEN_LOCK_TIMEOUT_SECONDS = 15
SCREENER_POLLER_LOCK = os.path.join(DATA_DIR, "claw", "kis_poller.lock")

# Reuse TLS connections across the dozens of quote/enrichment calls in one
# scan.  Worker-local Session objects avoid sharing mutable cookie/header state,
# while the mounted adapter owns one process-wide, thread-safe urllib3 pool.
_HTTP_POOL_SIZE = 16
_HTTP_ADAPTER = HTTPAdapter(
    pool_connections=_HTTP_POOL_SIZE,
    pool_maxsize=_HTTP_POOL_SIZE,
    pool_block=True,
    max_retries=0,
)
_HTTP_LOCAL = local()
_ORIGINAL_REQUESTS_GET = requests.get

# KIS documents a lower request allowance for paper trading.  Concurrent
# workers still start requests below that limit; concurrency only overlaps
# network latency and never turns into an unbounded burst.
_api_rate_lock = Lock()
_api_next_request_at = 0.0
_API_ATTEMPT_LOCAL = local()
_API_RATE_STATE_VERSION = 1
_API_RATE_LOCK_TIMEOUT_SECONDS = 10
_SCREENER_POLL_STATE_VERSION = 1


def _token_namespace():
    """Return a non-secret cache namespace for the active KIS credentials."""
    fingerprint = hashlib.sha256(_app_key().encode("utf-8")).hexdigest()
    return f"{'paper' if _paper else 'real'}:{fingerprint}"


def _token_cache_lock_path():
    # One lock protects both issuance and the shared multi-namespace document.
    return f"{_TOKEN_CACHE_FILE}.lock"


@contextmanager
def _track_api_attempts():
    """Track physical HTTP attempts made by one scan, including worker threads."""
    tracker = {
        "lock": Lock(),
        "get_attempts": 0,
        "token_issue_attempts": 0,
        "rate_limit_responses": 0,
    }
    previous = getattr(_API_ATTEMPT_LOCAL, "tracker", None)
    _API_ATTEMPT_LOCAL.tracker = tracker
    try:
        yield tracker
    finally:
        if previous is None:
            try:
                delattr(_API_ATTEMPT_LOCAL, "tracker")
            except AttributeError:
                pass
        else:
            _API_ATTEMPT_LOCAL.tracker = previous


def _record_api_attempt(kind):
    tracker = getattr(_API_ATTEMPT_LOCAL, "tracker", None)
    if tracker is None:
        return
    key = "token_issue_attempts" if kind == "token" else "get_attempts"
    with tracker["lock"]:
        tracker[key] += 1


def _record_rate_limit_response():
    tracker = getattr(_API_ATTEMPT_LOCAL, "tracker", None)
    if tracker is None:
        return
    with tracker["lock"]:
        tracker["rate_limit_responses"] += 1


def _attempt_metrics(tracker, logical_calls):
    with tracker["lock"]:
        get_attempts = tracker["get_attempts"]
        token_attempts = tracker["token_issue_attempts"]
        rate_limit_responses = tracker.get("rate_limit_responses", 0)
    metrics = {
        "logical_calls": logical_calls,
        "get_attempts": get_attempts,
        "token_issue_attempts": token_attempts,
        "physical_attempts_total": get_attempts + token_attempts,
    }
    # Keep the normal metrics payload backwards-compatible while exposing the
    # signal needed to apply a longer scan cooldown after an EGW00201 response.
    if rate_limit_responses:
        metrics["rate_limit_responses"] = rate_limit_responses
    return metrics


def _call_with_attempt_tracker(call, tracker):
    previous = getattr(_API_ATTEMPT_LOCAL, "tracker", None)
    _API_ATTEMPT_LOCAL.tracker = tracker
    try:
        return call()
    finally:
        if previous is None:
            try:
                delattr(_API_ATTEMPT_LOCAL, "tracker")
            except AttributeError:
                pass
        else:
            _API_ATTEMPT_LOCAL.tracker = previous


def _http_session():
    session = getattr(_HTTP_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.mount("https://", _HTTP_ADAPTER)
        session.mount("http://", _HTTP_ADAPTER)
        _HTTP_LOCAL.session = session
    return session


def _http_get(*args, **kwargs):
    # Preserve the long-standing requests.get monkeypatch seam used by focused
    # tests and local diagnostics. Production calls use the pooled transport.
    if requests.get is not _ORIGINAL_REQUESTS_GET:
        return requests.get(*args, **kwargs)
    return _http_session().get(*args, **kwargs)


def _api_request_interval_seconds():
    raw = os.environ.get("KIS_API_MIN_REQUEST_INTERVAL_SECONDS", "")
    if raw:
        try:
            configured = float(raw)
            if math.isfinite(configured) and configured >= 0:
                # This is a *minimum* interval. Never silently cap a positive
                # operator override, because doing so can violate a stricter
                # account-wide quota chosen by the deployment.
                return configured
        except ValueError:
            pass
        logger.warning("invalid KIS_API_MIN_REQUEST_INTERVAL_SECONDS=%r", raw)
    # Keep meaningful headroom for other KIS consumers using the same app key.
    # Running this scanner at the documented account-wide ceiling caused
    # EGW00201 responses when the scheduler made unrelated requests nearby.
    return 0.50 if _paper else 0.20


def _api_rate_state_path():
    return os.path.join(
        os.path.dirname(SCREENER_POLLER_LOCK) or ".", "kis_api_rate_state.json"
    )


def _api_rate_file_lock_path():
    return f"{_api_rate_state_path()}.lock"


def _empty_api_rate_state():
    return {"version": _API_RATE_STATE_VERSION, "accounts": {}}


def _read_api_rate_state():
    path = _api_rate_state_path()
    if not os.path.exists(path):
        return _empty_api_rate_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if (
            isinstance(state, dict)
            and state.get("version") == _API_RATE_STATE_VERSION
            and isinstance(state.get("accounts"), dict)
        ):
            return state
    except (IOError, OSError, json.JSONDecodeError, TypeError) as e:
        logger.warning("KIS shared rate state load failed: %s", e)
    return _empty_api_rate_state()


def _reserve_shared_api_slot(interval, *, now=None):
    """Reserve one account-scoped request slot shared by all app processes."""
    now = time.time() if now is None else float(now)
    path = _api_rate_state_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with FileLock(_api_rate_file_lock_path(), timeout=_API_RATE_LOCK_TIMEOUT_SECONDS):
        state = _read_api_rate_state()
        accounts = state.setdefault("accounts", {})
        namespace = _token_namespace()
        account = accounts.get(namespace)
        if not isinstance(account, dict):
            account = {}
        next_request_at = max(
            _safe_float(account.get("next_request_at"), 0.0),
            _safe_float(account.get("backoff_until"), 0.0),
        )
        slot_at = max(now, next_request_at)
        account.update({
            "next_request_at": slot_at + interval,
            "backoff_until": _safe_float(account.get("backoff_until"), 0.0),
            "updated_at": now,
        })
        accounts[namespace] = account
        write_json_atomic(path, state, indent=0)
    return max(0.0, slot_at - now)


def _rate_limit_backoff_seconds():
    default = max(1.0, _api_request_interval_seconds() * 4)
    raw = os.environ.get("KIS_API_RATE_LIMIT_BACKOFF_SECONDS", str(default))
    try:
        value = float(raw)
        if math.isfinite(value) and value >= 1.0:
            return value
    except ValueError:
        pass
    logger.warning("invalid KIS_API_RATE_LIMIT_BACKOFF_SECONDS=%r", raw)
    return default


def _publish_shared_rate_limit_backoff(delay, *, now=None):
    """Publish an EGW00201 quiet window for peer processes using this key."""
    now = time.time() if now is None else float(now)
    path = _api_rate_state_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with FileLock(_api_rate_file_lock_path(), timeout=_API_RATE_LOCK_TIMEOUT_SECONDS):
        state = _read_api_rate_state()
        accounts = state.setdefault("accounts", {})
        namespace = _token_namespace()
        account = accounts.get(namespace)
        if not isinstance(account, dict):
            account = {}
        backoff_until = max(
            _safe_float(account.get("backoff_until"), 0.0), now + delay
        )
        account.update({
            "backoff_until": backoff_until,
            "next_request_at": max(
                _safe_float(account.get("next_request_at"), 0.0), backoff_until
            ),
            "updated_at": now,
        })
        accounts[namespace] = account
        write_json_atomic(path, state, indent=0)
    return max(0.0, backoff_until - now)


def _pace_api_request_locally(interval):
    """Best-effort fallback if the process-shared state cannot be locked."""
    global _api_next_request_at
    with _api_rate_lock:
        now = time.monotonic()
        delay = _api_next_request_at - now
        if delay > 0:
            time.sleep(delay)
            now = time.monotonic()
        _api_next_request_at = now + interval


def _pace_api_request():
    interval = _api_request_interval_seconds()
    if interval <= 0:
        return
    try:
        delay = _reserve_shared_api_slot(interval)
    except (Timeout, IOError, OSError, TypeError, ValueError) as e:
        logger.warning("KIS shared rate reservation failed; using local pacing: %s", e)
        _pace_api_request_locally(interval)
        return
    if delay > 0:
        time.sleep(delay)


def _scanner_max_workers():
    default = 4 if _paper else 8
    raw = os.environ.get("KIS_SCREENER_MAX_WORKERS", str(default))
    try:
        return min(_HTTP_POOL_SIZE, max(1, int(raw)))
    except ValueError:
        logger.warning("invalid KIS_SCREENER_MAX_WORKERS=%r", raw)
        return default


def _empty_token_cache_document():
    return {"version": _TOKEN_CACHE_VERSION, "tokens": {}}


def _read_token_cache_document():
    if not os.path.exists(_TOKEN_CACHE_FILE):
        return _empty_token_cache_document()
    try:
        with open(_TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if (
            isinstance(data, dict)
            and data.get("version") == _TOKEN_CACHE_VERSION
            and isinstance(data.get("tokens"), dict)
        ):
            return data
        # Version-1 files contained only token/expires_at, so there is no safe
        # way to know which app key or paper/real endpoint issued the token.
        # Ignore that one-time legacy cache instead of assigning it to a mode
        # by guess; the next successful issuance atomically migrates the file.
        logger.info("ignoring unnamespaced legacy KIS token cache")
    except (IOError, OSError, json.JSONDecodeError, AttributeError, TypeError) as e:
        logger.warning("KIS token cache load failed: %s", e)
    return _empty_token_cache_document()


def _load_cached_token(namespace=None):
    namespace = namespace or _token_namespace()
    record = _read_token_cache_document().get("tokens", {}).get(namespace)
    if not isinstance(record, dict):
        return None
    token = record.get("token")
    expires_at = _safe_float(record.get("expires_at"), 0.0)
    expected_mode, expected_fingerprint = namespace.split(":", 1)
    if (
        token
        and record.get("mode") == expected_mode
        and record.get("app_key_fingerprint") == expected_fingerprint
        and _token_is_usable(expires_at)
    ):
        # Keep the original absolute expiry. Extending a disk token to
        # ``now + 23h`` on every process start can make an old token look valid
        # beyond the expiry issued by KIS.
        return token, expires_at
    return None


def _save_token_cache(token, expires_at, namespace=None):
    """Merge one namespaced token into the cache while its file lock is held."""
    namespace = namespace or _token_namespace()
    try:
        data = _read_token_cache_document()
        tokens = data.setdefault("tokens", {})
        # Do not retain expired bearer tokens indefinitely.
        data["tokens"] = {
            key: value
            for key, value in tokens.items()
            if isinstance(value, dict) and _token_is_usable(value.get("expires_at"))
        }
        mode, fingerprint = namespace.split(":", 1)
        data["tokens"][namespace] = {
            "token": token,
            "expires_at": expires_at,
            "mode": mode,
            "app_key_fingerprint": fingerprint,
        }
        write_json_atomic(_TOKEN_CACHE_FILE, data, indent=0)
        return True
    except (IOError, OSError, TypeError) as e:
        logger.warning("KIS token cache write failed: %s", e)
        return False


def _token_is_usable(expires_at, now=None):
    """Return True only when a token remains valid past the safety margin."""
    current = time.time() if now is None else now
    return _safe_float(expires_at, 0.0) > current + _TOKEN_EXPIRY_MARGIN_SECONDS


def _token_expiry_from_payload(payload, issued_at=None):
    """Extract the absolute expiry KIS issued, with a conservative fallback."""
    issued_at = time.time() if issued_at is None else issued_at
    if not isinstance(payload, dict):
        return issued_at + _DEFAULT_TOKEN_TTL_SECONDS

    raw_expiry = payload.get("access_token_token_expired") or payload.get("expires_at")
    if raw_expiry:
        try:
            numeric_expiry = float(raw_expiry)
            if numeric_expiry > issued_at:
                return numeric_expiry
        except (TypeError, ValueError):
            pass
        expiry_text = str(raw_expiry).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(expiry_text, fmt).timestamp()
            except ValueError:
                continue

    expires_in = _safe_float(payload.get("expires_in"), 0.0)
    if expires_in > 0:
        return issued_at + expires_in
    return issued_at + _DEFAULT_TOKEN_TTL_SECONDS


def get_token():
    with _token_lock:
        namespace = _token_namespace()
        if (
            _token_cache.get("namespace") == namespace
            and _token_cache["token"]
            and _token_is_usable(_token_cache["expires_at"])
        ):
            return _token_cache["token"]
        if not _app_key() or not _app_secret():
            logger.error("KIS_APP_KEY / KIS_APP_SECRET 환경변수 없음")
            return None

        os.makedirs(os.path.dirname(os.path.abspath(_TOKEN_CACHE_FILE)), exist_ok=True)
        issue_lock = FileLock(_token_cache_lock_path())
        try:
            issue_lock.acquire(timeout=_TOKEN_LOCK_TIMEOUT_SECONDS)
        except (Timeout, OSError) as e:
            logger.error("KIS token cache/issuance lock unavailable: %s", e)
            return None
        try:
            # Re-read only after acquiring the process-shared lock. A sibling
            # process may have issued and persisted the token while we waited.
            cached = _load_cached_token(namespace)
            if cached:
                token, expires_at = cached
                _token_cache.update({
                    "token": token,
                    "expires_at": expires_at,
                    "namespace": namespace,
                })
                return token

            _record_api_attempt("token")
            res = requests.post(f"{BASE_URL}/oauth2/tokenP", json={
                "grant_type": "client_credentials",
                "appkey": _app_key(), "appsecret": _app_secret(),
            }, timeout=10)
            if res.status_code != 200:
                logger.error(f"KIS 토큰 발급 실패: {res.status_code}")
                return None
            payload = res.json()
            token = payload.get("access_token")
            if token:
                expires_at = _token_expiry_from_payload(payload)
                _token_cache.update({
                    "token": token,
                    "expires_at": expires_at,
                    "namespace": namespace,
                })
                _save_token_cache(token, expires_at, namespace)
            return token
        except Exception as e:
            logger.error(f"KIS 토큰 발급 에러: {e}")
            return None
        finally:
            issue_lock.release()


def invalidate_token(expected_token=None):
    with _token_lock:
        namespace = _token_namespace()
        # A stale caller may report an old token after another request already
        # refreshed it. Do not discard that newer, usable token.
        if (
            expected_token
            and _token_cache.get("namespace") == namespace
            and _token_cache["token"] not in (None, expected_token)
        ):
            return False
        if _token_cache.get("namespace") == namespace:
            _token_cache.update({"token": None, "expires_at": 0, "namespace": None})

        if not os.path.exists(_TOKEN_CACHE_FILE):
            return True
        cache_lock = FileLock(_token_cache_lock_path())
        try:
            cache_lock.acquire(timeout=_TOKEN_LOCK_TIMEOUT_SECONDS)
        except (Timeout, OSError) as e:
            logger.warning("KIS token invalidation lock unavailable: %s", e)
            return True
        try:
            data = _read_token_cache_document()
            tokens = data.setdefault("tokens", {})
            disk_record = tokens.get(namespace)
            disk_token = disk_record.get("token") if isinstance(disk_record, dict) else None
            # Preserve a token another process refreshed while this caller was
            # reporting an older failed token.
            if not expected_token or disk_token in (None, expected_token):
                tokens.pop(namespace, None)
                write_json_atomic(_TOKEN_CACHE_FILE, data, indent=0)
        except (IOError, OSError, TypeError) as e:
            logger.warning("KIS token cache invalidation failed: %s", e)
        finally:
            cache_lock.release()
        return True


# ─── API 호출 ───

def _headers(token, tr_id):
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": _app_key(), "appsecret": _app_secret(),
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


def _active_request_token(token=None):
    """Prefer the freshest shared token over a stale token held by a caller."""
    with _token_lock:
        if (
            _token_cache.get("namespace") == _token_namespace()
            and _token_cache["token"]
            and _token_is_usable(_token_cache["expires_at"])
        ):
            return _token_cache["token"]
    return token or get_token()


def _api_get(
    token,
    path,
    tr_id,
    params,
    retry=True,
    output_type=list,
    rate_limit_retry=True,
):
    empty_output = {} if output_type is dict else []
    try:
        request_token = _active_request_token(token)
        if not request_token:
            return empty_output
        _pace_api_request()
        _record_api_attempt("get")
        res = _http_get(f"{BASE_URL}{path}",
                        headers=_headers(request_token, tr_id),
                        params=params, timeout=10)
        token_expired = (res.status_code == 401 or
                         (res.status_code == 500 and "EGW00123" in res.text))
        if token_expired and retry:
            logger.warning(f"KIS 토큰 만료 감지 ({res.status_code}), 재발급 시도")
            invalidate_token(expected_token=request_token)
            new_token = get_token()
            if new_token:
                return _api_get(
                    new_token,
                    path,
                    tr_id,
                    params,
                    retry=False,
                    output_type=output_type,
                    rate_limit_retry=rate_limit_retry,
                )
        try:
            body = res.json()
        except Exception:
            logger.warning("KIS API %s HTTP %s non-json body=%s", path, res.status_code, res.text[:160])
            return empty_output
        if not isinstance(body, dict):
            logger.warning("KIS API %s returned unexpected body type=%s", path, type(body).__name__)
            return empty_output
        if body.get("msg_cd") == "EGW00201":
            _record_rate_limit_response()
            # The KIS quota is shared by every consumer of the same app key, so
            # publish the quiet window before retrying. Peer Flask/scheduler
            # processes then reserve slots after the same account-wide window.
            backoff = _rate_limit_backoff_seconds()
            try:
                wait_seconds = _publish_shared_rate_limit_backoff(backoff)
            except (Timeout, IOError, OSError, TypeError, ValueError) as e:
                logger.warning("KIS shared rate-limit backoff publish failed: %s", e)
                wait_seconds = backoff
            if rate_limit_retry:
                # Retry only once. A second EGW00201 still extends the shared
                # backoff and remains an explicit missing input for QA guards.
                logger.info(
                    "KIS API rate limited; retrying once after %.3fs path=%s",
                    wait_seconds, path,
                )
                time.sleep(wait_seconds)
                return _api_get(
                    request_token,
                    path,
                    tr_id,
                    params,
                    retry=retry,
                    output_type=output_type,
                    rate_limit_retry=False,
                )
        if res.status_code != 200:
            logger.warning(
                "KIS API %s HTTP %s msg_cd=%s msg=%s",
                path, res.status_code, body.get("msg_cd"), body.get("msg1"),
            )
            return empty_output
        if body.get("rt_cd") not in (None, "0"):
            logger.warning("KIS API %s rt_cd=%s msg=%s", path, body.get("rt_cd"), body.get("msg1"))
        output = body.get("output", [])
        return output if isinstance(output, output_type) else empty_output
    except Exception as e:
        logger.warning(f"KIS API 호출 실패 {path}: {e}")
        return empty_output


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
                        # KIS defines 0000 as the whole domestic-stock universe.
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


def fetch_price_detail(token, stock_code):
    """현재가 시세 조회 — 52주 최고가/최저가, 최고가 일자 포함"""
    return _api_get(
        token,
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        "FHKST01010100",
        {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
        },
        output_type=dict,
    )


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


def _select_investor_row(investor_data):
    """Return the newest completed investor row.

    During the live session KIS prepends today's date with blank investor
    quantities.  The first completed row is the latest authoritative input;
    treating the blank placeholder as a failed API made every intraday scan
    unsafe even though the prior close was present in the same response.
    """
    if not isinstance(investor_data, list):
        return None
    for row in investor_data:
        if not isinstance(row, dict):
            continue
        if all(
            key in row and row.get(key) not in (None, "")
            for key in ("frgn_ntby_qty", "orgn_ntby_qty")
        ):
            return row
    return None


def _score_investor(investor_data):
    today = _select_investor_row(investor_data)
    if today is None:
        return 0, 0, 0
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


def _positive_int_or_none(val):
    """Parse a strictly positive integer without inventing a denominator."""
    try:
        parsed = int(val)
    except (ValueError, TypeError):
        return None
    return parsed if parsed > 0 else None


def _positive_float_or_none(val):
    try:
        parsed = float(val)
    except (ValueError, TypeError):
        return None
    return parsed if parsed > 0 else None


def _has_investor_inputs(investor_data):
    return _select_investor_row(investor_data) is not None


def _score_volume_surge(item):
    if not isinstance(item, dict):
        return 0, 0.0
    vol = _safe_int(item.get("acml_vol"))
    prdy = _positive_int_or_none(item.get("prdy_vol"))
    if prdy is not None:
        ratio = (vol / prdy) * 100
    else:
        # inquire-price does not expose prdy_vol for ordinary equities, but it
        # does expose the authoritative KIS-computed current/previous volume
        # percentage. This is a valid baseline, not an inferred denominator.
        ratio = _positive_float_or_none(item.get("prdy_vrss_vol_rate"))
    if ratio is None:
        # Missing previous-day volume is unknown, not one share. The old
        # denominator fallback produced ratios in the millions and a free +10.
        # Keep the historical numeric response type; data_quality carries the
        # distinction between a measured zero and an unavailable baseline.
        return 0, 0.0
    if ratio >= 500: return 10, round(ratio, 1)
    if ratio >= 300: return 8, round(ratio, 1)
    if ratio >= 200: return 6, round(ratio, 1)
    if ratio >= 100: return 3, round(ratio, 1)
    return 0, round(ratio, 1)


def _has_volume_baseline(item):
    return isinstance(item, dict) and (
        _positive_int_or_none(item.get("prdy_vol")) is not None
        or _positive_float_or_none(item.get("prdy_vrss_vol_rate")) is not None
    )


def _resolve_volume_source(candidate, surge_row=None, price_detail=None):
    """Choose a same-snapshot authoritative volume baseline with provenance."""
    surge_row = surge_row if isinstance(surge_row, dict) else {}
    price_detail = price_detail if isinstance(price_detail, dict) else {}
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    current_volume = _safe_int(candidate.get("volume"))

    direct_sources = [
        ("volume_surge_rank.prdy_vol", surge_row),
        (candidate.get("prdy_vol_source") or "candidate.prdy_vol", {
            "acml_vol": current_volume,
            "prdy_vol": candidate.get("prdy_vol"),
        }),
        (f"{candidate.get('candidate_source', 'ranking')}.prdy_vol", raw),
        ("price_detail.prdy_vol", price_detail),
    ]
    for source, row in direct_sources:
        prdy = _positive_int_or_none(row.get("prdy_vol"))
        if prdy is None:
            continue
        return {
            "acml_vol": _safe_int(row.get("acml_vol")) or current_volume,
            "prdy_vol": prdy,
        }, source

    # Official KIS inquire-price fallback. The field is documented as
    # "전일 대비 거래량 비율" and is already the percentage used by scoring.
    ratio_sources = [
        ("price_detail.prdy_vrss_vol_rate", price_detail),
        (f"{candidate.get('candidate_source', 'ranking')}.prdy_vrss_vol_rate", raw),
        ("volume_surge_rank.prdy_vrss_vol_rate", surge_row),
    ]
    for source, row in ratio_sources:
        ratio = _positive_float_or_none(row.get("prdy_vrss_vol_rate"))
        if ratio is None:
            continue
        return {
            "acml_vol": _safe_int(row.get("acml_vol")) or current_volume,
            "prdy_vrss_vol_rate": ratio,
        }, source

    return {"acml_vol": current_volume}, "missing"


def _score_sector(sector_map, sector):
    if not sector or sector not in sector_map:
        return 0, 0
    cnt = sector_map[sector]
    if cnt >= 3: return 10, cnt
    if cnt >= 2: return 7, cnt
    if cnt >= 1: return 3, cnt
    return 0, cnt


def _score_new_high(price_detail, current_price):
    """52주 신고가 근접도 채점 (15점 만점)
    - w52_hgpr: 52주 최고가
    - w52_hgpr_date: 52주 최고가 일자 (YYYYMMDD)

    KIS also returns ``stck_dryy_hgpr`` (calendar-year high), but that is
    intentionally not used as a proxy for a rolling 52-week high.
    """
    if not price_detail or not current_price:
        return 0, {}
    high_52w = _safe_int(price_detail.get("w52_hgpr"))
    high_date_str = price_detail.get("w52_hgpr_date", "")
    low_52w = _safe_int(price_detail.get("w52_lwpr"))
    if not high_52w or high_52w <= 0:
        return 0, {}

    # 신고가 일자가 최근 20 거래일(약 28 캘린더일) 이내인지
    recent = False
    days_since = None
    if high_date_str and len(high_date_str) == 8:
        try:
            high_date = datetime.strptime(high_date_str, "%Y%m%d")
            days_since = (datetime.now() - high_date).days
            recent = 0 <= days_since <= 28  # 20 거래일 ≈ 28 캘린더일
        except ValueError:
            pass

    distance_pct = ((high_52w - current_price) / high_52w) * 100 if high_52w else 0
    info = {
        "high_52w": high_52w,
        "low_52w": low_52w,
        "high_date": high_date_str,
        "days_since": days_since,
        "distance_pct": round(distance_pct, 1),
    }

    # 당일 신고가 갱신 (현재가 >= 52주고가)
    if current_price >= high_52w:
        return 15, info
    # 20일내 신고가 + 현재가 3% 이내
    if recent and distance_pct <= 3:
        return 12, info
    # 20일내 신고가 + 현재가 5% 이내
    if recent and distance_pct <= 5:
        return 10, info
    # 20일내 신고가 + 현재가 10% 이내
    if recent and distance_pct <= 10:
        return 5, info
    return 0, info


def _time_weight():
    h, m = datetime.now().hour, datetime.now().minute
    t = h + m / 60
    if 9.0 <= t < 9.5: return 1.2
    if 9.5 <= t < 10.5: return 1.0
    if 10.5 <= t < 11.5: return 1.1
    if 13.0 <= t < 14.0: return 1.15
    if 14.0 <= t < 15.33: return 0.8
    return 1.0


LEADING_FEATURE_SNAPSHOT_SCHEMA_VERSION = 1


def _build_leading_feature_snapshot(
    candidate, *, investor_row, foreign, inst, vol_ratio, volume_source_name,
    high_info, sector_count, market_cap_eok, time_weight, scanned_at,
):
    """주도주 행의 피처 스냅샷 — 채점기가 소비한 원천 입력을 그대로 남긴다.

    점수 산식은 건드리지 않는다. `time_context` 는 현재 `_time_weight()` 배수를
    표시 필드로 기록해 동일 데이터에 대해 점수가 시각에 따라 흔들린 정도를
    사후 복원할 수 있게 한다 (§3.1 개선안 4/6 의 전제).
    """
    investor_row = investor_row if isinstance(investor_row, dict) else {}
    high_info = high_info if isinstance(high_info, dict) else {}
    return {
        "schema_version": LEADING_FEATURE_SNAPSHOT_SCHEMA_VERSION,
        "kind": "leading",
        "snapshot_at": scanned_at,
        "raw": {
            "price": candidate.get("price"),
            "change_pct": candidate.get("change_pct"),
            "trading_value": candidate.get("tr_amt"),
            "volume": candidate.get("volume"),
            "volume_ratio": vol_ratio,
            "volume_ratio_source": volume_source_name,
            "sector": candidate.get("sector") or "",
            "sector_rising_count": sector_count,
            "investor_foreign_net": foreign,
            "investor_inst_net": inst,
            "investor_as_of_date": investor_row.get("stck_bsop_date"),
            "high_52w": high_info.get("high_52w"),
            "high_52w_date": high_info.get("high_date"),
            "high_52w_distance_pct": high_info.get("distance_pct"),
            "market_cap_eok": market_cap_eok,
        },
        "time_context": {
            "weight": time_weight,
            "scanned_at": scanned_at,
        },
    }


def _grade(total):
    if total >= 80: return "S"
    if total >= 60: return "A"
    if total >= 40: return "B"
    return "C"


# ─── KRX 휴장일 (Korean Stock Exchange Trading Calendar) ───
# holidays 패키지 = 한국 공식 공휴일만 (근로자의 날 미포함)
# → KRX 고유 휴장일 (근로자의 날 / 연말 / 임시휴장) 합집합
_KRX_RECURRING_CLOSURES = {
    "05-01",  # 근로자의 날 (매년)
    "12-31",  # 연말 휴장 (매년)
}
# 특정 연도 임시휴장 (선거일 등) — 매년 갱신
_KRX_TEMP_CLOSURES = {
    "2024-04-10",  # 제22대 총선
    # "2026-XX-XX": 8회 지방선거 (확정 시 추가)
}
# 한국 공식 공휴일 캐시 (연도별)
_kr_holidays_cache: dict = {}
_holidays_lock = Lock()


def _kr_official_holidays(year: int):
    with _holidays_lock:
        if year not in _kr_holidays_cache:
            try:
                import holidays as _holidays_lib
                _kr_holidays_cache[year] = _holidays_lib.KR(years=[year])
            except Exception as e:
                logger.warning(f"[is_market_open] holidays.KR({year}) failed: {e}")
                _kr_holidays_cache[year] = {}  # fail-open: 공식 공휴일 검사 스킵
        return _kr_holidays_cache[year]


def _is_kr_trading_day(d) -> bool:
    """KRX 영업일 여부. 공식공휴일 ∪ KRX 고유휴장(근로자의날/연말/임시) 모두 체크."""
    # 1) 한국 공식 공휴일 (설/추석/대체공휴일 등)
    key_date = d.date() if hasattr(d, 'date') else d
    if key_date in _kr_official_holidays(d.year):
        return False
    # 2) KRX 매년 반복 휴장 (근로자의 날, 연말)
    if d.strftime("%m-%d") in _KRX_RECURRING_CLOSURES:
        return False
    # 3) KRX 특정 연도 임시휴장
    if d.strftime("%Y-%m-%d") in _KRX_TEMP_CLOSURES:
        return False
    return True


def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if not _is_kr_trading_day(now):
        return False  # KRX 휴장 (근로자의 날, 설/추석, 임시휴장 등)
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
_price_details_cache = {}  # 마지막 스크리닝의 price_details (enricher용)
_result_lock = Lock()
_price_details_lock = Lock()
_CACHE_TTL = 3


def get_live_file_ttl_seconds():
    return max(5, _safe_int(os.environ.get("KIS_SCREENER_LIVE_TTL_SECONDS", "90"), 90))


def get_quote_mode():
    return "paper" if _paper else "real"


def result_age_seconds(result, now=None):
    if not isinstance(result, dict):
        return None
    raw_ts = result.get("timestamp")
    if not raw_ts:
        return None
    try:
        ts = str(raw_ts).strip().replace("Z", "+00:00")
        stamp = datetime.fromisoformat(ts)
        if stamp.tzinfo is not None:
            base_now = now or datetime.now(stamp.tzinfo)
            if base_now.tzinfo is None:
                base_now = base_now.replace(tzinfo=stamp.tzinfo)
            age = (base_now.astimezone(stamp.tzinfo) - stamp).total_seconds()
            return None if age < -5 else max(0.0, age)
        base_now = now or datetime.now()
        if base_now.tzinfo is not None:
            base_now = base_now.replace(tzinfo=None)
        age = (base_now - stamp).total_seconds()
        return None if age < -5 else max(0.0, age)
    except Exception:
        return None


def is_live_result_fresh(result, now=None, max_age_seconds=None):
    if not isinstance(result, dict) or result.get("market_status") != "open":
        return False
    age = result_age_seconds(result, now=now)
    if age is None:
        return False
    ttl = get_live_file_ttl_seconds() if max_age_seconds is None else max_age_seconds
    return age <= ttl


def _source_quality(source_counts):
    statuses = {
        name: {
            "status": "available" if count > 0 else "missing_or_empty",
            "rows": count,
        }
        for name, count in source_counts.items()
    }
    missing = [name for name, count in source_counts.items() if count <= 0]
    return statuses, missing


def _run_parallel(executor, calls, *, stage):
    """Run keyed independent fetches and return successful values by key."""
    tracker = getattr(_API_ATTEMPT_LOCAL, "tracker", None)
    future_keys = {
        executor.submit(
            _call_with_attempt_tracker, call, tracker
        ) if tracker is not None else executor.submit(call): key
        for key, call in calls.items()
    }
    results = {}
    for future in as_completed(future_keys):
        key = future_keys[future]
        try:
            results[key] = future.result()
        except Exception as e:
            logger.warning("KIS %s fetch failed key=%s error=%s", stage, key, e)
            results[key] = None
    return results


@contextmanager
def screener_poll_guard(timeout=0):
    """Cross-process single-poller guard shared by every screening caller."""
    os.makedirs(os.path.dirname(SCREENER_POLLER_LOCK), exist_ok=True)
    lock = FileLock(SCREENER_POLLER_LOCK)
    try:
        lock.acquire(timeout=timeout)
    except Timeout:
        yield False
        return
    try:
        yield True
    finally:
        lock.release()


def _poller_busy_result():
    """Return known-good data without starting a second KIS scan."""
    with _result_lock:
        cached = dict(_result_cache["data"]) if isinstance(_result_cache.get("data"), dict) else None
    latest = load_latest()

    def _usable(payload):
        if not isinstance(payload, dict) or payload.get("error") or not payload.get("timestamp"):
            return False
        quality = payload.get("data_quality")
        return not isinstance(quality, dict) or (
            quality.get("critical_complete") is not False
            and quality.get("score_reliable") is not False
            and quality.get("safe_to_replace_latest") is not False
        )

    def _age(payload):
        age = result_age_seconds(payload)
        return age if age is not None else float("inf")

    candidates = [payload for payload in (cached, latest) if _usable(payload)]
    if candidates:
        # Smaller age is newer. A missing/unparseable timestamp was filtered
        # above but still sorts last if parsing fails.
        selected = min(candidates, key=_age)
        result = dict(selected)
        result["poller_busy"] = True
        result["served_from"] = "poller_busy_cache"
        result["poller_fallback_source"] = (
            "memory_cache" if selected is cached else "latest_file"
        )
        return result
    return {
        "error": "screener_poller_busy",
        "poller_busy": True,
        "served_from": "poller_busy_no_cache",
        "results": [],
        "candidate_pool": [],
        "timestamp": datetime.now().isoformat(),
        "market_status": get_market_status(),
        "by_grade": {},
        "data_quality": {
            "status": "unavailable", "partial": True, "critical_complete": False,
            "score_reliable": False, "missing_sources": ["screener_poller"],
            "safe_to_replace_latest": False,
        },
    }


def _screener_poll_state_path():
    return f"{SCREENER_POLLER_LOCK}.state.json"


def _empty_screener_poll_state():
    return {"version": _SCREENER_POLL_STATE_VERSION, "accounts": {}}


def _read_screener_poll_state():
    path = _screener_poll_state_path()
    if not os.path.exists(path):
        return _empty_screener_poll_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if (
            isinstance(state, dict)
            and state.get("version") == _SCREENER_POLL_STATE_VERSION
            and isinstance(state.get("accounts"), dict)
        ):
            return state
    except (IOError, OSError, json.JSONDecodeError, TypeError) as e:
        logger.warning("KIS screener poll state load failed: %s", e)
    return _empty_screener_poll_state()


def _configured_seconds(name, default, *, minimum=0.0):
    raw = os.environ.get(name, str(default))
    try:
        value = float(raw)
        if math.isfinite(value) and value >= minimum:
            return value
    except ValueError:
        pass
    logger.warning("invalid %s=%r", name, raw)
    return float(default)


def _minimum_resolved_candidate_coverage():
    # IPOs have no previous-day volume and can also lack same-day investor
    # history. Keep the scan live when that uncertainty is a small tail; those
    # rows are carried as detection_unknown and cannot emit transition events.
    raw = os.environ.get("KIS_SCREENER_MIN_RESOLVED_COVERAGE", "0.90")
    try:
        value = float(raw)
        if math.isfinite(value) and 0.0 <= value <= 1.0:
            return value
    except ValueError:
        pass
    logger.warning("invalid KIS_SCREENER_MIN_RESOLVED_COVERAGE=%r", raw)
    return 0.90


def _resolved_candidate_coverage(total_candidates, unresolved_candidates):
    total = max(0, int(total_candidates))
    if total == 0:
        return 1.0
    unresolved = min(total, max(0, int(unresolved_candidates)))
    return (total - unresolved) / total


def _poller_cooldown_seconds(result):
    normal = _configured_seconds("KIS_SCREENER_MIN_SCAN_GAP_SECONDS", 5.0)
    quality = result.get("data_quality") if isinstance(result, dict) else None
    safe = (
        isinstance(result, dict)
        and not result.get("error")
        and (
            not isinstance(quality, dict)
            or quality.get("safe_to_replace_latest") is not False
        )
    )
    metrics = result.get("api_call_metrics") if isinstance(result, dict) else None
    rate_limited = (
        isinstance(metrics, dict)
        and _safe_int(metrics.get("rate_limit_responses"), 0) > 0
    )
    if rate_limited:
        return max(
            normal,
            _configured_seconds("KIS_SCREENER_RATE_LIMIT_COOLDOWN_SECONDS", 30.0),
        ), "rate_limited"
    if not safe:
        return max(
            normal,
            _configured_seconds("KIS_SCREENER_FAILURE_COOLDOWN_SECONDS", 30.0),
        ), "unsafe_result"
    return normal, "completed"


def _poller_cooldown_remaining(*, now=None):
    now = time.time() if now is None else float(now)
    state = _read_screener_poll_state()
    account = state.get("accounts", {}).get(_token_namespace())
    if not isinstance(account, dict):
        return 0.0, None
    retry_at = _safe_float(account.get("retry_not_before"), 0.0)
    return max(0.0, retry_at - now), account.get("reason")


def _save_screener_poll_outcome(result, *, completed_at=None):
    """Persist completion-to-next-start cadence while the poller lock is held."""
    completed_at = time.time() if completed_at is None else float(completed_at)
    cooldown, reason = _poller_cooldown_seconds(result)
    state = _read_screener_poll_state()
    state.setdefault("accounts", {})[_token_namespace()] = {
        "completed_at": completed_at,
        "retry_not_before": completed_at + cooldown,
        "reason": reason,
    }
    write_json_atomic(_screener_poll_state_path(), state, indent=0)


def _poller_cooldown_result(remaining, reason):
    result = _poller_busy_result()
    result["poller_busy"] = True
    result["poller_backoff"] = True
    result["poller_backoff_reason"] = reason or "shared_scan_gap"
    result["retry_after_seconds"] = round(max(0.0, remaining), 3)
    if result.get("served_from") == "poller_busy_cache":
        result["served_from"] = "poller_backoff_cache"
    elif result.get("served_from") == "poller_busy_no_cache":
        result["served_from"] = "poller_backoff_no_cache"
    return result


def run_screening(force=False, *, poll_lock_timeout=0):
    """Run one scan under the shared lock and completion-based cadence."""
    with screener_poll_guard(timeout=poll_lock_timeout) as acquired:
        if not acquired:
            return _poller_busy_result()
        remaining, reason = _poller_cooldown_remaining()
        if remaining > 0:
            return _poller_cooldown_result(remaining, reason)
        result = _run_screening_unlocked(force=force)
        try:
            _save_screener_poll_outcome(result)
        except (IOError, OSError, TypeError, ValueError) as e:
            # A state-file problem must not discard an otherwise valid scan.
            logger.warning("KIS screener poll outcome save failed: %s", e)
        return result


def _run_screening_unlocked(force=False):
    with _track_api_attempts() as attempt_tracker:
        return _run_screening_tracked(force=force, attempt_tracker=attempt_tracker)


def _run_screening_tracked(force=False, *, attempt_tracker):
    now = time.time()
    if not force:
        with _result_lock:
            if _result_cache["data"] and (now - _result_cache["ts"]) < _CACHE_TTL:
                return _result_cache["data"]

    t_start = time.time()
    token = get_token()
    if not token:
        return {"error": "토큰 발급 실패", "results": [], "timestamp": datetime.now().isoformat(),
                "market_status": get_market_status(), "by_grade": {}, "total_candidates": 0,
                "time_weight": 1.0, "api_calls": 0,
                "elapsed_ms": round((time.time() - t_start) * 1000),
                "api_call_metrics": _attempt_metrics(attempt_tracker, 0),
                "data_quality": {
                    "status": "unavailable",
                    "partial": True,
                    "critical_complete": False,
                    "score_reliable": False,
                    "missing_sources": ["kis_token"],
                    "source_status": {},
                    "safe_to_replace_latest": False,
                }}

    ranking_calls = {
        "volume_by_amount": lambda: fetch_volume_rank(token, "3"),
        "fluctuation": lambda: fetch_fluctuation_rank(token),
        "volume_by_surge": lambda: fetch_volume_rank(token, "1"),
    }
    with ThreadPoolExecutor(max_workers=min(3, _scanner_max_workers())) as executor:
        ranking = _run_parallel(executor, ranking_calls, stage="ranking")
    volume_by_amt = ranking.get("volume_by_amount") or []
    fluct_data = ranking.get("fluctuation") or []
    volume_by_surge = ranking.get("volume_by_surge") or []
    source_counts = {
        "volume_by_amount": len(volume_by_amt or []),
        "fluctuation": len(fluct_data or []),
        "volume_by_surge": len(volume_by_surge or []),
    }
    source_status, missing_sources = _source_quality(source_counts)
    if not any(source_counts.values()):
        return {
            "error": "kis_upstream_empty",
            "error_detail": "KIS ranking APIs returned no rows; stale latest was not overwritten.",
            "timestamp": datetime.now().isoformat(),
            "market_status": get_market_status(),
            "quote_mode": get_quote_mode(),
            "source_counts": source_counts,
            "data_quality": {
                "status": "unavailable",
                "partial": True,
                "critical_complete": False,
                "score_reliable": False,
                "source_status": source_status,
                "missing_sources": missing_sources,
                "safe_to_replace_latest": False,
            },
            "results": [],
            "by_grade": {},
            "total_candidates": 0,
            "time_weight": 1.0,
            "api_calls": 3,
            "api_call_metrics": _attempt_metrics(attempt_tracker, 3),
            "elapsed_ms": round((time.time() - t_start) * 1000),
        }

    liquidity_floor = 20_0000_0000
    amount_map = {
        item.get("mksc_shrn_iscd", ""): item
        for item in volume_by_amt
        if item.get("mksc_shrn_iscd")
    }
    surge_map = {
        item.get("mksc_shrn_iscd", ""): item
        for item in volume_by_surge
        if item.get("mksc_shrn_iscd")
    }

    candidates = {}
    for item in volume_by_amt:
        code = item.get("mksc_shrn_iscd", "")
        name = item.get("hts_kor_isnm", "")
        if not code or _is_etf(name):
            continue
        tr_amt = _safe_int(item.get("acml_tr_pbmn"))
        if tr_amt < liquidity_floor:
            continue
        prdy_vol = _positive_int_or_none(item.get("prdy_vol"))
        prdy_source = "volume_amount_rank.prdy_vol"
        if prdy_vol is None:
            prdy_vol = _positive_int_or_none(
                (surge_map.get(code) or {}).get("prdy_vol")
            )
            prdy_source = "volume_surge_rank.prdy_vol"
        candidates[code] = {
            "code": code, "name": name,
            "price": _safe_int(item.get("stck_prpr")),
            "change_pct": _safe_float(item.get("prdy_ctrt")),
            "tr_amt": tr_amt,
            "volume": _safe_int(item.get("acml_vol")),
            "prdy_vol": prdy_vol,
            "prdy_vol_source": prdy_source if prdy_vol is not None else None,
            "candidate_source": "volume_amount_rank",
            "sector": item.get("bstp_cls_code", ""),
            "raw": item,
        }

    # The surge ranking is a first-class universe source, not merely a lookup
    # table for candidates discovered elsewhere. Apply the same authoritative
    # turnover floor used by the amount ranking and retain its own provenance.
    for item in volume_by_surge:
        code = item.get("mksc_shrn_iscd", "")
        amount_row = amount_map.get(code) or {}
        name = item.get("hts_kor_isnm") or amount_row.get("hts_kor_isnm", "")
        if not code or code in candidates or _is_etf(name):
            continue
        tr_amt = _safe_int(item.get("acml_tr_pbmn") or amount_row.get("acml_tr_pbmn"))
        if tr_amt < liquidity_floor:
            continue
        prdy_vol = _positive_int_or_none(item.get("prdy_vol"))
        prdy_source = "volume_surge_rank.prdy_vol"
        if prdy_vol is None:
            prdy_vol = _positive_int_or_none(amount_row.get("prdy_vol"))
            prdy_source = "volume_amount_rank.prdy_vol"
        candidates[code] = {
            "code": code,
            "name": name,
            "price": _safe_int(item.get("stck_prpr") or amount_row.get("stck_prpr")),
            "change_pct": _safe_float(item.get("prdy_ctrt") or amount_row.get("prdy_ctrt")),
            "tr_amt": tr_amt,
            "volume": _safe_int(item.get("acml_vol") or amount_row.get("acml_vol")),
            "prdy_vol": prdy_vol,
            "prdy_vol_source": prdy_source if prdy_vol is not None else None,
            "candidate_source": "volume_surge_rank",
            "sector": item.get("bstp_cls_code") or amount_row.get("bstp_cls_code", ""),
            "raw": item,
        }

    # The KIS fluctuation ranking response does not include acml_tr_pbmn.
    # Hydrate its leading rows with the live quote/detail endpoint before
    # applying the liquidity floor; treating the missing field as zero drops
    # every rising-stock candidate.
    fluct_price_details = {}
    detail_requested_codes = set()
    detail_missing_codes = set()
    fluct_work = {}
    liquidity_upper_bound_skips = 0
    liquidity_rank_reuses = 0
    for item in fluct_data:
        code = item.get("mksc_shrn_iscd", item.get("stck_shrn_iscd", ""))
        name = item.get("hts_kor_isnm", "")
        if not code or code in candidates or _is_etf(name):
            continue
        pct = _safe_float(item.get("prdy_ctrt"))
        if pct < 1:
            continue

        # Prefer exact trading value already returned by any ranking feed.
        # If absent, a day-high * accumulated-volume upper bound can safely
        # reject rows that cannot possibly clear the liquidity floor.
        auxiliary_rows = (amount_map.get(code) or {}, surge_map.get(code) or {})
        tr_amt = _safe_int(item.get("acml_tr_pbmn"))
        if not tr_amt:
            tr_amt = next(
                (
                    value
                    for value in (
                        _safe_int(row.get("acml_tr_pbmn"))
                        for row in auxiliary_rows
                    )
                    if value > 0
                ),
                0,
            )
            if tr_amt:
                liquidity_rank_reuses += 1
        if tr_amt and tr_amt < liquidity_floor:
            continue
        if not tr_amt:
            high = _safe_int(item.get("stck_hgpr"))
            volume = _safe_int(item.get("acml_vol"))
            if high > 0 and volume > 0 and high * volume < liquidity_floor:
                liquidity_upper_bound_skips += 1
                continue
        fluct_work[code] = {"item": item, "tr_amt": tr_amt}

    fluct_detail_codes = [
        code for code, work in fluct_work.items() if not work["tr_amt"]
    ]
    detail_requested_codes.update(fluct_detail_codes)
    if fluct_detail_codes:
        calls = {
            code: (lambda code=code: fetch_price_detail(token, code))
            for code in fluct_detail_codes
        }
        with ThreadPoolExecutor(max_workers=_scanner_max_workers()) as executor:
            fetched = _run_parallel(executor, calls, stage="fluctuation_detail")
        for code in fluct_detail_codes:
            detail = fetched.get(code) or {}
            if detail:
                fluct_price_details[code] = detail
            else:
                detail_missing_codes.add(code)

    for code, work in fluct_work.items():
        item = work["item"]
        detail = fluct_price_details.get(code, {})
        tr_amt = work["tr_amt"] or _safe_int(detail.get("acml_tr_pbmn"))
        if tr_amt < liquidity_floor:
            continue
        name = item.get("hts_kor_isnm", "")
        pct = _safe_float(item.get("prdy_ctrt"))
        source_rows = (
            ("fluctuation_rank.prdy_vol", item),
            ("volume_amount_rank.prdy_vol", amount_map.get(code) or {}),
            ("volume_surge_rank.prdy_vol", surge_map.get(code) or {}),
            ("price_detail.prdy_vol", detail),
        )
        prdy_vol = None
        prdy_source = None
        for source, row in source_rows:
            prdy_vol = _positive_int_or_none(row.get("prdy_vol"))
            if prdy_vol is not None:
                prdy_source = source
                break
        candidates[code] = {
            "code": code, "name": name,
            "price": _safe_int(item.get("stck_prpr") or detail.get("stck_prpr")),
            "change_pct": pct, "tr_amt": tr_amt,
            "volume": _safe_int(item.get("acml_vol") or detail.get("acml_vol")),
            "prdy_vol": prdy_vol,
            "prdy_vol_source": prdy_source,
            "candidate_source": "fluctuation_rank",
            "sector": item.get("bstp_cls_code", ""),
            "raw": item,
        }

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
    price_details = dict(fluct_price_details)
    market_caps = {}  # {code: 시가총액(억)}
    investor_requested_codes = {c["code"] for c in pre_scored}
    investor_missing_codes = set()
    candidate_detail_codes = {
        c["code"] for c in pre_scored if not price_details.get(c["code"])
    }
    detail_requested_codes.update(candidate_detail_codes)

    def _fetch_enrichment_batch(investor_codes, detail_codes, stage):
        calls = {
            ("investor", code): (lambda code=code: fetch_investor(token, code))
            for code in investor_codes
        }
        calls.update({
            ("detail", code): (lambda code=code: fetch_price_detail(token, code))
            for code in detail_codes
        })
        if not calls:
            return {}
        with ThreadPoolExecutor(max_workers=_scanner_max_workers()) as executor:
            return _run_parallel(executor, calls, stage=stage)

    def _merge_enrichment_batch(codes, detail_codes, batch):
        for code in codes:
            inv = batch.get(("investor", code)) or []
            investor_results[code] = inv
            if _has_investor_inputs(inv):
                investor_missing_codes.discard(code)
            else:
                investor_missing_codes.add(code)

            pd = price_details.get(code) or batch.get(("detail", code)) or {}
            price_details[code] = pd
            if not pd:
                if code in detail_codes:
                    detail_missing_codes.add(code)
            else:
                detail_missing_codes.discard(code)
                cap = _safe_int(pd.get("hts_avls"))
                if cap > 0:
                    market_caps[code] = cap
            if not inv and not pd:
                # Keep one compact diagnostic without leaking response bodies.
                logger.warning("KIS candidate enrichment unavailable code=%s", code)

    initial_enrichment = _fetch_enrichment_batch(
        investor_requested_codes, candidate_detail_codes, "enrichment"
    )
    _merge_enrichment_batch(
        investor_requested_codes, candidate_detail_codes, initial_enrichment
    )

    tw = _time_weight()
    scan_snapshot_at = datetime.now().isoformat(timespec="seconds")

    # The fixed top-15 preselection limits the first batch, but it is not a
    # correctness boundary. A row whose currently known score is C can still
    # reach B after the unobserved investor (+25) and 52-week-high (+15) inputs
    # arrive. Use that conservative upper bound for the second batch so no
    # potential B candidate is silently missed, while rows that provably cannot
    # reach B avoid unnecessary calls.
    secondary_enrichment_codes = set()
    for c in candidates.values():
        code = c["code"]
        if code in investor_requested_codes:
            continue
        pd = price_details.get(code, {})
        volume_source, _ = _resolve_volume_source(c, surge_map.get(code), pd)
        s4, _ = _score_volume_surge(volume_source)
        s5, _ = _score_sector(sector_rising, c["sector"])
        s6, _ = _score_new_high(pd, c["price"])
        known_raw = (
            _score_trading_value(c["tr_amt"])
            + _score_change_pct(c["change_pct"])
            + s4 + s5 + s6
        )
        unobserved_max = 25  # investor has not been requested for this row.
        if _positive_int_or_none(pd.get("w52_hgpr")) is None:
            unobserved_max += 15
        if not _has_volume_baseline(volume_source):
            unobserved_max += 10
        potential_total = min(100, round((known_raw + unobserved_max) * tw))
        if _grade(potential_total) != "C":
            secondary_enrichment_codes.add(code)

    secondary_detail_codes = {
        code for code in secondary_enrichment_codes if not price_details.get(code)
    }
    if secondary_enrichment_codes:
        investor_requested_codes.update(secondary_enrichment_codes)
        candidate_detail_codes.update(secondary_detail_codes)
        detail_requested_codes.update(secondary_detail_codes)
        secondary_enrichment = _fetch_enrichment_batch(
            secondary_enrichment_codes,
            secondary_detail_codes,
            "secondary_enrichment",
        )
        _merge_enrichment_batch(
            secondary_enrichment_codes,
            secondary_detail_codes,
            secondary_enrichment,
        )

    results = []
    candidate_pool = []
    scored_candidates = 0
    filtered_grade_c = 0
    filtered_incomplete_score = 0
    volume_baseline_evaluated_codes = set()
    volume_baseline_missing_codes = set()
    volume_baseline_sources = defaultdict(int)
    incomplete_score_codes = set()
    unresolved_potential_codes = set()
    for c in candidates.values():
        s1 = _score_trading_value(c["tr_amt"])
        s2 = _score_change_pct(c["change_pct"])
        investor_data = investor_results.get(c["code"], [])
        investor_row = _select_investor_row(investor_data) or {}
        price_detail = price_details.get(c["code"], {})
        volume_source, volume_source_name = _resolve_volume_source(
            c, surge_map.get(c["code"]), price_detail
        )
        s3, foreign, inst = _score_investor(investor_data)
        s4, vol_ratio = _score_volume_surge(volume_source)
        s5, sector_count = _score_sector(sector_rising, c["sector"])
        s6, high_info = _score_new_high(price_detail, c["price"])

        volume_baseline_evaluated_codes.add(c["code"])
        missing_score_inputs = []
        missing_score_max_points = 0
        if not _has_investor_inputs(investor_data):
            missing_score_inputs.append("investor")
            missing_score_max_points += 25
        volume_baseline_available = _has_volume_baseline(volume_source)
        if not volume_baseline_available:
            missing_score_inputs.append("prdy_vol")
            missing_score_max_points += 10
            volume_baseline_missing_codes.add(c["code"])
        else:
            volume_baseline_sources[volume_source_name] += 1
        if _positive_int_or_none(price_detail.get("w52_hgpr")) is None:
            missing_score_inputs.append("price_detail_52w_high")
            missing_score_max_points += 15
        if missing_score_inputs:
            incomplete_score_codes.add(c["code"])

        raw_total = s1 + s2 + s3 + s4 + s5 + s6
        total = min(100, round(raw_total * tw))
        grade = _grade(total)
        score_upper_bound = min(
            100, round((raw_total + missing_score_max_points) * tw)
        )
        can_reach_min_grade = _grade(score_upper_bound) != "C"
        if missing_score_inputs and can_reach_min_grade:
            unresolved_potential_codes.add(c["code"])
        scored_candidates += 1

        result_item = {
            "rank": 0, "grade": grade, "code": c["code"], "name": c["name"],
            "price": c["price"], "change_pct": c["change_pct"],
            "trading_value": c["tr_amt"],
            "trading_value_eok": round(c["tr_amt"] / 1_0000_0000),
            "volume": c["volume"],
            "score": {"total": total, "trading_value": s1, "momentum": s2,
                      "smart_money": s3, "volume_surge": s4, "sector": s5,
                      "new_high": s6},
            "investor": {
                "foreign_net": foreign,
                "inst_net": inst,
                "as_of_date": investor_row.get("stck_bsop_date"),
                "source": "kis_latest_completed_day",
            },
            "volume_ratio": vol_ratio,
            "volume_ratio_source": volume_source_name,
            "sector_rising_count": sector_count,
            "score_complete": not missing_score_inputs,
            "incomplete_reasons": missing_score_inputs,
            "data_quality": {
                "status": "partial" if missing_score_inputs else "complete",
                "score_complete": not missing_score_inputs,
                "score_interpretation": "lower_bound" if missing_score_inputs else "complete",
                "missing_score_inputs": missing_score_inputs,
                "unobserved_score_max_points": missing_score_max_points,
                "score_upper_bound": score_upper_bound,
                "inputs": {
                    "investor": (
                        "available"
                        if _has_investor_inputs(investor_data)
                        else "missing"
                        if c["code"] in investor_requested_codes
                        else "not_requested"
                    ),
                    "price_detail": (
                        "available"
                        if price_detail
                        else "missing"
                        if c["code"] in detail_requested_codes
                        else "not_requested"
                    ),
                    "prdy_vol": "available" if volume_baseline_available else "missing",
                    "volume_ratio_source": volume_source_name,
                },
            },
        }
        if high_info:
            result_item["high_52w"] = high_info
        # 시가총액 추가
        if c["code"] in market_caps:
            result_item["market_cap_eok"] = market_caps[c["code"]]
        # v3.6 additive — 캘리브레이션용 피처 스냅샷 (점수 산식 불변)
        try:
            result_item["feature_snapshot"] = _build_leading_feature_snapshot(
                c,
                investor_row=investor_row,
                foreign=foreign,
                inst=inst,
                vol_ratio=vol_ratio,
                volume_source_name=volume_source_name,
                high_info=high_info,
                sector_count=sector_count,
                market_cap_eok=market_caps.get(c["code"]),
                time_weight=tw,
                scanned_at=scan_snapshot_at,
            )
        except Exception as snap_exc:  # noqa: BLE001 — 스냅샷 실패가 스캔을 막지 않는다
            logger.debug("leading feature snapshot skipped code=%s: %s", c.get("code"), snap_exc)
        score_complete = not missing_score_inputs
        eligible = grade != "C" and score_complete
        rejection_reason = (
            "score_inputs_incomplete"
            if not score_complete and can_reach_min_grade
            else "below_grade_threshold"
            if grade == "C"
            else "score_inputs_incomplete"
            if not score_complete
            else None
        )
        candidate_pool.append({
            **result_item,
            "eligible": eligible,
            "raw_score": raw_total,
            "rejection_reason": rejection_reason,
        })
        if not score_complete and can_reach_min_grade:
            filtered_incomplete_score += 1
            continue
        if grade == "C":
            filtered_grade_c += 1
            continue
        if not score_complete:
            filtered_incomplete_score += 1
            continue
        results.append(result_item)

    results.sort(key=lambda x: x["score"]["total"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    by_grade = {}
    for r in results:
        by_grade[r["grade"]] = by_grade.get(r["grade"], 0) + 1

    # Layer 2 보강 데이터 머지 → 점수에 직접 반영
    try:
        from app.services.leading_enricher import get_cached_enrichment
        enrichments = get_cached_enrichment()
        for r in results:
            enrich = enrichments.get(r["code"])
            if enrich:
                r["enrichment"] = enrich
                # ─── AI 뉴스 점수 (0-10) ───
                ai_raw = enrich.get("ai_score", 0)
                ai_pts = {0: 0, 1: 3, 2: 7, 3: 10}.get(ai_raw, 0)
                # ─── 연속 주도주 점수 (0-8) ───
                consec = enrich.get("consecutive_days", 0)
                if consec >= 3:
                    consec_pts = 8
                elif consec >= 2:
                    consec_pts = 5
                elif consec >= 1:
                    consec_pts = 2
                else:
                    consec_pts = 0
                # score 객체에 추가
                r["score"]["ai_news"] = ai_pts
                r["score"]["consecutive"] = consec_pts
                # 보강 총점 = 기존 total + AI + 연속
                r["score"]["total_enriched"] = min(
                    120, r["score"]["total"] + ai_pts + consec_pts
                )
            else:
                # 보강 미완료 시
                r["score"]["ai_news"] = None
                r["score"]["consecutive"] = None
                r["score"]["total_enriched"] = None
    except Exception:
        pass

    # 보강 점수가 있으면 재정렬 + 등급 재평가
    try:
        for r in results:
            enriched_total = r["score"].get("total_enriched")
            if enriched_total is not None:
                r["grade"] = _grade(enriched_total)
        results.sort(key=lambda x: (x["score"].get("total_enriched") or x["score"]["total"]), reverse=True)
        for i, r in enumerate(results):
            r["rank"] = i + 1
        by_grade = {}
        for r in results:
            by_grade[r["grade"]] = by_grade.get(r["grade"], 0) + 1
    except Exception:
        pass

    critical_complete = not missing_sources
    # A candidate is unresolved only when its exact missing-input upper bound
    # can still reach B. This avoids both unsafe false negatives and needless
    # preservation of stale leaders for provably-C incomplete rows.
    partial_failure_reasons = []
    if missing_sources:
        partial_failure_reasons.append("ranking_sources_missing")
    if detail_missing_codes:
        partial_failure_reasons.append("price_detail_missing")
    if investor_missing_codes:
        partial_failure_reasons.append("investor_missing")
    if volume_baseline_missing_codes:
        partial_failure_reasons.append("prdy_vol_missing")
    if incomplete_score_codes and not partial_failure_reasons:
        partial_failure_reasons.append("score_inputs_incomplete")
    quality_partial = bool(partial_failure_reasons)
    displayed_results_complete = all(
        row.get("score_complete") is True for row in results
    )
    resolved_candidate_coverage = _resolved_candidate_coverage(
        len(candidates), len(unresolved_potential_codes)
    )
    minimum_resolved_coverage = _minimum_resolved_candidate_coverage()
    score_reliable = (
        displayed_results_complete
        and resolved_candidate_coverage >= minimum_resolved_coverage
    )
    data_quality = {
        "status": "partial" if quality_partial else "complete",
        "partial": quality_partial,
        # The three ranking feeds define the candidate universe. A missing
        # ranking feed makes the scan unsafe to replace a known-good latest.
        "critical_complete": critical_complete,
        # Complete displayed rows remain trustworthy even when a small number
        # of candidates are guarded as detection_unknown. Claw carries those
        # rows forward to prevent false NEW/DROP events. A coverage floor keeps
        # broad enrichment outages fail-closed.
        "score_reliable": score_reliable,
        "universe_complete": not unresolved_potential_codes,
        "resolved_candidate_coverage": round(resolved_candidate_coverage, 4),
        "minimum_resolved_candidate_coverage": minimum_resolved_coverage,
        "source_status": source_status,
        "missing_sources": missing_sources,
        "partial_failure_reasons": partial_failure_reasons,
        "detail": {
            "requested": len(detail_requested_codes),
            "available": len(detail_requested_codes - detail_missing_codes),
            "missing_codes": sorted(detail_missing_codes),
        },
        "investor": {
            "requested": len(investor_requested_codes),
            "available": len(investor_requested_codes - investor_missing_codes),
            "missing_codes": sorted(investor_missing_codes),
        },
        "volume_baseline": {
            "evaluated": len(volume_baseline_evaluated_codes),
            "available": len(volume_baseline_evaluated_codes - volume_baseline_missing_codes),
            "missing_codes": sorted(volume_baseline_missing_codes),
            "sources": dict(sorted(volume_baseline_sources.items())),
        },
        "incomplete_score_codes": sorted(incomplete_score_codes),
        "unresolved_potential_codes": sorted(unresolved_potential_codes),
        "displayed_results_complete": displayed_results_complete,
        "safe_to_replace_latest": (
            critical_complete and score_reliable
        ),
    }

    api_call_breakdown = {
        "ranking": len(ranking_calls),
        "fluctuation_liquidity_detail": len(fluct_detail_codes),
        "investor": len(investor_requested_codes),
        "candidate_detail": len(candidate_detail_codes),
    }
    logical_api_calls = sum(api_call_breakdown.values())
    output = {
        "timestamp": datetime.now().isoformat(),
        "market_status": get_market_status(),
        "quote_mode": get_quote_mode(),
        "time_weight": tw,
        "total_candidates": len(candidates),
        "filter_summary": {
            "scored_candidates": scored_candidates,
            "filtered_grade_c": filtered_grade_c,
            "filtered_incomplete_score": filtered_incomplete_score,
            "displayed_results_complete": displayed_results_complete,
            "min_grade": "B",
        },
        "empty_reason": (
            "score_inputs_incomplete"
            if unresolved_potential_codes and not results
            else "below_grade_threshold"
            if len(candidates) > 0 and scored_candidates > 0 and not results
            else None
        ),
        "source_counts": source_counts,
        "data_quality": data_quality,
        "candidate_pool": sorted(
            candidate_pool,
            key=lambda x: (x["score"]["total"], x["change_pct"], x["trading_value"]),
            reverse=True,
        ),
        "results": results,
        "by_grade": by_grade,
        # api_calls remains the backwards-compatible logical operation count.
        # Physical GET retries and token POSTs are reported separately so the
        # number is useful for both performance and quota diagnostics.
        "api_calls": logical_api_calls,
        "api_call_breakdown": api_call_breakdown,
        "api_call_metrics": _attempt_metrics(attempt_tracker, logical_api_calls),
        "scan_profile": {
            "pooled_http": True,
            "max_workers": _scanner_max_workers(),
            "liquidity_rank_reuses": liquidity_rank_reuses,
            "liquidity_upper_bound_skips": liquidity_upper_bound_skips,
            "initial_enrichment_candidates": len(pre_scored),
            "secondary_enrichment_candidates": len(secondary_enrichment_codes),
            "secondary_detail_calls": len(secondary_detail_codes),
        },
        "elapsed_ms": round((time.time() - t_start) * 1000),
    }

    # Keep the canonical memory fallback aligned with the atomic latest-file
    # safeguard. An unresolved potential B candidate must not displace a
    # known-good result merely because memory is newer than disk.
    if data_quality["safe_to_replace_latest"]:
        with _result_lock:
            _result_cache["data"] = output
            _result_cache["ts"] = time.time()

    # price_details 캐시 (enricher에서 시가총액 참조용)
    with _price_details_lock:
        _price_details_cache.clear()
        _price_details_cache.update(price_details)

    # 결과 저장
    _save_result(output)

    return output


def _save_result(result):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        has_results = bool(result.get("results"))
        quality = result.get("data_quality") if isinstance(result, dict) else None
        safe_to_replace = (
            not result.get("error")
            and (
                not isinstance(quality, dict)
                or quality.get("safe_to_replace_latest", True)
            )
        )
        latest = os.path.join(DATA_DIR, "screener_leading_latest.json")
        date_str = datetime.now().strftime("%Y%m%d")
        archive = os.path.join(DATA_DIR, f"screener_leading_{date_str}.json")

        if has_results or safe_to_replace:
            # A valid complete scan is authoritative even when no stock clears
            # the grade threshold. Persisting that empty state prevents stale
            # leaders from surviving indefinitely. A partial critical universe
            # still cannot replace a known-good artifact.
            if safe_to_replace or not os.path.exists(latest):
                write_json_atomic(latest, result, indent=0)
            else:
                logger.warning(
                    "KIS partial ranking scan preserved latest; missing_sources=%s",
                    (quality or {}).get("missing_sources", []),
                )
            if safe_to_replace or not os.path.exists(archive):
                write_json_atomic(archive, result, indent=0)
        else:
            # Error/unsafe partial with no results: preserve known-good files,
            # but leave an inspectable artifact on a first-ever run.
            if not os.path.exists(latest):
                write_json_atomic(latest, result, indent=0)
            if not os.path.exists(archive):
                write_json_atomic(archive, result, indent=0)
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
