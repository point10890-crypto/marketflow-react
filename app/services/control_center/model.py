"""관제 결과의 공통 모양."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

KST = timezone(timedelta(hours=9))

# 심각도 순서: 높을수록 나쁘다. skipped/unknown 은 '모름' 이지 '정상' 이 아니다.
STATUS_ORDER = {'ok': 0, 'skipped': 1, 'unknown': 2, 'warn': 3, 'fail': 4}
FAMILIES = ('process', 'endpoint', 'page', 'data', 'job', 'task', 'provider', 'host', 'security', 'monitor')


def now_kst() -> datetime:
    return datetime.now(KST)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec='seconds') if dt else None


def worst(statuses) -> str:
    items = [s for s in statuses if s in STATUS_ORDER]
    if not items:
        return 'unknown'
    return max(items, key=lambda s: STATUS_ORDER[s])


@dataclass
class CheckResult:
    """감시 항목 하나의 한 번 관측.

    id 는 안정적인 키다(예: `endpoint:/api/health`, `job:kr_close_bet`). 사건(incident)은 id 로 묶인다.
    detail 에는 사람이 읽는 한 줄 설명, data 에는 기계가 읽는 값(비밀값 금지).
    """

    id: str
    family: str
    target: str
    status: str
    detail: str = ''
    severity: str = 'standard'          # critical | standard | info — 실패 시 사건 심각도
    latency_ms: int | None = None
    value: Any = None
    data: dict[str, Any] = field(default_factory=dict)
    observed_at: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUS_ORDER:
            raise ValueError(f'unknown status {self.status!r}')
        if self.family not in FAMILIES:
            raise ValueError(f'unknown family {self.family!r}')
        if self.severity not in ('critical', 'standard', 'info'):
            raise ValueError(f'unknown severity {self.severity!r}')
        if self.observed_at is None:
            self.observed_at = iso(now_kst())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
