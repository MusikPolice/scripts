#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "google-api-python-client>=2.0.0",
#   "google-auth-httplib2>=0.1.0",
#   "google-auth-oauthlib>=0.5.0",
#   "python-dotenv>=1.0.0",
# ]
# ///
"""
Gmail Cleanup Tool

Permanently deletes:
  - Read inbox/archive emails older than DAYS_INBOX days (default: 90)
  - Sent emails older than DAYS_SENT days (default: 365)

Configuration lives in a .env file next to this script (copy .env.example).
CLI flags override .env values for one-off runs.

Quick start
-----------
1. Install uv (if needed):   curl -LsSf https://astral.sh/uv/install.sh | sh
2. Set up Google Cloud credentials (see --help for full steps).
3.  cp .env.example .env        # then edit thresholds to your liking
4.  uv run gmail_cleanup.py --dry-run
5.  uv run gmail_cleanup.py

   uv automatically creates an isolated virtual environment and installs
   dependencies the first time — nothing is installed into your system Python.
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv(Path(__file__).parent / ".env")

# Full mailbox access is required for permanent deletion.
SCOPES = ["https://mail.google.com/"]
BATCH_SIZE = 1000       # Gmail API hard limit for batchDelete
LIST_PAGE_SIZE = 500    # messages.list maxResults (API max)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_credentials(credentials_file: str, token_file: str) -> Credentials:
    creds = None

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing access token...")
            creds.refresh(Request())
        else:
            print("Opening browser for Gmail authorisation...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "w") as fh:
            fh.write(creds.to_json())
        print(f"Token saved to {token_file}\n")

    return creds


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------

def cutoff_date(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")


def inbox_query(days: int) -> str:
    """Read, unstarred emails in inbox/archive, excluding sent, drafts, spam, trash."""
    return (
        f"is:read before:{cutoff_date(days)} "
        "-is:starred -in:sent -in:drafts -in:spam -in:trash"
    )


def sent_query(days: int) -> str:
    """Unstarred emails in the Sent folder."""
    return f"in:sent before:{cutoff_date(days)} -is:starred"


def list_message_ids(service, query: str, label: str) -> list:
    """Return all message IDs matching *query*, printing progress to stderr."""
    ids = []
    page_token = None

    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": LIST_PAGE_SIZE}
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            result = service.users().messages().list(**kwargs).execute()
        except HttpError as e:
            print(f"\nAPI error while listing {label}: {e}")
            sys.exit(1)

        ids.extend(msg["id"] for msg in result.get("messages", []))
        page_token = result.get("nextPageToken")
        print(f"  [{label}] {len(ids):,} found so far...", end="\r", flush=True)

        if not page_token:
            break

    print(f"  [{label}] {len(ids):,} messages matched.          ")
    return ids


def batch_delete(service, message_ids: list, label: str, dry_run: bool) -> int:
    """Delete *message_ids* in chunks of BATCH_SIZE. Returns count processed."""
    total = len(message_ids)
    processed = 0

    for i in range(0, total, BATCH_SIZE):
        chunk = message_ids[i : i + BATCH_SIZE]
        end = min(i + BATCH_SIZE, total)

        if dry_run:
            print(f"  [{label}] [DRY RUN] Would delete {i + 1:,}–{end:,} of {total:,}")
        else:
            print(f"  [{label}] Deleting {i + 1:,}–{end:,} of {total:,}...", end="\r", flush=True)
            try:
                service.users().messages().batchDelete(
                    userId="me", body={"ids": chunk}
                ).execute()
            except HttpError as e:
                if e.resp.status == 429:
                    print(f"\n  [{label}] Rate limited — waiting 30 s then retrying...")
                    time.sleep(30)
                    service.users().messages().batchDelete(
                        userId="me", body={"ids": chunk}
                    ).execute()
                else:
                    print(f"\n  [{label}] API error: {e}")
                    print(f"  Stopped after {processed:,} deletions.")
                    sys.exit(1)

        processed += len(chunk)
        time.sleep(0.25)  # stay well inside the 250 quota-units/s limit

    if not dry_run:
        print(f"  [{label}] {processed:,} messages deleted.          ")
    return processed


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def env_int(key: str, default: int) -> int:
    val = os.environ.get(key, "").strip()
    if val.isdigit():
        return int(val)
    return default


SETUP_INSTRUCTIONS = """
Credentials setup (one-time)
-----------------------------
1. Go to https://console.cloud.google.com/ and create (or select) a project.
2. Enable the Gmail API:
     APIs & Services → Enable APIs → search "Gmail API" → Enable
