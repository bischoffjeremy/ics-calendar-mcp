# OST Calendar MCP Server

MCP-Server der den OST-Stundenplan und Outlook-Kalender zusammenführt und über smarte Tools abrufbar macht.

## Kalender-Quellen

| Quelle | Beschreibung |
|--------|-------------|
| `stundenplan` | OST Stundenplan (stundenplan-sg.ost.ch) |
| `outlook` | Outlook/Teams Kalender (office365.com) |

## Tools

| Tool | Beschreibung |
|------|-------------|
| `get_events_today` | Alle Termine von heute |
| `get_events_tomorrow` | Alle Termine von morgen |
| `get_events_this_week` | Wochenübersicht (Mo–So) gruppiert nach Tag |
| `get_next_event` | Nächster anstehender Termin mit Countdown |
| `get_events_by_date` | Termine an einem bestimmten Datum |
| `get_events_range` | Termine in einem Zeitraum |
| `search_events` | Stichwortsuche über Titel, Ort & Beschreibung |
| `get_free_slots_today` | Freie Zeitfenster zwischen Terminen |
| `get_week_overview` | Kompakte Statistik: Termine & Stunden pro Tag |

## Setup

```bash
podman compose up -d --build
```

Server läuft auf Port **8001** (Streamable HTTP).

### VS Code MCP Config

```json
{
  "servers": {
    "ost-calendar": {
      "type": "http",
      "url": "http://localhost:8001/mcp"
    }
  }
}
```

## Umgebungsvariablen (optional)

| Variable | Beschreibung |
|----------|-------------|
| `STUNDENPLAN_URL` | Überschreibt die Stundenplan-ICS-URL |
| `OUTLOOK_URL` | Überschreibt die Outlook-ICS-URL |
