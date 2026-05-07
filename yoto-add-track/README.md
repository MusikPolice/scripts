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
2. The MP3 is uploaded to Yoto's media store via a pre-signed S3 URL
3. Yoto transcodes the file server-side (to Opus); the script polls with exponential backoff until transcoding completes
4. The existing card is fetched, a new chapter containing the new track is appended, and the updated card is written back
5. The card is re-fetched to verify the track landed correctly

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
GET /media/transcode/audio/uploadUrl?filename=<name>
    │  returns: uploadId (base64url) + signed S3 URL
    ▼
PUT <signedS3Url>                  → upload MP3
    │
    ▼
GET /media/upload/<uploadId>/transcoded   (exponential backoff, max 5 min)
    │  202 = in progress; 200 = done
    │  returns: { transcode: { transcodedSha256, transcodedInfo: { duration, fileSize, channels, format } } }
    ▼
GET /content/<cardId>              → fetch existing card (chapters + tracks)
    │
    ▼
Append new chapter (one chapter per song) to chapters list
    │
    ▼
POST /content                      → write updated card back to Yoto
    │
    ▼
GET /content/<cardId>              → verify track is present
```

### Authentication

Uses **OAuth 2.0 Device Authorization Flow** — suitable for CLI/headless use.

- Auth server: `https://login.yotoplay.com`
- Device code endpoint: `POST /oauth/device/code`
- Token endpoint: `POST /oauth/token`
- Required scopes: `family:library:view user:content:manage offline_access`
- Access tokens are short-lived JWTs; refresh tokens are single-use and automatically rotated

The `yoto-api` Python library (`cdnninja/yoto_api`) is used for token refresh and library listing. The script implements its own device code flow rather than using the library's `device_code_flow_start()` method, because the library hardcodes `scope: "offline_access"` in its auth request — which produces a token that cannot access content or library endpoints. Media upload and content creation are called directly against the REST API since the library does not wrap those endpoints.

### Data model

A Yoto **card** contains one or more **chapters**, each of which contains one or more **tracks**. The Yoto web interface uses one chapter per song, each containing a single track. This script matches that structure.

Chapter keys are zero-padded decimal strings (`"00"`, `"01"`, …). The `overlayLabel` is the 1-indexed position number displayed on the physical card (`"1"`, `"2"`, …).

```
Card
├── cardId           (5-char alphanumeric, e.g. "aB3xY")
├── title
└── content
    └── chapters[]   (one chapter per song)
        ├── key          (zero-padded decimal: "00", "01", …)
        ├── title
        ├── overlayLabel (1-indexed position: "1", "2", …)
        ├── duration     (seconds)
        ├── fileSize     (bytes)
        └── tracks[]     (one track per chapter)
            ├── key          → "01"
            ├── title
            ├── overlayLabel (matches chapter overlayLabel)
            ├── trackUrl     → "yoto:#<transcodedSha256>"
            ├── type         → "audio"
            ├── format       → "opus"
            ├── duration     (seconds)
            ├── fileSize     (bytes)
            └── channels     → "stereo" or "mono"
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
| `GET` | `/media/transcode/audio/uploadUrl?filename=<name>` | Get signed S3 upload URL + uploadId |
| `PUT` | `<signedS3Url>` | Upload MP3 to S3 |
| `GET` | `/media/upload/<uploadId>/transcoded` | Poll for transcode completion (202 = pending, 200 = done) |

### POST /content payload (update existing card)

One chapter per song. The full chapters array (existing + new) is sent each time.

```json
{
  "cardId": "aB3xY",
  "title": "Kids Party Mix",
  "content": {
    "chapters": [
      {
        "key": "00",
        "title": "Song One",
        "overlayLabel": "1",
        "duration": 200,
        "fileSize": 3200000,
        "tracks": [
          {
            "key": "01",
            "title": "Song One",
            "overlayLabel": "1",
            "trackUrl": "yoto:#<transcodedSha256>",
            "type": "audio",
            "format": "opus",
            "duration": 200,
            "fileSize": 3200000,
            "channels": "stereo"
          }
        ]
      },
      {
        "key": "01",
        "title": "Never Gonna Give You Up",
        "overlayLabel": "2",
        "duration": 213,
        "fileSize": 3410000,
        "tracks": [
          {
            "key": "01",
            "title": "Never Gonna Give You Up",
            "overlayLabel": "2",
            "trackUrl": "yoto:#<transcodedSha256>",
            "type": "audio",
            "format": "opus",
            "duration": 213,
            "fileSize": 3410000,
            "channels": "stereo"
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

- [x] `yoto_add_track.py` — written and tested against live API
- [x] `.env.example`
- [x] `.gitignore`

### Notes from live testing

- **Auth flow**: `verification_uri_complete` is returned by the Yoto device code endpoint and includes the user code embedded in the URL. The script uses it directly if present, falling back to `verification_uri` + separate `user_code` display.
- **`set_refresh_token` behaviour**: Sets `manager.token` to a `Token` with only the refresh_token field populated (access_token is None). `check_and_refresh_token()` detects the missing access token and calls `api.refresh_token()` to exchange it.
- **Upload URL endpoint**: Pass `filename=<name>` (not `sha256=<hash>`). When sha256 is passed and the file already exists on the CDN, Yoto returns the raw hex hash as the uploadId, which routes through different AWS infrastructure that rejects Bearer tokens on the poll endpoint.
- **Poll endpoint**: `GET /media/upload/<uploadId>/transcoded` (not `/media/transcode/audio/<uploadId>`). Returns 202 while transcoding, 200 when complete. Transcoded metadata is at `response["transcode"]["transcodedInfo"]`.
- **Card structure**: One chapter per song, each chapter has exactly one track. Chapter keys are zero-padded decimals (`"00"`, `"01"`, …); `overlayLabel` is the 1-indexed human-visible position number.
- **`channels` field**: Must be the string `"stereo"` or `"mono"`, not an integer.
