# obsidian2confluence

obsidian2confluence performs a one-way, scheduled sync from an Obsidian vault to Confluence Cloud. Markdown notes (with optional YAML frontmatter) become Confluence pages, folder hierarchies map to the Confluence page tree, and attachments are uploaded as page assets. The tool runs inside Docker, keeps structured JSON logs, and maintains idempotent state in SQLite.

## Architecture

```
┌────────────┐      ┌──────────────┐      ┌───────────────┐      ┌────────────────┐
│Obsidian    │      │Scanner       │      │Sync Engine    │      │Confluence Cloud│
│Vault (/vault)├───►│(scan.py +    │──┬──►│(sync.py)      │──┬──►│REST APIs       │
└────────────┘      │frontmatter)  │  │   └───────────────┘  │   └────────────────┘
                    └──────────────┘  │                     │
                                      │                     │
                                      ▼                     ▼
                               ┌──────────────┐      ┌───────────────┐
                               │SQLite State  │◄────►│HTTP Client    │
                               │(.state/obs2cf)│     │(client.py)    │
                               └──────────────┘      └───────────────┘
```

## Limitations

- One-way sync: remote edits that conflict are reported but never merged automatically.
- Minimal Markdown→Confluence converter: advanced macros, callouts, and complex embeds remain TODOs.
- Attachments are uploaded per run; hashing to avoid redundant uploads is slated for future work.

## Getting Started

1. **Create an Atlassian API token** and determine your Confluence Cloud space key (⚙️ > Space Settings > Overview).
2. **Populate `.env`** (copy from `.env.example`) with Confluence credentials and vault configuration.
3. **Expose your Obsidian vault** on the host filesystem and run `docker compose up -d` (see mounting options below).
4. **First run** ensures the root page exists, uploads initial content, and writes state to `.state/obs2cf.db`.

### Configuration

All configuration lives in `.env` and is validated on startup.

| Variable | Description | Default |
| --- | --- | --- |
| `CONFLUENCE_BASE_URL` | Base URL of your wiki (e.g. `https://company.atlassian.net/wiki`) | – |
| `CONFLUENCE_EMAIL` | Account email for API token | – |
| `CONFLUENCE_API_TOKEN` | Atlassian API token | – |
| `CONFLUENCE_SPACE_KEY` | Target Confluence space key | – |
| `CONFLUENCE_ROOT_PAGE_TITLE` | Root page title under which notes are organised | `Knowledge Base` |
| `OBSIDIAN_VAULT_PATH` | Vault path inside the container (`/vault` in Docker) | – |
| `SYNC_INTERVAL_MINUTES` | Scheduler interval | `60` |
| `LOG_LEVEL` | `CRITICAL`/`ERROR`/`WARNING`/`INFO`/`DEBUG` | `INFO` |
| `DRY_RUN` | `true` to simulate without writing | `false` |

### Frontmatter Reference

```yaml
---
title: Optional custom page title
labels:
  - confluence
  - tag
parent: Parent Page Title          # defaults to folder structure under root
exclude: false                     # true skips syncing the note
page_id: 123456                    # binds to an existing Confluence page
---
```

### CLI Usage

- Run once locally: `python -m app.main --run-once`
- Ensure the root page exists (idempotent): `python -m app.main --rebuild-root`
- Start the scheduler (default mode): `python -m app.main`

### Docker Workflow

```
docker compose up -d            # build and start the hourly sync
docker compose logs -f          # stream structured JSON logs
docker compose down             # stop the service
```

Mounts (override via `OBSIDIAN_VAULT_HOST_PATH`):

- `/vault` (read-only) – your Obsidian vault.
- `/app/.state` – SQLite database (persists bindings and hashes).
- `/app/reports` & `/app/conflicts` – run reports and conflict logs.

### Dry Run

Set `DRY_RUN=true` in `.env` (or use a dedicated environment) to plan syncs without modifying Confluence. Each dry run writes `reports/plan_<timestamp>.md` summarising the proposed actions.

### Conflict Behaviour

When the local file has changed **and** the remote page has a newer version/timestamp, the sync skips the page, emits a warning, and records the issue in `conflicts/conflicts_<timestamp>.md`. Resolve the discrepancy manually, then re-run to clear the conflict.

### Development

```
make install        # install dependencies
make test           # run pytest suite (convert, conflicts, mapping)
make lint           # static analysis via ruff
make format         # black formatting
```

Individual commands:

- `pytest` – run unit tests.
- `ruff check app tests` – lint.
- `black app tests` – format.

### Troubleshooting

- **401/403 responses**: verify API token, email, and base URL; tokens are user-specific. Ensure the account has space write permissions.
- **Rate limiting (429)**: the client retries with exponential backoff. Increase `SYNC_INTERVAL_MINUTES` or reduce note volume during large migrations.
- **Attachments not updating**: Confluence caches attachments by filename. Delete the attachment manually or version filenames when necessary; richer hashing is planned.

### Future Work

1. Two-way sync with reconciliation of remote edits.
2. Full support for Obsidian embeds and advanced Confluence macros.
3. Attachment deduplication via hashing and conditional updates.
4. Graph-based link validation and reporting for unresolved references.

### License

MIT License – see `LICENSE`.

