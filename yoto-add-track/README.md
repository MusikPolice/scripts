# yoto-add-track

Downloads a song from YouTube and adds it to an existing playlist on a [Yoto](https://yotoplay.com) MYO (Make Your Own) card.

**Typical workflow:** Your kid hears a song you're playing → you grab the YouTube URL → one command → it's on his Yoto.

```bash
uv run yoto_add_track.py <youtube-url> <playlist-name-or-id>
```

---

## Requirements

- [uv](https://docs.astral.sh/uv/) — manages Python version and dependencies, nothing installed into system Python
- [ffmpeg](https://ffmpeg.org/download.html) — required by yt-dlp to convert video audio to MP3
- A [Yoto developer account](https://yoto.dev/get-started/start-here/) — free, takes ~5 minutes to register and get a Client ID

### Install uv

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Install ffmpeg

```powershell
# Windows via winget
winget install ffmpeg
```

---

## Setup

### 1. Get a Yoto Client ID

Register at [yoto.dev/get-started/start-here/](https://yoto.dev/get-started/start-here/) to create a developer application and receive a **Client ID**. Full API reference is at [yoto.dev/api/](https://yoto.dev/api/).

When creating the application:
- **Callback URL:** enter `http://localhost:8080` — it is never called, but the form requires a value. The script uses the device authorization flow, which has no callback.
- **Scopes:** select exactly these three:

  | Scope | Purpose |
  |---|---|
  | `family:library:view` | List cards in your library (used to look up a playlist by name) |
  | `user:content:manage` | Read and write MYO card content, upload audio files |
  | `offline_access` | Allow the refresh token to work between runs without re-authorizing |

  Do not request device or family management scopes — the script does not need them.

You do not need a Client Secret; the device code flow used here is a public client flow.

### 2. Configure credentials

```powershell
cp .env.example .env
```

Edit `.env` and fill in your Client ID:

```dotenv
YOTO_CLIENT_ID=your_client_id_here
```

### 3. First run — authorize with Yoto

On first run, the script prints a URL and waits for you to authorize in a browser:

```
Open this URL in your browser to authorize:
  https://login.yotoplay.com/activate?user_code=XXXX-XXXX
Waiting for authorization...
Authorized. Token saved for future runs.
```

Open the URL in your browser, log in with your Yoto account, and enter the code. The script then saves a refresh token to `token.json` so subsequent runs are silent.

---

## Usage

```powershell
uv run yoto_add_track.py <youtube-url> <playlist-name-or-id>
```

### Examples

```powershell
# Add by playlist name (case-insensitive match against card title)
uv run yoto_add_track.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" "Kids Party Mix"

# Add by card ID (5-character alphanumeric, shown in the Yoto web interface URL)
uv run yoto_add_track.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" "aB3xY"
```

### What happens

1. YouTube URL is resolved and audio downloaded as MP3 via `yt-dlp`
2. The MP3 is uploaded to Yoto's media store (deduplicated by SHA-256 — re-uploading the same file is a no-op)
3. Yoto transcodes the file server-side; the script polls until transcoding completes
4. The existing playlist is fetched, the new track appended, and the full content object written back

### CLI flags

| Flag | Description |
|---|---|
| `--dry-run` | Download and transcode the MP3 locally, but do not upload or modify the playlist |
| `--token FILE` | Override the default `token.json` path |
| `--output-dir DIR` | Keep downloaded MP3 files in DIR instead of deleting after upload |

---

## How it works

### Pipeline

```
YouTube URL
    │
    ▼
yt-dlp + ffmpeg                   → temp .mp3 file
    │
    ▼
SHA-256 hash of .mp3
    │
    ▼
GET /media/transcode/audio/uploadUrl?sha256=<hash>
    │  returns: uploadId + signed S3 URL (null if file already on Yoto CDN)
    ▼
PUT <signedS3Url>                  → upload MP3 (skipped if already exists)
    │
    ▼
GET /media/transcode/audio/<uploadId>   (poll every 500ms, max 30 attempts)
    │  returns: transcodedSha256, duration, fileSize, channels, format
    ▼
GET /content/<cardId>              → fetch existing card (chapters + tracks)
    │
    ▼
Append new track to chapter list
    │
    ▼
POST /content                      → write updated card back to Yoto
```

### Authentication

Uses **OAuth 2.0 Device Authorization Flow** — suitable for CLI/headless use.

- Auth server: `https://login.yotoplay.com`
- Device code endpoint: `POST /oauth/device/code`
- Token endpoint: `POST /oauth/token`
- Required scope: `user:content:manage`
- Access tokens are short-lived JWTs; refresh tokens are single-use and automatically rotated

The `yoto-api` Python library (`cdnninja/yoto_api`) handles the auth flow and token refresh. Media upload and content creation are called directly against the REST API since the library does not wrap those endpoints.

### Data model

A Yoto **card** contains one or more **chapters**, each of which contains one or more **tracks**. For a flat music playlist, all tracks live in a single chapter.

```
Card
├── cardId        (5-char alphanumeric, e.g. "aB3xY")
├── title
└── content
    └── chapters[]
        ├── key   (unique within card)
        ├── title
        └── tracks[]
            ├── key
            ├── title
            ├── trackUrl  → "yoto:#<transcodedSha256>"
            ├── type      → "audio"
            ├── format    → "mp3"
            ├── duration  (seconds)
            ├── fileSize  (bytes)
            └── channels  (1 or 2)
```

### API base URL

```
https://api.yotoplay.com
```

All requests use `Authorization: Bearer <access_token>`.

### Key endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/oauth/device/code` | Start device code flow |
| `POST` | `/oauth/token` | Exchange code / refresh token |
| `GET` | `/content` | List all cards in library |
| `GET` | `/content/<cardId>` | Fetch full card (chapters + tracks) |
| `POST` | `/content` | Create or update a card |
| `GET` | `/media/transcode/audio/uploadUrl?sha256=<hash>` | Get signed S3 upload URL |
| `PUT` | `<signedS3Url>` | Upload MP3 to S3 |
| `GET` | `/media/transcode/audio/<uploadId>` | Poll for transcode completion |

### POST /content payload (update existing card)

```json
{
  "cardId": "aB3xY",
  "title": "Kids Party Mix",
  "content": {
    "playbackType": "linear",
    "chapters": [
      {
        "key": "1",
        "title": "Kids Party Mix",
        "tracks": [
          {
            "key": "1",
            "title": "Never Gonna Give You Up",
            "trackUrl": "yoto:#<transcodedSha256>",
            "type": "audio",
            "format": "mp3",
            "duration": 213,
            "fileSize": 8520000,
            "channels": 2
          }
        ]
      }
    ]
  }
}
```

To update: include `cardId`. To create: omit it and Yoto auto-assigns one.

### Limits

- Max 100 tracks per card
- Max 100 MB / 60 minutes per single track
- Max 500 MB / 5 hours total per card

---

## Files

```
yoto-add-track/
├── yoto_add_track.py   # main script (PEP 723 inline dependencies)
├── .env.example        # configuration template
├── .env                # your config (git-ignored)
└── token.json          # OAuth refresh token (git-ignored, created on first run)
```

---

## Dependencies

Declared inline in `yoto_add_track.py` via [PEP 723](https://peps.python.org/pep-0723/) so `uv run` installs them automatically:

| Package | Purpose |
|---------|---------|
| `yt-dlp` | Download YouTube audio |
| `yoto-api` | Yoto OAuth device code flow + library listing |
| `requests` | Direct REST calls for upload and content endpoints |
| `python-dotenv` | Load `.env` config |

---

## Implementation status

- [x] `yoto_add_track.py` — written, not yet tested against live API
- [x] `.env.example`
- [x] `.gitignore`

### What still needs testing

- **First-run auth flow**: `device_code_flow_start()` return shape not verified against live API — the script reads `verification_uri_complete`, `verification_uri`, and `user_code` defensively, but may need adjusting once we see the actual response.
- **`set_refresh_token` behaviour**: Not confirmed whether calling it triggers an immediate token exchange or just stores the value. The script calls `check_and_refresh_token()` immediately after to be safe.
- **`GET /content/<cardId>` response shape**: The script expects `content.chapters` to be an array of objects with a `tracks` array. If the live API returns a different structure, `add_track_to_card()` will need to be updated.
- **Track key convention**: The script uses 1-based integer strings (`"1"`, `"2"`, …), incrementing past the highest existing numeric key. This matches the Yoto API docs examples but hasn't been verified against a real card.
