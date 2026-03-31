"""ICS Calendar MCP Server — merges multiple ICS feeds into smart tools."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar
import recurring_ical_events
from fastmcp import FastMCP

TZ = ZoneInfo("Europe/Zurich")


def _get_feed_urls() -> list[str]:
    """Read ICS feed URLs from CALENDAR_URLS env var (comma-separated)."""
    raw = os.environ.get("CALENDAR_URLS", "")
    return [url.strip() for url in raw.split(",") if url.strip()]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_calendars() -> list[Calendar]:
    """Fetch and parse all configured ICS feeds."""
    urls = _get_feed_urls()
    if not urls:
        return []
    calendars = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for url in urls:
            resp = client.get(url)
            resp.raise_for_status()
            calendars.append(Calendar.from_ical(resp.content))
    return calendars


def _events_between(start: datetime, end: datetime) -> list[dict]:
    """Return merged events from all feeds between start and end."""
    calendars = _fetch_calendars()
    events = []
    for cal in calendars:
        for ev in recurring_ical_events.of(cal).between(start, end):
            events.append(_format_event(ev))
    events.sort(key=lambda e: e["start"])
    return events


def _format_event(ev) -> dict:
    """Convert an icalendar event component to a clean dict."""
    dtstart = ev.get("DTSTART")
    dtend = ev.get("DTEND")
    start = _to_datetime(dtstart.dt) if dtstart else None
    end = _to_datetime(dtend.dt) if dtend else None

    location = str(ev.get("LOCATION", "")) or None
    description = str(ev.get("DESCRIPTION", "")) or None
    summary = str(ev.get("SUMMARY", "")) or "Kein Titel"

    result = {
        "summary": summary,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }
    if location:
        result["location"] = location
    if description:
        desc_clean = description.strip()
        if desc_clean:
            result["description"] = desc_clean
    return result


def _to_datetime(dt) -> datetime:
    """Normalize a date or datetime to a timezone-aware datetime in Zurich."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    if isinstance(dt, date):
        return datetime(dt.year, dt.month, dt.day, tzinfo=TZ)
    return dt


def _today_range() -> tuple[datetime, datetime]:
    now = datetime.now(TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def _week_range() -> tuple[datetime, datetime]:
    now = datetime.now(TZ)
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(days=7)
    return start, end


def _format_event_list(events: list[dict], label: str) -> str:
    if not events:
        return f"Keine Termine {label}."
    lines = [f"📅 {label} ({len(events)} Termine):\n"]
    for ev in events:
        time_str = ""
        if ev["start"]:
            s = datetime.fromisoformat(ev["start"])
            time_str = s.strftime("%H:%M")
            if ev["end"]:
                e = datetime.fromisoformat(ev["end"])
                time_str += f"–{e.strftime('%H:%M')}"
        line = f"• {time_str}  {ev['summary']}"
        if ev.get("location"):
            line += f"  📍 {ev['location']}"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "ICS Calendar",
    instructions=(
        "MCP-Server der mehrere ICS-Kalender zusammenführt. "
        "Alle Zeiten sind Europe/Zurich."
    ),
)


@mcp.tool()
def get_events_today() -> str:
    """Alle Termine von heute (Stundenplan + Outlook kombiniert)."""
    start, end = _today_range()
    events = _events_between(start, end)
    today_str = datetime.now(TZ).strftime("%A, %d.%m.%Y")
    return _format_event_list(events, f"Heute — {today_str}")


@mcp.tool()
def get_events_tomorrow() -> str:
    """Alle Termine von morgen."""
    start, end = _today_range()
    start += timedelta(days=1)
    end += timedelta(days=1)
    events = _events_between(start, end)
    tomorrow_str = start.strftime("%A, %d.%m.%Y")
    return _format_event_list(events, f"Morgen — {tomorrow_str}")


@mcp.tool()
def get_events_this_week() -> str:
    """Alle Termine dieser Woche (Mo–So), gruppiert nach Tag."""
    start, end = _week_range()
    events = _events_between(start, end)
    if not events:
        return "Keine Termine diese Woche."

    by_day: dict[str, list[dict]] = {}
    for ev in events:
        if ev["start"]:
            day = datetime.fromisoformat(ev["start"]).strftime("%A, %d.%m.")
            by_day.setdefault(day, []).append(ev)

    lines = [f"📅 Diese Woche ({len(events)} Termine):\n"]
    for day, day_events in by_day.items():
        lines.append(f"\n🗓 {day}")
        for ev in day_events:
            s = datetime.fromisoformat(ev["start"])
            time_str = s.strftime("%H:%M")
            if ev["end"]:
                e = datetime.fromisoformat(ev["end"])
                time_str += f"–{e.strftime('%H:%M')}"
            line = f"  • {time_str}  {ev['summary']}"
            if ev.get("location"):
                line += f"  📍 {ev['location']}"
            lines.append(line)
    return "\n".join(lines)