3. Create OAuth credentials:
     APIs & Services → Credentials → Create Credentials → OAuth client ID
     Application type: Desktop app  →  Create  →  Download JSON
4. Save the downloaded file as  credentials.json  next to this script
   (or set CREDENTIALS_FILE in .env, or pass --credentials).
5. On first run the script opens your browser. Sign in and grant access.
   A token.json file is saved — you won't need to do this again.
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # .env-sourced defaults (already loaded at module level)
    default_days_inbox = env_int("DAYS_INBOX", 90)
    default_days_sent  = env_int("DAYS_SENT", 365)
    default_credentials = os.environ.get("CREDENTIALS_FILE", "credentials.json")
    default_token       = os.environ.get("TOKEN_FILE", "token.json")

    parser = argparse.ArgumentParser(
        description="Permanently delete old Gmail messages. Thresholds are read from .env.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=SETUP_INSTRUCTIONS,
    )
    parser.add_argument(
        "--days-inbox", type=int, default=default_days_inbox, metavar="N",
        help=f"Delete read inbox/archive emails older than N days (default: {default_days_inbox})",
    )
    parser.add_argument(
        "--days-sent", type=int, default=default_days_sent, metavar="N",
        help=f"Delete sent emails older than N days (default: {default_days_sent})",
    )
    parser.add_argument(
        "--credentials", default=default_credentials, metavar="FILE",
        help=f"Path to OAuth credentials JSON (default: {default_credentials})",
    )
    parser.add_argument(
        "--token", default=default_token, metavar="FILE",
        help=f"Path to store/read the auth token (default: {default_token})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count matching emails without deleting anything",
    )
    args = parser.parse_args()

    if not os.path.exists(args.credentials):
        print(f"Error: credentials file '{args.credentials}' not found.")
        print(SETUP_INSTRUCTIONS)
        sys.exit(1)

    groups = [
        ("inbox/archive", inbox_query(args.days_inbox), args.days_inbox),
        ("sent",          sent_query(args.days_sent),   args.days_sent),
    ]

    print("Gmail Cleanup Tool")
    print("=" * 44)
    for label, query, days in groups:
        print(f"  {label:<16}: older than {days} days  ({cutoff_date(days)})")
        print(f"  {'query':<16}: {query}")
    print(f"  {'mode':<16}: {'DRY RUN — nothing will be deleted' if args.dry_run else 'LIVE — emails will be permanently deleted'}")
    print()

    creds = get_credentials(args.credentials, args.token)
    service = build("gmail", "v1", credentials=creds)

    # --- Search phase ---
    print("Searching...")
    all_ids: dict[str, list] = {}
    for label, query, _ in groups:
        all_ids[label] = list_message_ids(service, query, label)
    print()

    total = sum(len(v) for v in all_ids.values())
    if total == 0:
        print("No matching messages found. Nothing to do.")
        return

    for label, ids in all_ids.items():
        print(f"  {label:<16}: {len(ids):,} messages")
    print(f"  {'TOTAL':<16}: {total:,} messages")
    print()

    # --- Confirmation ---
    if not args.dry_run:
        print(f"WARNING: This will PERMANENTLY delete {total:,} emails.")
        print("They will NOT go to Trash — this cannot be undone.\n")
        confirm = input("Type  yes  to proceed: ").strip().lower()
        if confirm != "yes":
            print("Aborted. No emails were deleted.")
            return
        print()

    # --- Delete phase ---
    grand_total = 0
    for label, ids in all_ids.items():
        if ids:
            grand_total += batch_delete(service, ids, label, dry_run=args.dry_run)

    print()
    if args.dry_run:
        print(f"Dry run complete. {grand_total:,} messages would be deleted.")
    else:
        print(f"Done. {grand_total:,} messages permanently deleted.")


if __name__ == "__main__":
    main()
