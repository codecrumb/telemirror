# Telemirror

Self-hosted Telegram channel mirroring bot. Listens on source channels and forwards/copies messages to target channels, with optional filtering, editing, and deletion sync.

## Stack

- Python 3.x with asyncio, uvloop (non-Windows)
- [Telethon](https://github.com/LonamiWebs/Telethon) for Telegram MTProto
- PostgreSQL (psycopg3 + asyncpg pool) or in-memory LRU cache for message ID mapping
- aiohttp for the `/` health endpoint (required by some PaaS)
- Config via `.env` or `.configs/mirror.config.yml`

## Running

```bash
# Generate a session string first (one-time)
python login.py

# Run directly
python main.py

# Docker Compose (Postgres + bot)
docker-compose up
```

## Key files

| File | Purpose |
|------|---------|
| `main.py` | Entry point, wires database + Telemirror, starts health endpoint |
| `config.py` | Loads `.env` / yaml config into typed globals |
| `telemirror/mirroring.py` | Core event loop: `EventHandlers` → `EventProcessor` → send/forward |
| `telemirror/storage.py` | `MirrorMessage` NamedTuple + `InMemoryDatabase` / `PostgresDatabase` |
| `telemirror/messagefilters/` | Filter pipeline: `EmptyMessageFilter`, `UrlMessageFilter`, `ForwardFormatFilter`, `KeywordReplaceFilter`, etc. |
| `telemirror/mixins.py` | `CopyEventMessage`, `UpdateEntitiesParams`, `ChannelName`, `MessageLink` |
| `telemirror/_patch/` | Monkeypatches for Telethon: spoiler support, album timeout, send wrappers |
| `.configs/mirror.config.yml` | Per-direction filter/mode config (preferred over env vars for complex setups) |

## Architecture

```
Telegram MTProto
      │
      ▼
EventHandlers (registers Telethon event handlers)
  on_new_message / on_album / on_edit_message / on_deleted_message
      │
      ▼
EventProcessor
  new_message / new_album / edit_message / delete_message
  - looks up reply threading via Database
  - runs message through filter pipeline (config.filters.process)
  - calls send_message / send_file / forward_messages
  - persists original_id <-> mirror_id mapping to Database
      │
      ▼
Database (InMemoryDatabase | PostgresDatabase)
  binding_id table: (original_id, original_channel) <-> (mirror_id, mirror_channel)
```

## Config reference

```env
# Required
API_ID=
API_HASH=
SESSION_STRING=

# Database: either USE_MEMORY_DB=true or provide DB credentials
USE_MEMORY_DB=false
DATABASE_URL=postgres://user:pass@host/db
# or individually: DB_NAME, DB_USER, DB_PASS, DB_HOST

# Tuning
MEMORY_DB_MAX_CAPACITY=500   # LRU size for in-memory DB (affects reply threading range)
ALBUM_TIMEOUT=1.01           # seconds to wait for all album parts before forwarding

# Optional
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000
API_SYSTEM_VERSION=
API_DEVICE_MODEL=
API_APP_VERSION=

# Channel mapping (simple env-only setup)
CHAT_MAPPING=[-100SOURCE:-100TARGET]

# Or full YAML config (overrides env mapping)
YAML_CONFIG_ENV=...   # single-lined YAML string
# or place file at .configs/mirror.config.yml
```

## Filter pipeline

Filters are chained via `CompositeMessageFilter`. Each returns `FilterAction`:
- `CONTINUE` — pass to next filter
- `DISCARD` — drop message entirely
- `FORCE_SEND` — send immediately, skip remaining filters

Filters operate on both single messages and albums. Albums use `_process_album` which by default applies `_process_message` to each item.

Available filters (all in `telemirror/messagefilters/`):
- `EmptyMessageFilter` — no-op passthrough
- `SkipAllFilter` — drops everything
- `SkipUrlFilter` — drops messages containing URLs/mentions
- `UrlMessageFilter` — replaces URLs with a placeholder
- `ForwardFormatFilter` — prepends/appends forwarding attribution text
- `MappedNameForwardFormat` — like above but with a custom channel name map
- `KeywordReplaceFilter` — regex/word keyword replacement
- `SkipWithKeywordsFilter` — drops messages matching keywords
- `AllowWithKeywordsFilter` — drops messages NOT matching keywords

## Known issues / pending improvements

- **Message ordering race**: two near-simultaneous messages can forward in reversed order.
  Root cause: each Telethon event becomes an independent asyncio task; whichever completes
  `send_message` first wins. A per-source-chat `asyncio.Lock` would fix it. Currently
  accepted as-is since it's rare and low impact.

## Database schema (Postgres)

```sql
CREATE TABLE binding_id (
    id               serial primary key not null,
    original_id      bigint not null,
    original_channel bigint not null,
    mirror_id        bigint not null,
    mirror_channel   bigint not null
);
CREATE INDEX binding_id_original_idx ON binding_id (original_channel, original_id);
```

Auto-created on first run.
