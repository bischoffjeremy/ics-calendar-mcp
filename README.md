<p align="center">
  <img src="logo.png" alt="ICS Calendar MCP" width="800">
</p>

# ICS Calendar MCP Server

MCP server that merges multiple ICS calendar feeds and exposes them through smart tools. Built with [FastMCP](https://gofastmcp.com/).

Works with any standard ICS feed: **Outlook**, **Google Calendar**, **Apple**, **OST Stundenplan**, etc.

## Tools

### Read (ICS feeds + CalDAV)

| Tool | Description |
|------|-------------|
| `get_events_today` | Get all events for today |
| `get_events_tomorrow` | Get all events for tomorrow |
| `get_events_this_week` | Weekly overview (Mon–Sun) grouped by day |
| `get_next_event` | Next upcoming event with countdown |
| `get_events_by_date` | Events on a specific date |
| `get_events_range` | Events within a date range |
| `search_events` | Keyword search across title, location & description |
| `get_free_slots_today` | Free time slots between events |
| `get_week_overview` | Compact stats: events & hours per day |

### Write (CalDAV)

| Tool | Description |
|------|-------------|
| `list_calendars` | List all writable CalDAV calendars |
| `create_event` | Create a new event with time |
| `create_allday_event` | Create an all-day event |
| `update_event` | Update an existing event (title, time, location, ...) |
| `delete_event` | Delete an event by search query |

## Quick Start

### Docker (recommended)

```bash
cp .env.example .env
# Add your ICS feed URLs to .env

docker compose up -d --build
```

The server runs on `http://localhost:8001/mcp/` (Streamable HTTP transport).

### Local

```bash
pip install .
export CALENDAR_URLS="https://calendar.google.com/.../basic.ics,https://outlook.office365.com/.../calendar.ics"
fastmcp run src.server:mcp --transport streamable-http --host 0.0.0.0 --port 8001
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `CALENDAR_URLS` | Comma-separated list of ICS feed URLs (read-only) | *required* |
| `CALDAV_URL` | CalDAV server URL (for read/write) | *optional* |
| `CALDAV_USERNAME` | CalDAV username | *optional* |
| `CALDAV_PASSWORD` | CalDAV password / app password | *optional* |

### Supported CalDAV Providers

| Provider | CalDAV URL |
|----------|-----------|
| Google Calendar | `https://apidata.googleusercontent.com/caldav/v2/` |
| Nextcloud | `https://cloud.example.com/remote.php/dav/` |
| iCloud | `https://caldav.icloud.com/` |
| Fastmail | `https://caldav.fastmail.com/` |
| Radicale | `http://localhost:5232/` |

> **Tip:** For Google Calendar, create an [App Password](https://myaccount.google.com/apppasswords) and use your Gmail address as username.

## MCP Client Configuration

Add to your MCP client config (e.g. Claude Desktop, VS Code):

```json
{
  "mcpServers": {
    "ics-calendar": {
      "url": "http://localhost:8001/mcp/"
    }
  }
}
```

## License

MIT
