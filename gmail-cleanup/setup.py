#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Gmail Cleanup — one-time setup helper

Automates everything that can be automated via gcloud:
  - Checks gcloud is installed and authenticated
  - Creates a GCP project (or reuses one you choose)
  - Enables the Gmail API

Then opens the exact Cloud Console URLs for the two steps that Google
does not expose via any CLI or public API:
  - OAuth consent screen configuration
  - Desktop app OAuth client creation

Run with:  uv run setup.py
"""

import json
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Resolve gcloud once at startup. On Windows it's installed as gcloud.cmd and
# subprocess won't find it by the bare name "gcloud" without shell=True.
# shutil.which respects PATHEXT and returns the full path including extension.
GCLOUD = shutil.which("gcloud") or shutil.which("gcloud.cmd")


def run(cmd: list[str], check=True, capture=False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )


def run_json(cmd: list[str]) -> object:
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def gcloud(*args) -> list[str]:
    """Build a gcloud command using the resolved executable path."""
    return [GCLOUD, *args]


def require_gcloud():
    if not GCLOUD:
        print("ERROR: gcloud not found.")
        print("Install the Google Cloud SDK: https://cloud.google.com/sdk/docs/install")
        sys.exit(1)


def get_active_account() -> str | None:
    try:
        result = run_json(gcloud("config", "get-value", "account", "--format=json"))
        return result if isinstance(result, str) and result else None
    except Exception:
        return None


def list_projects() -> list[dict]:
    try:
        return run_json(gcloud("projects", "list", "--format=json"))
    except Exception:
        return []


def prompt(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer or default


def confirm(question: str) -> bool:
    return input(f"{question} [y/N]: ").strip().lower() == "y"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_auth():
    print("\n── Step 1: gcloud authentication ──")
    account = get_active_account()
    if account:
        print(f"  Logged in as: {account}")
        if not confirm("  Use this account?"):
            run(gcloud("auth", "login"))
    else:
        print("  No active account found.")
        run(gcloud("auth", "login"))


def step_project() -> str:
    print("\n── Step 2: GCP project ──")
    projects = list_projects()

    if projects:
        print("  Existing projects:")
        for p in projects:
            print(f"    {p['projectId']}")

    choice = prompt(
        "  Enter an existing project ID to reuse, or a new ID to create",
    )
    if not choice:
        print("  Project ID is required.")
        sys.exit(1)

    existing_ids = {p["projectId"] for p in projects}
    if choice in existing_ids:
        print(f"  Using existing project: {choice}")
    else:
        print(f"  Creating project: {choice}")
        run(gcloud("projects", "create", choice, f"--name={choice}"))
        print(f"  Project created.")

    run(gcloud("config", "set", "project", choice))
    return choice


def step_enable_api(project_id: str):
    print("\n── Step 3: Enable Gmail API ──")
    print(f"  Enabling gmail.googleapis.com on {project_id}...")
    run(gcloud("services", "enable", "gmail.googleapis.com",
               f"--project={project_id}"))
    print("  Gmail API enabled.")


def step_console_urls(project_id: str):
    print("\n── Steps 4 & 5: OAuth consent screen + credentials ──")
    print()
    print("  Google does not expose these steps via any CLI or public API.")
    print("  You need to complete them in the Cloud Console — two pages, a few clicks each.")
    print()

    consent_url = (
        f"https://console.cloud.google.com/apis/credentials/consent"
        f"?project={project_id}"
    )
    creds_url = (
        f"https://console.cloud.google.com/apis/credentials/oauthclient"
        f"?project={project_id}"
    )

    print(f"  STEP 4 — OAuth consent screen:")
    print(f"  {consent_url}")
    print()
    print(f"  STEP 5 — Create OAuth client ID:")
    print(f"  {creds_url}")
    print()

    if confirm("  Open both URLs in your browser now?"):
        webbrowser.open(consent_url)
        webbrowser.open(creds_url)

    print()
    print("  The credentials page offers three types — you want:")
    print("    OAuth Client ID  →  Desktop app")
    print()
    print("  (API keys only cover public data; service accounts require a paid")
    print("  Google Workspace org and don't work with personal Gmail.)")
    print()
    print("  Full details in Google's own current docs:")
    print("  https://developers.google.com/workspace/guides/create-credentials")
    print()
    print("  When done:")
    print("  - Save the downloaded JSON as  credentials.json  next to gmail_cleanup.py")
    print("  - Copy .env.example to .env and adjust thresholds if needed")
    print("  - Run:  uv run gmail_cleanup.py --dry-run")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Gmail Cleanup — setup")
    print("=" * 44)
    print("This script handles everything automatable via gcloud, then")
    print("opens the Cloud Console for the two steps Google doesn't expose via CLI.")

    require_gcloud()
    step_auth()
    project_id = step_project()
    step_enable_api(project_id)
    step_console_urls(project_id)

    print("\nSetup complete. Come back here once you have credentials.json.")


if __name__ == "__main__":
    main()
