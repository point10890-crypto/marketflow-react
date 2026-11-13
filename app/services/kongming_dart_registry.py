"""Bounded, issuer-exact OpenDART registry recovery for Kongming workers.

The shared legacy map is read-only. One successful corpus download covers all
missing symbols for a day; failures back off across processes and restarts.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from filelock import FileLock, Timeout

from app.utils.atomic_json import write_json_atomic


SOURCE = 'https://opendart.fss.or.kr/api/corpCode.xml'
ZIP_LIMIT = 10 * 1024 * 1024
XML_LIMIT = 64 * 1024 * 1024
REFRESH_INTERVAL = timedelta(days=1)
RETRY_INTERVAL = timedelta(minutes=15)
_GLOBAL_STATUS = {'010', '011', '012', '020', '800', '901'}
_ERROR_CODES = {'issuer_registry_invalid', 'issuer_registry_refresh_failed',
                'request_failed', 'http_error', 'response_limit'} | {
                    'dart_status_' + status for status in _GLOBAL_STATUS}


class RegistryError(ValueError):
    def __init__(self, code, metadata=None):
        super().__init__(code)
        self.metadata = metadata or {}


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(value)
        return stamp if stamp.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _valid_entry(symbol, entry):
    if (not isinstance(symbol, str) or re.fullmatch(r'[0-9A-Z]{6}', symbol) is None
            or symbol == '000000' or not isinstance(entry, dict)):
        return False
    corp, name, modified = (entry.get(field) for field in ('corp_code', 'corp_name', 'modify_date'))
    if (not isinstance(corp, str) or re.fullmatch(r'[0-9]{8}', corp) is None
            or not isinstance(name, str) or not name.strip() or len(name) > 500
            or not isinstance(modified, str) or re.fullmatch(r'[0-9]{8}', modified) is None):
        return False
    try:
        date(int(modified[:4]), int(modified[4:6]), int(modified[6:]))
    except ValueError:
        return False
    return True


def _parse(body):
    """Never extract files; reject oversized, ambiguous or entity-bearing XML."""
    try:
        if len(body) > ZIP_LIMIT:
            raise ValueError()
        if len(body) <= 8192 and body.lstrip().startswith((b'<?xml', b'<result')):
            text = body.decode('utf-8-sig')
            if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.IGNORECASE):
                raise ValueError()
            response = ET.fromstring(text)
            status = response.findtext('status')
            if response.tag == 'result' and status in _GLOBAL_STATUS:
                raise RegistryError('dart_status_' + status)
            raise ValueError()
        with ZipFile(BytesIO(body)) as archive:
            files = archive.infolist()
            if (len(files) != 1 or files[0].filename.upper() != 'CORPCODE.XML'
                    or not 0 < files[0].file_size <= XML_LIMIT):
                raise ValueError()
            raw = archive.read(files[0])
        text = raw.decode('utf-8-sig')
        if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.IGNORECASE):
            raise ValueError()
        root = ET.fromstring(text)
        if root.tag != 'result':
            raise ValueError()
        entries = {}
        for row in root:
            if row.tag != 'list':
                raise ValueError()
            symbol = (row.findtext('stock_code') or '').strip()
            if not symbol:  # Unlisted corporations have no stock mapping.
                continue
            entry = {field: (row.findtext(field) or '').strip()
                     for field in ('corp_code', 'corp_name', 'modify_date')}
            if not _valid_entry(symbol, entry) or (symbol in entries and entries[symbol] != entry):
                raise ValueError()
            entries[symbol] = entry
        if not entries:
            raise ValueError()
        return entries
    except RegistryError:
        raise
    except (BadZipFile, ET.ParseError, ValueError, RuntimeError, ZlibError):
        raise RegistryError('issuer_registry_invalid') from None


class DartIssuerRegistry:
    def __init__(self, project_root):
        self.path = Path(project_root) / 'data/kongming/dart_issuer_registry.json'
        self.legacy = Path(project_root) / 'data/dart_corp_codes.json'

    def _read(self, now):
        try:
            # The cached listed subset is small; do not parse an arbitrary file.
            if self.path.stat().st_size > 8 * 1024 * 1024:
                return {}
            state = json.loads(self.path.read_bytes())
            if not isinstance(state, dict) or state.get('source') != SOURCE or state.get('schema') != 1:
                return {}
            entries = state.get('entries', {})
            fetched = _stamp(state.get('fetched_at'))
            digest = state.get('sha256', '')
            if (not isinstance(entries, dict)
                    or (entries and (fetched is None or fetched > now or not isinstance(digest, str)
                                     or re.fullmatch(r'[0-9a-f]{64}', digest) is None))
                    or any(not _valid_entry(symbol, entry) for symbol, entry in entries.items())):
                return {}
            attempt = _stamp(state.get('last_attempt_at'))
            retry = _stamp(state.get('retry_at'))
            if (attempt is None or retry is None or attempt > now
                    or not attempt < retry <= attempt + REFRESH_INTERVAL):
                return {}
            return state
        except (OSError, ValueError):
            return {}

    def _metadata(self, state, now):
        fetched = _stamp(state.get('fetched_at'))
        return {'source': SOURCE, 'fetched_at': state.get('fetched_at'),
                'sha256': state.get('sha256'), 'retry_at': state.get('retry_at'),
                'stale': fetched is None or now - fetched >= REFRESH_INTERVAL}

    def _known(self, symbol, state, now):
        entry = state.get('entries', {}).get(symbol)
        if entry:
            return entry, dict(self._metadata(state, now), stock_code=symbol, **entry)
        try:
            raw = self.legacy.read_bytes()
            mapping = json.loads(raw)
            corp = mapping.get(symbol) if isinstance(mapping, dict) else None
            if isinstance(corp, str) and re.fullmatch(r'[0-9]{8}', corp):
                return {'corp_code': corp}, {
                    'source': 'data/dart_corp_codes.json', 'stock_code': symbol,
                    'corp_code': corp, 'fetched_at': None, 'sha256': sha256(raw).hexdigest(),
                    'cache_updated_at': datetime.fromtimestamp(self.legacy.stat().st_mtime, timezone.utc).isoformat(),
                    'stale': True,
                }
        except (OSError, ValueError):
            pass
        return None

    def resolve(self, symbol, now, fetch, ready):
        state = self._read(now)
        known = self._known(symbol, state, now)
        if known:
            return known
        retry = _stamp(state.get('retry_at'))
        if retry is not None and now < retry:
            code = state.get('last_error')
            raise RegistryError(code if code in _ERROR_CODES else 'issuer_mapping_unavailable', self._metadata(state, now))
        ready()  # Missing credentials or a spent run budget must not reserve a retry.
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(str(self.path) + '.lock', timeout=0):
                # Another process may have completed a refresh since our read.
                state = self._read(now)
                known = self._known(symbol, state, now)
                if known:
                    return known
                retry = _stamp(state.get('retry_at'))
                if retry is not None and now < retry:
                    code = state.get('last_error')
                    raise RegistryError(code if code in _ERROR_CODES else 'issuer_mapping_unavailable', self._metadata(state, now))
                ready()
                # Save the attempt before the HTTP call, so even a crashed worker
                # cannot cause every minute's successor to download the corpus.
                state = dict(state, schema=1, source=SOURCE, last_attempt_at=now.isoformat(),
                             retry_at=(now + RETRY_INTERVAL).isoformat(), last_error='issuer_registry_refresh_failed')
                write_json_atomic(str(self.path), state)
                try:
                    body = fetch('corpCode.xml', ZIP_LIMIT)
                    entries = _parse(body)
                except ValueError as exc:
                    code = str(exc) if str(exc) in _ERROR_CODES else 'issuer_registry_refresh_failed'
                    state['last_error'] = code
                    write_json_atomic(str(self.path), state)
                    raise RegistryError(code, self._metadata(state, now)) from None
                state = dict(state, entries=entries, fetched_at=now.isoformat(), sha256=sha256(body).hexdigest(),
                             retry_at=(now + REFRESH_INTERVAL).isoformat(), last_error=None)
                write_json_atomic(str(self.path), state)
                known = self._known(symbol, state, now)
                if known:
                    return known
                raise RegistryError('issuer_mapping_unavailable', self._metadata(state, now))
        except Timeout:
            raise RegistryError('issuer_registry_refresh_in_progress') from None
        except OSError:
            raise RegistryError('issuer_registry_cache_unavailable') from None
