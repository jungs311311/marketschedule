from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Event:
    id: str
    category: str  # msci, nasdaq, sp500, bok, fomc, kr_options, us_options, dst
    title: str
    market: str  # KR, US, GLOBAL
    trade_date: str  # date used for alert selection, not a UTC date
    slot: str  # morning or evening (KST)
    phase: str = "event"
    occurs_at: str | None = None  # aware ISO timestamp, if officially known
    details: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    confirmed: bool = True
    announcement_date: str | None = None
    implementation_date: str | None = None
    effective_date: str | None = None


@dataclass
class Session:
    market: str
    date: str
    status: str  # open, closed, early_close, changed, unknown
    reason: str
    open_at: str | None = None
    close_at: str | None = None
    sources: list[str] = field(default_factory=list)
    confirmed: bool = True


@dataclass
class Result:
    provider: str
    events: list[Event] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    successful_scopes: list[str] = field(default_factory=list)
    failed_scopes: list[str] = field(default_factory=list)
    coverage_start: str | None = None
    coverage_end: str | None = None
    fetched_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Result:
        values = dict(data)
        values['events'] = [Event(**e) for e in data.get('events', [])]
        values['sessions'] = [Session(**s) for s in data.get('sessions', [])]
        return cls(**values)
