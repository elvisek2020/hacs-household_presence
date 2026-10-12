"""Planned absence from calendars (FR-PLAN-01..04, FR-HH-06)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from .model import CalendarData, CalendarEvent, PlanConfig, fold


@dataclass(frozen=True, kw_only=True)
class Block:
    """Merged absence block including lead and trail."""

    start: datetime
    end: datetime

    def contains(self, now: datetime) -> bool:
        """Return True when ``now`` is inside the block."""
        return self.start <= now < self.end


def _matches(event: CalendarEvent, keywords: tuple[str, ...]) -> bool:
    if not keywords:
        return True
    summary = fold(event.summary)
    return any(k in summary for k in keywords)


def collect(
    calendar_ids: Iterable[str],
    calendars: Mapping[str, CalendarData],
    keywords: tuple[str, ...],
    *,
    all_day: bool,
) -> tuple[list[CalendarEvent], list[str]]:
    """Return matching events and the calendars that failed to load."""
    events: list[CalendarEvent] = []
    failed: list[str] = []
    for cal in calendar_ids:
        data = calendars.get(cal)
        if data is None or not data.ok:
            failed.append(cal)
            continue
        events.extend(
            e for e in data.events if (all_day or not e.all_day) and _matches(e, keywords)
        )
    events.sort(key=lambda e: (e.start, e.end))
    return events, failed


def build_blocks(cfg: PlanConfig, events: Iterable[CalendarEvent]) -> list[Block]:
    """Merge events across short gaps and widen them by lead and trail."""
    merged: list[list[datetime]] = []
    for event in sorted(events, key=lambda e: (e.start, e.end)):
        if event.end <= event.start:
            continue
        if merged and event.start - merged[-1][1] <= cfg.gap_bridge:
            merged[-1][1] = max(merged[-1][1], event.end)
        else:
            merged.append([event.start, event.end])
    blocks: list[Block] = []
    for start, end in merged:
        widened = Block(start=start - cfg.lead, end=end + cfg.trail)
        if blocks and widened.start <= blocks[-1].end:
            blocks[-1] = Block(start=blocks[-1].start, end=max(blocks[-1].end, widened.end))
        else:
            blocks.append(widened)
    return blocks


def active_block(blocks: Iterable[Block], now: datetime) -> Block | None:
    """Return the block running at ``now``."""
    return next((b for b in blocks if b.contains(now)), None)


def active_event(events: Iterable[CalendarEvent], now: datetime) -> CalendarEvent | None:
    """Return the running event that ends last (household vacation)."""
    running = [e for e in events if e.start <= now < e.end]
    return max(running, key=lambda e: e.end, default=None)
