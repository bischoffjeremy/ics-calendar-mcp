"""ICS Calendar MCP Server — read-only ICS feeds + read/write CalDAV calendars.

Calendar sources:
  - ICS feeds (CALENDAR_URLS): read-only, fetched via HTTP
  - CalDAV (CALDAV_URL): read & write, accessed via CalDAV protocol

Both sources are optional. Configure either, both, or none.
Read tools merge events from all configured sources.
Write tools (create/update/delete) only work with CalDAV calendars.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar, Event as ICalEvent
import recurring_ical_events
from fastmcp import FastMCP

TZ = ZoneInfo("Europe/Zurich")

# ---------------------------------------------------------------------------
# CalDAV (optional import — server works without it)
# ---------------------------------------------------------------------------

try:
    import caldav

    _HAS_CALDAV = True
except ImportError:
    _HAS_CALDAV = False

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _get_feed_urls() -> list[str]:
    raw = os.environ.get("CALENDAR_URLS", "")
    return [u.strip() for u in raw.split(",") if u.strip()]


def _get_caldav_client():
    if not _HAS_CALDAV:
        return None
    url = os.environ.get("CALDAV_URL", "").strip()
    if not url:
        return None
    return caldav.DAVClient(
        url=url,
        username=os.environ.get("CALDAV_USERNAME", "").strip(),
        password=os.environ.get("CALDAV_PASSWORD", "").strip(),
    )


def _get_caldav_calendars() -> list:
    client = _get_caldav_client()
    if not client:
        return []
    return client.principal().calendars()


def _find_caldav_calendar(name: str):
    for cal in _get_caldav_calendars():
        if (cal.get_display_name() or "").lower() == name.lower():
            return cal
    return None


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------


def _fetch_ics_events(start: datetime, end: datetime) -> list[dict]:
    """Fetch events from all ICS feeds (read-only) in the given range."""
    urls = _get_feed_urls()
    if not urls:
        return []
    events = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for url in urls:
            try:
                resp = client.get(url)
                resp.raise_for_status()
                cal = Calendar.from_ical(resp.content)
                for ev in recurring_ical_events.of(cal).between(start, end):
                    events.append(_format_event(ev))
            except Exception:
                pass
    return events


def _fetch_caldav_events(start: datetime, end: datetime) -> list[dict]:
    """Fetch events from all CalDAV calendars (read/write) in the given range."""
    events = []
    for dav_cal in _get_caldav_calendars():
        try:
            for obj in dav_cal.search(start=start, end=end, event=True):
                for comp in Calendar.from_ical(obj.data).walk():
                    if comp.name == "VEVENT":
                        events.append(_format_event(comp))
        except Exception:
            pass
    return events


def _events_between(start: datetime, end: datetime) -> list[dict]:
    """Merge events from all sources (ICS + CalDAV) in the given range."""
    events = _fetch_ics_events(start, end) + _fetch_caldav_events(start, end)
    events.sort(key=lambda e: e["start"] or "")
    return events


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_event(ev) -> dict:
    dtstart = ev.get("DTSTART")
    dtend = ev.get("DTEND")
    start = _to_dt(dtstart.dt) if dtstart else None
    end = _to_dt(dtend.dt) if dtend else None
    result = {
        "summary": str(ev.get("SUMMARY", "")) or "Kein Titel",
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }
    loc = str(ev.get("LOCATION", "")).strip()
    desc = str(ev.get("DESCRIPTION", "")).strip()
    if loc:
        result["location"] = loc
    if desc:
        result["description"] = desc
    return result


def _to_dt(dt) -> datetime:
    if isinstance(dt, datetime):
        return dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=TZ)
    if isinstance(dt, date):
        return datetime(dt.year, dt.month, dt.day, tzinfo=TZ)
    return dt


def _today_range():
    now = datetime.now(TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _week_range():
    now = datetime.now(TZ)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=7)


def _fmt_time(ev: dict) -> str:
    if not ev["start"]:
        return ""
    s = datetime.fromisoformat(ev["start"])
    t = s.strftime("%H:%M")
    if ev["end"]:
        t += f"–{datetime.fromisoformat(ev['end']).strftime('%H:%M')}"
    return t


def _fmt_list(events: list[dict], label: str) -> str:
    if not events:
        return f"Keine Termine {label}."
    lines = [f"📅 {label} ({len(events)} Termine):\n"]
    for ev in events:
        line = f"• {_fmt_time(ev)}  {ev['summary']}"
        if ev.get("location"):
            line += f"  📍 {ev['location']}"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Server — Read tools (ICS + CalDAV combined)
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "ICS Calendar",
    instructions=(
        "MCP-Server der mehrere ICS-Kalender zusammenführt. "
        "ICS-Feeds sind read-only, CalDAV-Kalender sind read/write. "
        "Alle Zeiten sind Europe/Zurich."
    ),
)


@mcp.tool()
def get_events_today() -> str:
    """Alle Termine von heute aus allen Quellen (ICS-Feeds + CalDAV)."""
    start, end = _today_range()
    label = datetime.now(TZ).strftime("Heute — %A, %d.%m.%Y")
    return _fmt_list(_events_between(start, end), label)


@mcp.tool()
def get_events_tomorrow() -> str:
    """Alle Termine von morgen aus allen Quellen (ICS-Feeds + CalDAV)."""
    start, end = _today_range()
    start += timedelta(days=1)
    end += timedelta(days=1)
    return _fmt_list(_events_between(start, end), f"Morgen — {start.strftime('%A, %d.%m.%Y')}")


@mcp.tool()
def get_events_this_week() -> str:
    """Alle Termine dieser Woche (Mo–So) aus allen Quellen, gruppiert nach Tag."""
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
    for day, devs in by_day.items():
        lines.append(f"\n🗓 {day}")
        for ev in devs:
            line = f"  • {_fmt_time(ev)}  {ev['summary']}"
            if ev.get("location"):
                line += f"  📍 {ev['location']}"
            lines.append(line)
    return "\n".join(lines)


@mcp.tool()
def get_next_event() -> str:
    """Der nächste anstehende Termin (innerhalb 7 Tage) aus allen Quellen."""
    now = datetime.now(TZ)
    events = _events_between(now, now + timedelta(days=7))
    if not events:
        return "Keine Termine in den nächsten 7 Tagen."

    ev = events[0]
    s = datetime.fromisoformat(ev["start"])
    delta = s - now

    if delta.total_seconds() < 3600:
        hint = f"in {int(delta.total_seconds() / 60)} Minuten"
    elif delta.days == 0:
        hint = f"heute um {s.strftime('%H:%M')}"
    elif delta.days == 1:
        hint = f"morgen um {s.strftime('%H:%M')}"
    else:
        hint = f"am {s.strftime('%A, %d.%m. um %H:%M')}"

    result = f"⏭ Nächster Termin: {ev['summary']} — {hint}"
    if ev.get("location"):
        result += f"\n📍 {ev['location']}"
    if ev["end"]:
        result += f"\n🕐 {_fmt_time(ev)}"
    return result


@mcp.tool()
def get_events_by_date(date_str: str) -> str:
    """Termine an einem bestimmten Datum aus allen Quellen (ICS + CalDAV).

    Args:
        date_str: Datum im Format YYYY-MM-DD
    """
    d = date.fromisoformat(date_str)
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    return _fmt_list(_events_between(start, start + timedelta(days=1)), start.strftime("%A, %d.%m.%Y"))


@mcp.tool()
def get_events_range(start_date: str, end_date: str) -> str:
    """Termine in einem Zeitraum aus allen Quellen (ICS + CalDAV).

    Args:
        start_date: Startdatum YYYY-MM-DD
        end_date: Enddatum YYYY-MM-DD (inklusive)
    """
    ds = date.fromisoformat(start_date)
    de = date.fromisoformat(end_date)
    start = datetime(ds.year, ds.month, ds.day, tzinfo=TZ)
    end = datetime(de.year, de.month, de.day, tzinfo=TZ) + timedelta(days=1)
    return _fmt_list(_events_between(start, end), f"{ds.strftime('%d.%m.')} – {de.strftime('%d.%m.%Y')}")


@mcp.tool()
def search_events(query: str, days_ahead: int = 365) -> str:
    """Suche nach Terminen per Stichwort in allen Quellen (ICS + CalDAV).

    Args:
        query: Suchbegriff (Titel, Ort oder Beschreibung)
        days_ahead: Wie viele Tage voraus suchen (Standard: 365)
    """
    start = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=max(days_ahead, 1))
    q = query.lower()
    matches = [
        ev for ev in _events_between(start, end)
        if q in ev["summary"].lower()
        or q in (ev.get("location") or "").lower()
        or q in (ev.get("description") or "").lower()
    ]
    label = f'Suche: "{query}" (nächste {days_ahead} Tage)'
    return _fmt_list(matches, label)


@mcp.tool()
def get_free_slots_today() -> str:
    """Freie Zeitfenster heute — zeigt Lücken zwischen Terminen (alle Quellen)."""
    start, end = _today_range()
    events = _events_between(start, end)
    now = datetime.now(TZ)

    blocks = []
    for ev in events:
        if ev["start"] and ev["end"]:
            s, e = datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"])
            if not (s.hour == 0 and s.minute == 0 and e.hour == 0 and e.minute == 0):
                blocks.append((s, e))
    if not blocks:
        return "Heute keine Termine — der ganze Tag ist frei! 🎉"

    blocks.sort()
    merged = [blocks[0]]
    for s, e in blocks[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    day_start = max(now, start.replace(hour=7))
    day_end = start.replace(hour=22)
    gaps, cursor = [], day_start
    for bs, be in merged:
        if bs > cursor:
            gaps.append((cursor, bs))
        cursor = max(cursor, be)
    if cursor < day_end:
        gaps.append((cursor, day_end))

    if not gaps:
        return "Heute keine freien Slots zwischen den Terminen."
    lines = [f"🟢 Freie Zeitfenster heute ({len(gaps)}):\n"]
    for gs, ge in gaps:
        lines.append(f"• {gs.strftime('%H:%M')}–{ge.strftime('%H:%M')}  ({int((ge - gs).total_seconds() / 60)} Min.)")
    return "\n".join(lines)


@mcp.tool()
def get_week_overview() -> str:
    """Kompakte Wochenübersicht mit Terminen pro Tag (alle Quellen)."""
    start, end = _week_range()
    events = _events_between(start, end)

    by_day: dict[str, list[dict]] = {}
    for ev in events:
        if ev["start"]:
            by_day.setdefault(datetime.fromisoformat(ev["start"]).strftime("%Y-%m-%d"), []).append(ev)

    lines = ["📊 Wochenübersicht:\n"]
    cursor = start
    for _ in range(7):
        key = cursor.strftime("%Y-%m-%d")
        day_events = by_day.get(key, [])
        total_min = sum(
            int((datetime.fromisoformat(e["end"]) - datetime.fromisoformat(e["start"])).total_seconds() / 60)
            for e in day_events if e["start"] and e["end"]
        )
        n = len(day_events)
        bar = "█" * n + "░" * max(0, 8 - n)
        lines.append(f"{cursor.strftime('%a %d.%m.')}  {bar}  {n} Termine, {total_min / 60:.1f}h")
        cursor += timedelta(days=1)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Server — Write tools (CalDAV only)
# ---------------------------------------------------------------------------


@mcp.tool()
def list_calendars() -> str:
    """Liste alle beschreibbaren CalDAV-Kalender auf.

    Nur CalDAV-Kalender unterstützen Schreibzugriff (create/update/delete).
    ICS-Feeds sind read-only und werden hier nicht aufgelistet.
    Der angezeigte Name wird als calendar_name Parameter verwendet.
    """
    calendars = _get_caldav_calendars()
    if not calendars:
        return "❌ Kein CalDAV-Server konfiguriert. Setze CALDAV_URL/USERNAME/PASSWORD in .env"

    lines = [f"📚 {len(calendars)} beschreibbare CalDAV-Kalender:\n"]
    for cal in calendars:
        name = cal.get_display_name() or "(Kein Name)"
        try:
            count = len(cal.events())
        except Exception:
            count = "?"
        lines.append(f"• {name}  ({count} Events)")
    return "\n".join(lines)


@mcp.tool()
def create_event(
    calendar_name: str,
    summary: str,
    start_date: str,
    start_time: str,
    end_time: str,
    location: str = "",
    description: str = "",
) -> str:
    """Erstelle einen neuen Termin in einem CalDAV-Kalender (nur CalDAV, nicht ICS-Feeds).

    Args:
        calendar_name: Name des CalDAV-Kalenders (siehe list_calendars)
        summary: Titel des Termins
        start_date: Datum YYYY-MM-DD
        start_time: Startzeit HH:MM
        end_time: Endzeit HH:MM
        location: Ort (optional)
        description: Beschreibung (optional)
    """
    cal = _find_caldav_calendar(calendar_name)
    if not cal:
        names = [c.get_display_name() for c in _get_caldav_calendars()]
        return f"❌ Kalender '{calendar_name}' nicht gefunden. Verfügbar: {', '.join(names) or 'keine'}"

    d = date.fromisoformat(start_date)
    sh, sm = map(int, start_time.split(":"))
    eh, em = map(int, end_time.split(":"))

    event = ICalEvent()
    event.add("uid", f"{uuid.uuid4()}@ics-calendar-mcp")
    event.add("dtstamp", datetime.now(TZ))
    event.add("dtstart", datetime(d.year, d.month, d.day, sh, sm, tzinfo=TZ))
    event.add("dtend", datetime(d.year, d.month, d.day, eh, em, tzinfo=TZ))
    event.add("summary", summary)
    if location:
        event.add("location", location)
    if description:
        event.add("description", description)

    ical = Calendar()
    ical.add("prodid", "-//ICS Calendar MCP//EN")
    ical.add("version", "2.0")
    ical.add_component(event)
    cal.save_event(ical.to_ical().decode())

    return f"✅ Termin erstellt in '{calendar_name}':\n📅 {summary}\n🕐 {start_date} {start_time}–{end_time}" + (f"\n📍 {location}" if location else "")


@mcp.tool()
def create_allday_event(
    calendar_name: str,
    summary: str,
    start_date: str,
    end_date: str = "",
    location: str = "",
    description: str = "",
) -> str:
    """Erstelle einen ganztägigen Termin in einem CalDAV-Kalender (nur CalDAV).

    Args:
        calendar_name: Name des CalDAV-Kalenders (siehe list_calendars)
        summary: Titel des Termins
        start_date: Startdatum YYYY-MM-DD
        end_date: Enddatum YYYY-MM-DD (optional, Standard = start_date)
        location: Ort (optional)
        description: Beschreibung (optional)
    """
    cal = _find_caldav_calendar(calendar_name)
    if not cal:
        names = [c.get_display_name() for c in _get_caldav_calendars()]
        return f"❌ Kalender '{calendar_name}' nicht gefunden. Verfügbar: {', '.join(names) or 'keine'}"

    ds = date.fromisoformat(start_date)
    de = date.fromisoformat(end_date) + timedelta(days=1) if end_date else ds + timedelta(days=1)

    event = ICalEvent()
    event.add("uid", f"{uuid.uuid4()}@ics-calendar-mcp")
    event.add("dtstamp", datetime.now(TZ))
    event.add("dtstart", ds)
    event.add("dtend", de)
    event.add("summary", summary)
    if location:
        event.add("location", location)
    if description:
        event.add("description", description)

    ical = Calendar()
    ical.add("prodid", "-//ICS Calendar MCP//EN")
    ical.add("version", "2.0")
    ical.add_component(event)
    cal.save_event(ical.to_ical().decode())

    label = start_date if not end_date else f"{start_date} – {end_date}"
    return f"✅ Ganztägiger Termin erstellt in '{calendar_name}':\n📅 {summary}\n🗓 {label}" + (f"\n📍 {location}" if location else "")


@mcp.tool()
def delete_event(calendar_name: str, query: str, event_date: str = "") -> str:
    """Lösche einen Termin aus einem CalDAV-Kalender (nur CalDAV, nicht ICS-Feeds).

    Args:
        calendar_name: Name des CalDAV-Kalenders
        query: Suchbegriff im Titel des Termins
        event_date: Datum YYYY-MM-DD zur Eingrenzung (optional, empfohlen)
    """
    cal = _find_caldav_calendar(calendar_name)
    if not cal:
        names = [c.get_display_name() for c in _get_caldav_calendars()]
        return f"❌ Kalender '{calendar_name}' nicht gefunden. Verfügbar: {', '.join(names) or 'keine'}"

    q = query.lower()
    if event_date:
        d = date.fromisoformat(event_date)
        start = datetime(d.year, d.month, d.day, tzinfo=TZ)
        results = cal.search(start=start, end=start + timedelta(days=1), event=True, expand=True)
    else:
        results = cal.events()

    matches = []
    for obj in results:
        try:
            for comp in Calendar.from_ical(obj.data).walk():
                if comp.name == "VEVENT" and q in str(comp.get("SUMMARY", "")).lower():
                    matches.append((obj, str(comp.get("SUMMARY", ""))))
                    break
        except Exception:
            pass

    if not matches:
        return f"❌ Kein Termin mit '{query}' gefunden in '{calendar_name}'."
    if len(matches) > 1:
        return f"⚠️ {len(matches)} Treffer für '{query}' — bitte genauer eingrenzen:\n" + "\n".join(f"• {t}" for _, t in matches)

    obj, title = matches[0]
    obj.delete()
    return f"🗑 Termin gelöscht: {title}"


@mcp.tool()
def update_event(
    calendar_name: str,
    query: str,
    event_date: str = "",
    new_summary: str = "",
    new_date: str = "",
    new_start_time: str = "",
    new_end_time: str = "",
    new_location: str = "",
    new_description: str = "",
) -> str:
    """Aktualisiere einen Termin in einem CalDAV-Kalender (nur CalDAV, nicht ICS-Feeds).

    Args:
        calendar_name: Name des CalDAV-Kalenders
        query: Suchbegriff im Titel zum Finden des Termins
        event_date: Datum YYYY-MM-DD zur Eingrenzung (optional, empfohlen)
        new_summary: Neuer Titel (leer = nicht ändern)
        new_date: Neues Datum YYYY-MM-DD (leer = nicht ändern)
        new_start_time: Neue Startzeit HH:MM (leer = nicht ändern)
        new_end_time: Neue Endzeit HH:MM (leer = nicht ändern)
        new_location: Neuer Ort (leer = nicht ändern)
        new_description: Neue Beschreibung (leer = nicht ändern)
    """
    cal = _find_caldav_calendar(calendar_name)
    if not cal:
        names = [c.get_display_name() for c in _get_caldav_calendars()]
        return f"❌ Kalender '{calendar_name}' nicht gefunden. Verfügbar: {', '.join(names) or 'keine'}"

    q = query.lower()
    if event_date:
        d = date.fromisoformat(event_date)
        start = datetime(d.year, d.month, d.day, tzinfo=TZ)
        results = cal.search(start=start, end=start + timedelta(days=1), event=True, expand=True)
    else:
        results = cal.events()

    matches = []
    for obj in results:
        try:
            for comp in Calendar.from_ical(obj.data).walk():
                if comp.name == "VEVENT" and q in str(comp.get("SUMMARY", "")).lower():
                    matches.append((obj, str(comp.get("SUMMARY", ""))))
                    break
        except Exception:
            pass

    if not matches:
        return f"❌ Kein Termin mit '{query}' gefunden in '{calendar_name}'."
    if len(matches) > 1:
        return f"⚠️ {len(matches)} Treffer für '{query}' — bitte genauer eingrenzen:\n" + "\n".join(f"• {t}" for _, t in matches)

    obj, old_title = matches[0]
    parsed = Calendar.from_ical(obj.data)

    for comp in parsed.walk():
        if comp.name != "VEVENT":
            continue
        if new_summary:
            comp.pop("SUMMARY", None)
            comp.add("summary", new_summary)
        if new_date or new_start_time:
            old = _to_dt(comp.get("DTSTART").dt)
            d = date.fromisoformat(new_date) if new_date else old.date()
            h, m = (map(int, new_start_time.split(":")) if new_start_time else (old.hour, old.minute))
            comp.pop("DTSTART", None)
            comp.add("dtstart", datetime(d.year, d.month, d.day, h, m, tzinfo=TZ))
        if new_date or new_end_time:
            old = _to_dt(comp.get("DTEND").dt)
            d = date.fromisoformat(new_date) if new_date else old.date()
            h, m = (map(int, new_end_time.split(":")) if new_end_time else (old.hour, old.minute))
            comp.pop("DTEND", None)
            comp.add("dtend", datetime(d.year, d.month, d.day, h, m, tzinfo=TZ))
        if new_location:
            comp.pop("LOCATION", None)
            comp.add("location", new_location)
        if new_description:
            comp.pop("DESCRIPTION", None)
            comp.add("description", new_description)
        break

    obj.data = parsed.to_ical().decode()
    obj.save()
    return f"✅ Termin aktualisiert: {old_title} → {new_summary or old_title}"
