#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "yt-dlp>=2024.1.0",
#   "requests>=2.31.0",
#   "python-dotenv>=1.0.0",
# ]
# ///
"""
yoto-add-track

Downloads a song from YouTube and adds it to an existing playlist on a Yoto MYO card.

Usage:
    uv run yoto_add_track.py <youtube-url> <playlist-name-or-id>

On first run you will be prompted to authorize via your Yoto account in a browser.
A refresh token is saved to token.json so subsequent runs are silent.

See README.md for full setup instructions.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yt_dlp
from dotenv import load_dotenv

YOTO_API_BASE = "https://api.yotoplay.com"
YOTO_AUTH_URL = "https://login.yotoplay.com/oauth/device/code"
YOTO_TOKEN_URL = "https://login.yotoplay.com/oauth/token"
YOTO_SCOPES = "family:library:view user:content:manage offline_access"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Token:
    access_token: str = None
    refresh_token: str = None
    token_type: str = "Bearer"
    scope: str = None
    valid_until: datetime = None


@dataclass
class Card:
    id: str
    title: str


class YotoManager:
    def __init__(self, client_id: str) -> None:
        if not client_id:
            raise ValueError("A client_id must be provided")
        self.client_id = client_id
        self.token: Token = None

    def set_refresh_token(self, refresh_token: str) -> None:
        self.token = Token(refresh_token=refresh_token)

    def check_and_refresh_token(self) -> Token:
        if self.token is None:
            raise ValueError("No token available, please authenticate first")
        needs_refresh = (
            self.token.access_token is None
            or self.token.valid_until is None
            or self.token.valid_until - timedelta(hours=1) <= datetime.now(timezone.utc)
        )
        if not needs_refresh:
            return self.token

        resp = requests.post(
            YOTO_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": self.token.refresh_token,
                "audience": YOTO_API_BASE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        body = resp.json()
        if body.get("error"):
            raise ValueError(
                f"Token refresh failed: {body.get('error_description', body['error'])}"
            )
        self.token = Token(
            access_token=body["access_token"],
            refresh_token=body["refresh_token"],
            token_type=body.get("token_type", "Bearer"),
            scope=self.token.scope,
            valid_until=datetime.now(timezone.utc) + timedelta(seconds=body["expires_in"]),
        )
        return self.token


# ---------------------------------------------------------------------------
# Config / auth
# ---------------------------------------------------------------------------

def load_config() -> str:
    """Load .env and return YOTO_CLIENT_ID, or exit with a helpful message."""
    load_dotenv(Path(__file__).parent / ".env")
    client_id = os.environ.get("YOTO_CLIENT_ID", "").strip()
    if not client_id:
        sys.exit(
            "Error: YOTO_CLIENT_ID is not set.\n"
            "Copy .env.example to .env and fill in your Client ID from yoto.dev."
        )
    return client_id


def authenticate(manager: YotoManager, token_file: Path) -> None:
    """Authenticate using a saved refresh token, or start a new device code flow."""
    if token_file.exists():
        saved = json.loads(token_file.read_text())
        refresh_token = saved.get("refresh_token", "")
        if refresh_token:
            print("Loading saved credentials...")
            try:
                manager.set_refresh_token(refresh_token)
                manager.check_and_refresh_token()
                _save_token(manager, token_file)
                return
            except Exception:
                print("Saved token is invalid or expired — re-authorizing...")

    manager.token = _device_code_flow(manager.client_id)
    _save_token(manager, token_file)
    print("Authorized. Token saved for future runs.\n")


def _device_code_flow(client_id: str) -> Token:
    """
    Run a device authorization flow requesting the scopes our script actually needs.
    The yoto-api library hardcodes scope='offline_access' in its own auth method,
    which produces a token that can't access content or library endpoints.
    """
    resp = requests.post(
        YOTO_AUTH_URL,
        data={"audience": YOTO_API_BASE, "client_id": client_id, "scope": YOTO_SCOPES},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    auth = resp.json()

    verification_url = (
        auth.get("verification_uri_complete")
        or auth.get("verification_uri", "https://login.yotoplay.com/activate")
    )
    user_code = auth.get("user_code", "")
    device_code = auth["device_code"]
    interval = int(auth.get("interval", 5))
    expires_in = int(auth.get("expires_in", 300))

    print(f"\nOpen this URL in your browser to authorize:\n  {verification_url}")
    if user_code and "user_code" not in verification_url:
        print(f"Enter code: {user_code}")
    print("\nWaiting for authorization...")

    deadline = datetime.now() + timedelta(seconds=expires_in)
    while datetime.now() < deadline:
        time.sleep(interval)
        token_resp = requests.post(
            YOTO_TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": client_id,
                "audience": YOTO_API_BASE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        body = token_resp.json()

        if token_resp.ok:
            return Token(
                access_token=body["access_token"],
                refresh_token=body["refresh_token"],
                token_type=body.get("token_type", "Bearer"),
                scope=body.get("scope", YOTO_SCOPES),
                valid_until=datetime.now(timezone.utc) + timedelta(seconds=body["expires_in"]),
            )

        error = body.get("error")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
        elif error == "expired_token":
            sys.exit("Authorization code expired. Please run again.")
        else:
            sys.exit(f"Authorization failed: {body.get('error_description', error)}")

    sys.exit("Authorization timed out. Please run again.")


def _save_token(manager: YotoManager, token_file: Path) -> None:
    token_file.write_text(json.dumps({"refresh_token": manager.token.refresh_token}))


def _auth_headers(manager: YotoManager, token_file: Path) -> dict:
    """Return auth headers, refreshing the access token if needed."""
    manager.check_and_refresh_token()
    _save_token(manager, token_file)
    return {
        "User-Agent": "Yoto/2.73 (com.yotoplay.Yoto; build:10405; iOS 17.4.0)",
        "Content-Type": "application/json",
        "Authorization": f"{manager.token.token_type} {manager.token.access_token}",
    }


# ---------------------------------------------------------------------------
# Card lookup
# ---------------------------------------------------------------------------

def find_card(manager: YotoManager, token_file: Path, name_or_id: str) -> Card:
    """Find a card by exact ID or case-insensitive title match."""
    resp = requests.get(
        f"{YOTO_API_BASE}/card/family/library",
        headers=_auth_headers(manager, token_file),
    )
    resp.raise_for_status()
    library = {
        item["cardId"]: Card(id=item["cardId"], title=item["card"]["title"])
        for item in resp.json().get("cards", [])
    }

    if name_or_id in library:
        return library[name_or_id]

    query = name_or_id.lower()
    matches = [c for c in library.values() if query in c.title.lower()]

    if not matches:
        available = "\n".join(f"  {c.id}: {c.title}" for c in library.values())
        sys.exit(f"No card matching '{name_or_id}'.\n\nAvailable cards:\n{available}")

    if len(matches) > 1:
        options = "\n".join(f"  {c.id}: {c.title}" for c in matches)
        sys.exit(
            f"Multiple cards match '{name_or_id}' — use the card ID to be specific:\n{options}"
        )

    return matches[0]


# ---------------------------------------------------------------------------
# YouTube download
# ---------------------------------------------------------------------------

def download_mp3(youtube_url: str, output_dir: Path) -> tuple[Path, str, int]:
    """Download YouTube audio as MP3. Returns (path, title, duration_seconds)."""
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)

    video_id = info.get("id", "audio")
    title = info.get("title", "Unknown")
    duration = int(info.get("duration") or 0)
    mp3_path = output_dir / f"{video_id}.mp3"

    if not mp3_path.exists():
        sys.exit(f"yt-dlp finished but expected file not found: {mp3_path}")

    return mp3_path, title, duration


# ---------------------------------------------------------------------------
# Yoto media upload
# ---------------------------------------------------------------------------

def upload_and_transcode(mp3_path: Path, manager: YotoManager, token_file: Path) -> dict:
    """
    Upload an MP3 to Yoto's media store and wait for transcoding.
    Returns the transcode result dict (transcodedSha256, duration, fileSize, channels, format).
    """
    # Step 1: get a signed upload URL.
    # We intentionally omit the sha256 deduplication hint so Yoto always
    # issues a fresh base64url job ID. When sha256 is passed and the file
    # already exists, Yoto returns the raw hex hash as uploadId and routes
    # the poll through different AWS infrastructure that rejects Bearer tokens.
    headers = _auth_headers(manager, token_file)
    resp = requests.get(
        f"{YOTO_API_BASE}/media/transcode/audio/uploadUrl",
        params={"filename": mp3_path.name},
        headers=headers,
    )
    resp.raise_for_status()
    upload_data = resp.json()["upload"]
    upload_id = upload_data["uploadId"]
    upload_url = upload_data.get("uploadUrl")

    if not upload_url:
        sys.exit("Yoto did not provide an upload URL. Try again.")

    # Step 2: upload to the signed S3 URL
    print(f"Uploading {mp3_path.name} ({mp3_path.stat().st_size // 1024} KB)...")
    with open(mp3_path, "rb") as f:
        put_resp = requests.put(upload_url, data=f, headers={"Content-Type": "audio/mpeg"})
        put_resp.raise_for_status()
    print("Upload complete. Waiting for Yoto to transcode...")

    # Step 3: poll for transcoding with exponential backoff (max ~5 min total)
    delay = 1.0
    elapsed = 0.0
    while elapsed < 300:
        time.sleep(delay)
        elapsed += delay
        poll_resp = requests.get(
            f"{YOTO_API_BASE}/media/upload/{upload_id}/transcoded",
            params={"loudnorm": "false"},
            headers=_auth_headers(manager, token_file),
        )
        if poll_resp.status_code == 202:
            delay = min(delay * 1.5, 15.0)
            continue
        poll_resp.raise_for_status()
        transcode_data = poll_resp.json().get("transcode", {})
        if transcode_data.get("transcodedSha256"):
            print("Transcoding complete.")
            info = transcode_data.get("transcodedInfo", {})
            return {
                "transcodedSha256": transcode_data["transcodedSha256"],
                "duration": info.get("duration", 0),
                "format": info.get("format", "opus"),
                "channels": info.get("channels", "stereo"),
                "fileSize": info.get("fileSize", 0),
            }
        delay = min(delay * 1.5, 15.0)

    sys.exit("Timed out waiting for Yoto to finish transcoding (5 min). Try again in a moment.")


# ---------------------------------------------------------------------------
# Playlist update
# ---------------------------------------------------------------------------

def add_track_to_card(
    card: Card,
    transcode: dict,
    track_title: str,
    manager: YotoManager,
    token_file: Path,
) -> None:
    """
    Fetch the card's current content and add the new track as a new chapter.

    The card structure used by the Yoto web interface is one chapter per song,
    each containing a single track. We match that structure here.
    """
    track_url = f"yoto:#{transcode['transcodedSha256']}"

    # Read current card content
    resp = requests.get(
        f"{YOTO_API_BASE}/content/{card.id}",
        params={"timezone": "UTC"},
        headers=_auth_headers(manager, token_file),
    )
    resp.raise_for_status()
    card_info = resp.json()["card"]
    content = card_info.get("content", {})
    chapters = content.get("chapters", [])

    # Guard: skip if this track is already present anywhere on the card
    for chapter in chapters:
        for track in chapter.get("tracks", []):
            if track.get("trackUrl") == track_url:
                print(f"'{track_title}' is already on this card — skipping.")
                return

    # Determine the next chapter key (zero-padded decimal, matching existing convention)
    # and the next overlay label (1-indexed position number shown on the card)
    key_nums = [int(c["key"]) for c in chapters if str(c.get("key", "")).isdigit()]
    new_chapter_key = str(max(key_nums, default=-1) + 1).zfill(2)

    label_nums = [int(c["overlayLabel"]) for c in chapters
                  if str(c.get("overlayLabel", "")).isdigit()]
    new_overlay_label = str(max(label_nums, default=0) + 1)

    new_chapter = {
        "key": new_chapter_key,
        "title": track_title,
        "overlayLabel": new_overlay_label,
        "duration": transcode.get("duration", 0),
        "fileSize": transcode.get("fileSize", 0),
        "tracks": [{
            "key": "01",
            "title": track_title,
            "overlayLabel": new_overlay_label,
            "trackUrl": track_url,
            "type": "audio",
            "format": transcode.get("format", "opus"),
            "duration": transcode.get("duration", 0),
            "fileSize": transcode.get("fileSize", 0),
            "channels": transcode.get("channels", "stereo"),
        }],
    }
    chapters.append(new_chapter)
    content["chapters"] = chapters

    payload = {
        "cardId": card.id,
        "title": card_info.get("title", ""),
        "content": content,
    }
    write_resp = requests.post(
        f"{YOTO_API_BASE}/content",
        json=payload,
        headers=_auth_headers(manager, token_file),
    )
    write_resp.raise_for_status()

    # Verify the track is visible in a fresh fetch
    verify_resp = requests.get(
        f"{YOTO_API_BASE}/content/{card.id}",
        params={"timezone": "UTC"},
        headers=_auth_headers(manager, token_file),
    )
    verify_resp.raise_for_status()
    verify_chapters = verify_resp.json()["card"].get("content", {}).get("chapters", [])
    for chapter in verify_chapters:
        for track in chapter.get("tracks", []):
            if track.get("trackUrl") == track_url:
                print(f"Added '{track_title}' to '{card_info.get('title', card.id)}' "
                      f"(position {chapter.get('overlayLabel', '?')}).")
                return
    print(f"Warning: could not verify '{track_title}' was added — check the Yoto web interface.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a YouTube song and add it to a Yoto MYO card playlist."
    )
    parser.add_argument("youtube_url", help="YouTube video URL")
    parser.add_argument(
        "playlist",
        help="Card title (partial, case-insensitive) or card ID (5-char alphanumeric)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download the MP3 locally but do not upload or modify the playlist",
    )
    parser.add_argument(
        "--token",
        metavar="FILE",
        default=None,
        help="Path to token.json (default: token.json next to this script)",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="Keep the downloaded MP3 in DIR instead of deleting it after upload",
    )
    args = parser.parse_args()

    client_id = load_config()
    token_file = Path(args.token) if args.token else Path(__file__).parent / "token.json"

    manager = YotoManager(client_id=client_id)
    authenticate(manager, token_file)

    card = find_card(manager, token_file, args.playlist)
    print(f"Target card: {card.title} ({card.id})")

    # Download into a temp dir (cleaned up automatically) unless --output-dir is set
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        _run(args, card, manager, token_file, output_dir, keep_mp3=True)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            _run(args, card, manager, token_file, Path(tmp), keep_mp3=False)


def _run(args, card: Card, manager: YotoManager, token_file: Path, output_dir: Path, keep_mp3: bool) -> None:
    print(f"Downloading audio from YouTube...")
    mp3_path, title, duration = download_mp3(args.youtube_url, output_dir)
    print(f"Downloaded: {title} ({duration}s)")

    if args.dry_run:
        print(f"\n[dry-run] Would add '{title}' to '{card.title}' ({card.id}).")
        if keep_mp3:
            print(f"[dry-run] MP3 saved at: {mp3_path}")
        return

    transcode = upload_and_transcode(mp3_path, manager, token_file)
    add_track_to_card(card, transcode, title, manager, token_file)

    if keep_mp3:
        print(f"MP3 kept at: {mp3_path}")


if __name__ == "__main__":
    main()
