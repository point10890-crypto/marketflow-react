"""Deterministic time, identity and public-link validation."""
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

KST = timezone(timedelta(hours=9))
PARTICLES = '은|는|이|가|을|를|의|에|에서|에게|와|과|도|만|로|으로|부터|까지'


def stamp(value, *, legacy_kst=False):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(parsed, datetime):
        raise ValueError('timestamp_missing')
    if parsed.tzinfo is None:
        if not legacy_kst:
            raise ValueError('timestamp_timezone_missing')
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def clock(value=None):
    return stamp(value) if value is not None else datetime.now(KST)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def normalized_name(value):
    value = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).casefold()
    return re.sub(r'^(?:주식회사|\(주\))|(?:주식회사|\(주\))$', '', value)


def title_matches(title, issuer):
    name = unicodedata.normalize('NFKC', issuer)
    title = unicodedata.normalize('NFKC', title)
    return bool(len(name) >= 2 and re.search(
        rf'(?<!\w){re.escape(name)}(?=$|\W|(?:{PARTICLES})(?=$|\W))', title, re.IGNORECASE))


def sports_title(title, publisher=None):
    """Company-branded sports teams are not evidence about the listed issuer."""
    if re.search(r'(?:공급|판매|후원|스폰서십)\s*계약|업무협약', title):
        return False  # A company can have a real business contract involving sport.
    explicit_sport = re.search(r'배구|농구|야구|축구|V[- ]?리그|K리그|슈퍼리그', title, re.IGNORECASE)
    coach_result = ('감독' in title and any(term in title for term in ('격파', '승리', '연승', '완승', '패배', '역전', '세트')))
    sports_publisher = re.search(r'스포츠|스포티비|SPOTV|OSEN', publisher or '', re.IGNORECASE)
    publisher_result = sports_publisher and any(term in title for term in (
        '이겼', '자축', '격파', '승리', '연승', '완승', '패배', '역전', '꺾었', '꺾고'))
    return bool(explicit_sport or coach_result or publisher_result)


def safe_url(value):
    """Only public HTTP links; never persist credentials or tracking secrets."""
    if not isinstance(value, str) or len(value) > 4096 or re.search(r'[\s\x00-\x1f\\]', value):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower().rstrip('.')
        if (parsed.scheme not in {'https', 'http'} or parsed.username or parsed.password
                or not host or '.' not in host or '%' in host or parsed.port not in {None, 80, 443}
                or host.endswith(('.localhost', '.local', '.internal', '.lan', '.home', '.localdomain', '.test', '.invalid'))):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if re.fullmatch(r'[0-9.]+', host) or host.startswith('0x'):
                return None
        query = []
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            if re.search(r'key|token|secret|password|credential|signature', key, re.IGNORECASE):
                return None
            if not key.lower().startswith('utm_') and key.lower() not in {'fbclid', 'gclid'}:
                query.append((key, item))
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, urlencode(sorted(query)), ''))
    except ValueError:
        return None
