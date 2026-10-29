# Relationship CRM

Local SQLite CRM with a Telegram bot for confirmed interaction capture. The CLI remains usable without Telegram credentials. No social scraping or contact messaging is implemented.

## Install

Requires Python 3.11 or newer. Create an isolated environment and install this repository:

```sh
.venv/bin/python -m venv .venv
.venv/bin/pip install -e .
```

Use `.venv/bin/python` for the commands below.

## CLI quick start

```sh
.venv/bin/python app.py --user demo add 'Anna Example' --email anna@example.test --org ExampleCo
.venv/bin/python app.py --user demo interaction 1 'Discussed project status'
.venv/bin/python app.py --user demo followup 1 2026-11-02 'Send the requested notes'
.venv/bin/python app.py --user demo today
.venv/bin/python app.py --user demo search Anna
.venv/bin/python app.py --user demo export contacts.csv
.venv/bin/python app.py --user demo delete 1 --confirm
```

Export contains contacts, interaction history and follow-ups in CSV (nested records are JSON columns) or Markdown. `delete-user-data --confirm` removes all CRM data for the specified local owner. Each CLI query is scoped to `--user`. Dates in storage are ISO calendar dates; event timestamps are UTC.

## Telegram bot

Set `TELEGRAM_BOT_TOKEN`, `CRM_ALLOWED_USER_IDS` (comma-separated Telegram numeric IDs), and optionally `CRM_TIMEZONE` in the process environment. Do not paste the bot token into chat or commit it. Then run:

```sh
.venv/bin/python telegram_bot.py --db crm.sqlite3
```

The bot accepts only private messages from allowlisted IDs. `/capture` previews contact, note and follow-up date before `/confirm`; `/cancel` discards the pending action. It supports `/contacts`, `/search`, `/add`, `/log`, `/followup`, `/history`, `/briefing`, `/done`, `/duplicates`, `/merge`, `/delete`, `/tag`, `/project`, and `/export`. A weekday such as Friday resolves to the next occurrence in `CRM_TIMEZONE` and is shown for confirmation. Ambiguous dates are rejected. The bot never contacts CRM contacts.

SQLite migrations are versioned in `schema_migrations`; Telegram update IDs and outbound responses persist across restarts. Outbound responses use an at-most-once policy: failures are retained in the local outbox and are not automatically retried, avoiding duplicate messages. A crash during a Telegram send may leave a delivery marked `uncertain`; inspect the database before manual retry.

## Tests

```sh
.venv/bin/python -m unittest discover -v
```

## Implemented and limitations

Implemented: owner-scoped contacts and history, follow-up scheduling/listing, duplicate suggestions, confirmation before merge/delete/capture, tags/projects, export/delete, Telegram allowlist, timezone-aware weekday parsing, schema migrations and idempotent update processing.

Planned: automated daily notifications with quiet hours and delivery ledger integration, editable organizations as first-class CRM records, richer project/contact reports and a Telegram export document flow. Reminders currently appear in `/briefing`; they are not pushed. This is a local personal CRM, not a multi-tenant hosted service.
