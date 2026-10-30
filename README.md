# Relationship CRM

![Relationship CRM banner](assets/banner.svg)

[![CI](https://github.com/jezannn16/relationship-crm/actions/workflows/ci.yml/badge.svg)](https://github.com/jezannn16/relationship-crm/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)

**A private, local SQLite CRM with an optional Telegram capture bot.** Track people, interaction history, tags, projects, and follow-ups. The command-line workflow needs no account or network access. Telegram is opt-in and accepts only private messages from configured user IDs.

| | |
|---|---|
| **Storage** | Local SQLite database |
| **CLI** | Available offline, scoped by `--user` |
| **Telegram** | Optional long polling; replies only in the bot chat |
| **Contact messaging** | Not implemented |

## Contents

- [Quick start](#quick-start)
- [Telegram setup](#telegram-setup)
- [How capture works](#how-capture-works)
- [CLI reference](#cli-reference)
- [Privacy and limits](#privacy-and-limits)
- [Development](#development)

## Quick start

Python 3.11 or newer is required. Check that `python3 --version` reports a supported version; if your system's `python3` is older, use the explicit path to an installed Python 3.11+ executable in the venv command. Create an isolated environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

Run the synthetic local walkthrough against a temporary database:

```sh
.venv/bin/python app.py --db /tmp/crm-demo.sqlite3 --user demo add 'Anna Example' --email anna@example.test --org ExampleCo
.venv/bin/python app.py --db /tmp/crm-demo.sqlite3 --user demo interaction 1 'Discussed the project timeline'
.venv/bin/python app.py --db /tmp/crm-demo.sqlite3 --user demo followup 1 2026-11-02 'Share the timeline'
.venv/bin/python app.py --db /tmp/crm-demo.sqlite3 --user demo today --date 2026-11-02
.venv/bin/python app.py --db /tmp/crm-demo.sqlite3 --user other search Anna
.venv/bin/python app.py --db /tmp/crm-demo.sqlite3 --user demo edit 1 --notes 'Updated synthetic note'
.venv/bin/python app.py --db /tmp/crm-demo.sqlite3 --user demo tag 1 customer
.venv/bin/python app.py --db /tmp/crm-demo.sqlite3 --user demo tags
```

The final search is empty because every CLI query is scoped to its `--user`. The dates and contact are synthetic; use a future or current date to try your own follow-up.

## Telegram setup

The Telegram bot is optional. It needs a bot token from BotFather and your numeric Telegram user ID. Keep the token in a local environment variable or secret manager; do not place it in source, chat, tickets, or GitHub Actions logs. Restrict the bot to your ID with `CRM_ALLOWED_USER_IDS` before starting it.

```sh
export TELEGRAM_BOT_TOKEN='set-this-in-your-local-shell'
export CRM_ALLOWED_USER_IDS='your-numeric-telegram-user-id'
export CRM_TIMEZONE='Europe/Moscow'
.venv/bin/python telegram_bot.py --db /tmp/crm-telegram-test.sqlite3
```

Starting polling connects to Telegram and incoming private messages receive bot replies. For a credential check that does **not** read queued updates or send a message, run this separately before polling:

```sh
.venv/bin/python check_telegram_token.py
```

It calls only Telegram Bot API [`getMe`](https://core.telegram.org/bots/api#getme) and prints the bot username. This checks network access and token validity, not command handling or message delivery. If a token has been exposed, revoke it through BotFather and replace it locally.

The bot's `/capture` flow previews a parsed interaction and follow-up. Confirming writes both to the local CRM. `/add`, `/log`, `/followup`, `/merge`, and `/delete` also change local records; `/confirm` is not a dry-run command.

## How capture works

```mermaid
flowchart LR
    A[Private Telegram message] --> B{Sender ID allowlisted?}
    B -- no --> C[Access denied reply]
    B -- yes --> D[Parse command]
    D --> E[Preview capture]
    E --> F{User confirms?}
    F -- cancel --> G[Discard pending action]
    F -- confirm --> H[Contacts, interactions, follow-ups in local SQLite]
    C --> I[Bot response through Telegram]
    G --> I
    H --> I
```

The bot does not search social networks or message CRM contacts. The only outgoing Telegram messages are responses to the chat that sent a bot command.

## CLI reference

```sh
# Add a contact, record an interaction, and schedule a follow-up.
.venv/bin/python app.py --db crm.sqlite3 --user me add 'Anna Example' --email anna@example.test --org ExampleCo
.venv/bin/python app.py --db crm.sqlite3 --user me interaction 1 'Discussed project status'
.venv/bin/python app.py --db crm.sqlite3 --user me followup 1 2026-11-02 'Send the notes'

# Search, review due items, and export this owner's records.
.venv/bin/python app.py --db crm.sqlite3 --user me search Anna
.venv/bin/python app.py --db crm.sqlite3 --user me today
.venv/bin/python app.py --db crm.sqlite3 --user me export contacts.csv --format csv
.venv/bin/python app.py --db crm.sqlite3 --user me export owner-data.json --format json
```

CSV and Markdown exports include contact-linked interactions, follow-ups, tags, and projects. JSON export is the complete owner-scoped bundle, including unassigned tags, projects with descriptions, and organization records with notes.

Dates use `YYYY-MM-DD`; `today` compares due dates against the selected date and does not send reminders. Merge and delete commands require `--confirm`. `delete-user-data --confirm` removes contacts, interactions, follow-ups, tags, projects, organizations, audit entries, notification keys, briefing settings, and queued bot responses for the chosen owner.

`edit CONTACT_ID` updates only fields supplied with `--name`, `--email`, `--org`, or `--notes`. `delete-interaction ID --confirm` and `delete-followup ID --confirm` remove one record only when it belongs to the selected `--user`.

Organizations and projects have owner-scoped catalog commands. A contact's existing `organization` text is preserved; adding or editing a contact with `--org` also adds that name to the owner's organization catalog. Renaming a catalog organization updates matching contact organization text. Deletion is confirmed and refused while contacts still reference an organization or project; unassign a project's contacts first.

```sh
.venv/bin/python app.py --db crm.sqlite3 --user me organization add ExampleCo --notes 'Synthetic account'
.venv/bin/python app.py --db crm.sqlite3 --user me organization list
.venv/bin/python app.py --db crm.sqlite3 --user me organization edit ExampleCo --new-name ExampleCo-West
.venv/bin/python app.py --db crm.sqlite3 --user me project add Launch --description 'Q4 launch'
.venv/bin/python app.py --db crm.sqlite3 --user me project assign 1 Launch
.venv/bin/python app.py --db crm.sqlite3 --user me project list
.venv/bin/python app.py --db crm.sqlite3 --user me project unassign 1 Launch
.venv/bin/python app.py --db crm.sqlite3 --user me project delete Launch --confirm
```

Tags can be listed with `tags [CONTACT_ID]`, assigned with `tag CONTACT_ID NAME`, and removed with `untag CONTACT_ID NAME`. The Telegram bot has matching `/tags`, `/tag`, and `/untag` commands.

Daily briefings are disabled until explicitly enabled for an owner. Configure timezone and quiet hours, then queue a briefing from that owner's local data without sending it:

```sh
.venv/bin/python app.py --db crm.sqlite3 --user me briefing-config --enable --timezone Europe/Moscow --quiet-start 22:00 --quiet-end 08:00 --stale-days 90
.venv/bin/python app.py --db crm.sqlite3 --user me dispatch-briefings
.venv/bin/python app.py --db crm.sqlite3 --user me delivery-status
```

The dispatcher only writes to the durable outbox. An already-running, explicitly configured Telegram bot delivers queued entries; it checks schedule/timezone/quiet hours after each poll cycle. The local date is the deduplication key. Definite failed delivery can be retried with `retry-delivery ID --confirm`, up to three attempts total; timeouts or server errors are marked `uncertain` and cannot be retried through this command because Telegram may already have accepted the message.

## Privacy and limits

- Contact details, notes, interaction history, and follow-ups are stored in SQLite on this machine. Protect the database, backups, and exports as personal data.
- Telegram polling requests only message updates. It sends an answer to the same chat for accepted private messages, including access-denied responses for non-allowlisted users who message the bot.
- Only numeric IDs in `CRM_ALLOWED_USER_IDS` can use CRM commands. Group messages are ignored. Keep the bot private and configure the allowlist before launch.
- The outbox uses at-most-once handling. Only Telegram API responses classified as definite failures can be manually retried. Network timeouts and server errors become `uncertain` and are never retried automatically because Telegram may already have accepted the message. Attempts and outcomes persist in SQLite.
- `/briefing` lists due or overdue follow-ups and contacts with no interaction for 90 days; `/briefing 30` changes the stale threshold. Opt-in daily delivery uses the persisted outbox and respects per-owner timezone/quiet hours. Hosted multi-user service, social scraping, and contact messaging are not implemented.

## Development

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m unittest discover -v
.venv/bin/ruff check .
```

CI runs local tests and Ruff on Python 3.11 and 3.13. Telegram behavior tests use synthetic updates and a fake API. A separate opt-in `getMe` probe is available for a real token check; CI has no Telegram secrets and does not contact Telegram.

See [docs/demo.md](docs/demo.md) for another synthetic data walkthrough. Run `app.py --help` or `telegram_bot.py --help` for command options.
