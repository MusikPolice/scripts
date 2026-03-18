# Gmail Cleanup

Permanently deletes old emails from your Gmail account using the Gmail API.
Designed to reclaim storage and get a 20-year-old inbox under control.

Two groups are targeted independently, each with its own age threshold:

| Group | What gets deleted | Default threshold |
|---|---|---|
| **Inbox / Archive** | Read emails (not in Sent, Drafts, Spam, or Trash) | 90 days |
| **Sent** | Everything in the Sent folder | 365 days |

Deletions are **permanent** — emails bypass the Trash and are gone immediately.
A `--dry-run` flag lets you preview exactly what would be removed before committing.

---

## Requirements

- [uv](https://docs.astral.sh/uv/) — manages Python and dependencies in an isolated
  environment, nothing is installed into your system Python.
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) — used by the setup script.
- A Google account with Gmail.

### Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

---

## Setup

Run the setup script. It handles everything that can be automated (project creation,
API enabling) and then opens the exact Cloud Console pages for the two steps that
Google does not expose via any CLI or public API.

```bash
uv run setup.py
```

The script will:
1. Check that `gcloud` is installed and you're logged in
2. Create a GCP project (or let you reuse an existing one)
3. Enable the Gmail API on that project
4. Open the Cloud Console directly to the OAuth consent screen and credential
   creation pages, and link you to Google's own current documentation for those steps

When the console steps are done, download the credentials JSON and save it as
`credentials.json` next to `gmail_cleanup.py`.

The credentials page offers three types — you want **OAuth Client ID**, application
type **Desktop app**:
- *API keys* only grant access to public data, not a private mailbox.
- *Service accounts* can access Gmail but only via domain-wide delegation, which
  requires a paid Google Workspace organisation. They don't work with personal Gmail.
- *OAuth Client ID (Desktop app)* is the right choice. It triggers the browser
  sign-in flow where you grant access to your own account. The downloaded JSON
  contains a client ID and secret used to initiate that flow — your credentials
  never leave Google.

> **Why two steps still require the console:** Google has never exposed OAuth consent
> screen configuration or Desktop app client creation through any public API or CLI.
> The IAP-based workaround that existed was shut down in July 2025. The setup script
> gives you direct links rather than step-by-step UI instructions that go stale.

---

## Configuration

Copy the example config and edit it:

```bash
cp .env.example .env
```

`.env` options:

```dotenv
# Delete read inbox/archive emails older than this many days.
DAYS_INBOX=90

# Delete sent emails older than this many days.
DAYS_SENT=365

# Paths to OAuth files (relative to the script, or absolute).
CREDENTIALS_FILE=credentials.json
TOKEN_FILE=token.json
```

All options can also be overridden per-run with CLI flags (see below).

---

## Usage

**Always do a dry run first:**

```bash
uv run gmail_cleanup.py --dry-run
```

This searches Gmail and prints how many emails would be deleted in each group,
without touching anything.

On the **first run**, the script opens your browser to complete the OAuth flow and
saves a `token.json` so subsequent runs are silent.

**Live run:**

```bash
uv run gmail_cleanup.py
```

The script shows a per-group summary and asks you to type `yes` before deleting anything.

### CLI flags

| Flag | Description |
|---|---|
| `--dry-run` | Count matching emails, print batches, delete nothing |
| `--days-inbox N` | Override `DAYS_INBOX` for this run |
| `--days-sent N` | Override `DAYS_SENT` for this run |
| `--credentials FILE` | Override `CREDENTIALS_FILE` for this run |
| `--token FILE` | Override `TOKEN_FILE` for this run |

Examples:

```bash
# Preview with a wider sent window
uv run gmail_cleanup.py --dry-run --days-sent 730

# Run with a tighter inbox threshold just this once
uv run gmail_cleanup.py --days-inbox 30
```

### On Unix/macOS: run directly

```bash
chmod +x gmail_cleanup.py
./gmail_cleanup.py --dry-run
```

The shebang (`#!/usr/bin/env -S uv run`) handles everything.

---

## How it works

1. **Auth** — Loads or refreshes OAuth credentials. On first run, opens the
   browser. Saves a token for reuse.

2. **Search** — Calls `messages.list` with a Gmail search query for each group,
   paging through all results (500 per page) to collect message IDs.

   The queries used:
   - Inbox/archive: `is:read before:YYYY/MM/DD -in:sent -in:drafts -in:spam -in:trash`
   - Sent: `in:sent before:YYYY/MM/DD`

3. **Confirm** — Shows a per-group and total count, then prompts for `yes`
   before proceeding (skipped in dry-run mode).

4. **Delete** — Calls `messages.batchDelete` with up to 1,000 IDs per request
   (the API's hard limit). Pauses 250 ms between batches to stay within Gmail's
   quota. If a 429 rate-limit error is returned, waits 30 seconds and retries
   once before aborting.

Deletion is **permanent** — `batchDelete` bypasses the Trash entirely. This is
intentional: moving to Trash wouldn't free storage until the Trash is emptied,
and still leaves the emails available in the interim.

---

## What is NOT deleted

- **Unread inbox/archive emails** — only `is:read` messages are targeted.
- **Drafts** — always excluded.
- **Spam and Trash** — excluded to avoid double-counting.
- **Starred emails** — always excluded. Star something to protect it.

---

## Files

```
gmail-cleanup/
├── gmail_cleanup.py   # the main script (dependencies declared inline via PEP 723)
├── setup.py           # one-time setup helper (gcloud + console URLs)
├── .env.example       # configuration template
├── .env               # your config (git-ignored)
├── credentials.json   # OAuth client secret (git-ignored, downloaded from console)
└── token.json         # OAuth access token (git-ignored, created on first run)
```

`credentials.json` and `token.json` contain sensitive auth material — do not
commit them. They are covered by `.gitignore`.
