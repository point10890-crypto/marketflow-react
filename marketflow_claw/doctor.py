"""doctor — 배포 직후 '바로 돌 수 있는 상태인지' 점검. 비밀값은 출력하지 않는다."""
from __future__ import annotations

import os
import sqlite3
from typing import Any

from marketflow_claw import collectors, delivery, memory
from marketflow_claw.paths import CLAW_DIR, DAILY_PRICES, LEADERS_LATEST, MARKET_GATE_CACHE, ensure_dirs


def _check(name: str, ok: bool, detail: str = '', *, warn: bool = False) -> dict[str, Any]:
    return {'name': name, 'status': 'ok' if ok else ('warn' if warn else 'fail'), 'detail': detail}


def run(*, network: bool = True) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # 1) env keys (presence only)
    for key in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_CHANNEL_BOT_TOKEN', 'KIS_APP_KEY', 'KIS_APP_SECRET'):
        checks.append(_check(f'env:{key}', bool(os.environ.get(key)), 'set' if os.environ.get(key) else 'missing'))
    r = delivery.route()
    checks.append(_check('delivery:route', r['token_set'] and r['chat_set'], f"{r['mode']} via {r['token_key']}"))
    checks.append(_check('delivery:enabled', delivery._enabled(), os.environ.get('CLAW_DELIVERY_ENABLED', '0'), warn=True))

    # 2) files
    for label, path, warn in (('leaders_latest', LEADERS_LATEST, False), ('market_gate_cache', MARKET_GATE_CACHE, True),
                              ('daily_prices', DAILY_PRICES, True)):
        exists = os.path.isfile(path)
        age = collectors._file_age_seconds(path)
        checks.append(_check(f'file:{label}', exists, f"age {age/3600:.1f}h" if age is not None else 'missing', warn=warn))

    # 3) db writable
    try:
        ensure_dirs()
        with memory.connect() as con:
            st = memory.stats(con, '00000000')
        checks.append(_check('db:writable', True, os.path.join(CLAW_DIR, 'claw.db')))
    except (sqlite3.Error, OSError) as e:
        checks.append(_check('db:writable', False, f'{type(e).__name__}: {e}'))

    # 4) network probes
    if network:
        try:
            from app.services.kis_screener import get_token
            checks.append(_check('kis:token', bool(get_token()), 'token issued/cached'))
        except Exception as e:  # noqa: BLE001
            checks.append(_check('kis:token', False, f'{type(e).__name__}'))
        try:
            import requests
            tok = os.environ.get(r['token_key'], '')
            me = requests.get(f'https://api.telegram.org/bot{tok}/getMe', timeout=10).json() if tok else {}
            checks.append(_check('telegram:getMe', bool(me.get('ok')), '@' + str((me.get('result') or {}).get('username', '?'))))
        except Exception as e:  # noqa: BLE001
            checks.append(_check('telegram:getMe', False, f'{type(e).__name__}'))

    ok = all(c['status'] != 'fail' for c in checks)
    return {'ok': ok, 'checks': checks}