@mcp.tool()
def get_next_event() -> str:
    """Der nächste anstehende Termin (innerhalb der nächsten 7 Tage)."""
    now = datetime.now(TZ)
    end = now + timedelta(days=7)
    events = _events_between(now, end)
    if not events:
        return "Keine Termine in den nächsten 7 Tagen."

    ev = events[0]
    s = datetime.fromisoformat(ev["start"])
    delta = s - now

    if delta.total_seconds() < 3600:
        time_hint = f"in {int(delta.total_seconds() / 60)} Minuten"
    elif delta.days == 0:
        time_hint = f"heute um {s.strftime('%H:%M')}"
    elif delta.days == 1:
        time_hint = f"morgen um {s.strftime('%H:%M')}"
    else:
        time_hint = f"am {s.strftime('%A, %d.%m. um %H:%M')}"

    result = f"⏭ Nächster Termin: {ev['summary']} — {time_hint}"
    if ev.get("location"):
        result += f"\n📍 {ev['location']}"
    if ev.get("end"):
        e = datetime.fromisoformat(ev["end"])
        result += f"\n🕐 {s.strftime('%H:%M')}–{e.strftime('%H:%M')}"
    return result


@mcp.tool()
def get_events_by_date(date_str: str) -> str:
    """Termine an einem bestimmten Datum.

    Args:
        date_str: Datum im Format YYYY-MM-DD (z.B. 2026-04-01)
    """
    d = date.fromisoformat(date_str)
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    events = _events_between(start, end)
    label = start.strftime("%A, %d.%m.%Y")
    return _format_event_list(events, label)


@mcp.tool()
def get_events_range(start_date: str, end_date: str) -> str:
    """Termine in einem Zeitraum.

    Args:
        start_date: Startdatum YYYY-MM-DD
        end_date: Enddatum YYYY-MM-DD (inklusive)
    """
    ds = date.fromisoformat(start_date)
    de = date.fromisoformat(end_date)
    start = datetime(ds.year, ds.month, ds.day, tzinfo=TZ)
    end = datetime(de.year, de.month, de.day, tzinfo=TZ) + timedelta(days=1)
    events = _events_between(start, end)
    label = f"{ds.strftime('%d.%m.')} – {de.strftime('%d.%m.%Y')}"
    return _format_event_list(events, label)


@mcp.tool()
def search_events(query: str, days_ahead: int = 30) -> str:
    """Suche nach Terminen per Stichwort (im Titel, Ort oder Beschreibung).

    Args:
        query: Suchbegriff (z.B. "Mathematik", "Prüfung", "Teams")
        days_ahead: Wie viele Tage voraus suchen (Standard: 30)
    """
    now = datetime.now(TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days_ahead)
    events = _events_between(start, end)

    q = query.lower()
    matches = [
        ev for ev in events
        if q in ev["summary"].lower()
        or q in (ev.get("location") or "").lower()
        or q in (ev.get("description") or "").lower()
    ]
    return _format_event_list(matches, f"Suche: \"{query}\" (nächste {days_ahead} Tage)")


@mcp.tool()
def get_free_slots_today() -> str:
    """Freie Zeitfenster heute — zeigt Lücken zwischen Terminen."""
    start, end = _today_range()
    events = _events_between(start, end)
    now = datetime.now(TZ)

    # Only consider events with proper start/end times
    blocks = []
    for ev in events:
        if ev["start"] and ev["end"]:
            s = datetime.fromisoformat(ev["start"])
            e = datetime.fromisoformat(ev["end"])
            if s.hour == 0 and s.minute == 0 and e.hour == 0 and e.minute == 0:
                continue  # skip all-day events
            blocks.append((s, e))

    if not blocks:
        return "Heute keine Termine — der ganze Tag ist frei! 🎉"

    blocks.sort(key=lambda b: b[0])

    # Merge overlapping blocks
    merged = [blocks[0]]
    for s, e in blocks[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    day_start = max(now, start.replace(hour=7, minute=0))
    day_end = start.replace(hour=22, minute=0)

    gaps = []
    cursor = day_start
    for block_start, block_end in merged:
        if block_start > cursor:
            gaps.append((cursor, block_start))
        cursor = max(cursor, block_end)
    if cursor < day_end:
        gaps.append((cursor, day_end))

    if not gaps:
        return "Heute keine freien Slots zwischen den Terminen."

    lines = [f"🟢 Freie Zeitfenster heute ({len(gaps)}):\n"]
    for gs, ge in gaps:
        duration = int((ge - gs).total_seconds() / 60)
        lines.append(f"• {gs.strftime('%H:%M')}–{ge.strftime('%H:%M')}  ({duration} Min.)")
    return "\n".join(lines)


@mcp.tool()
def get_week_overview() -> str:
    """Kompakte Wochenübersicht: Anzahl Termine & Stunden pro Tag."""
    start, end = _week_range()
    events = _events_between(start, end)

    by_day: dict[str, list[dict]] = {}
    for ev in events:
        if ev["start"]:
            day_key = datetime.fromisoformat(ev["start"]).strftime("%Y-%m-%d")
            by_day.setdefault(day_key, []).append(ev)

    lines = ["📊 Wochenübersicht:\n"]
    cursor = start
    for _ in range(7):
        day_key = cursor.strftime("%Y-%m-%d")
        day_name = cursor.strftime("%a %d.%m.")
        day_events = by_day.get(day_key, [])

        total_min = 0
        for ev in day_events:
            if ev["start"] and ev["end"]:
                s = datetime.fromisoformat(ev["start"])
                e = datetime.fromisoformat(ev["end"])
                total_min += int((e - s).total_seconds() / 60)

        count = len(day_events)
        hours = total_min / 60
        bar = "█" * count + "░" * max(0, 8 - count)
        lines.append(f"{day_name}  {bar}  {count} Termine, {hours:.1f}h")
        cursor += timedelta(days=1)

    return "\n".join(lines)
