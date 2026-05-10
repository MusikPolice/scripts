# youtube-to-mp3

Downloads audio from a YouTube video, normalizes the volume to 0 dB true peak, trims silence from the start and end, and saves it as an MP3 named after the video title. Optionally creates a pitch-shifted copy transposed by a given number of semitones — useful for cover bands that play a song in a different key.

```powershell
.\youtube-to-mp3.ps1 <youtube-url> [--Transpose <semitones>] [--OutputDir <path>]
```

---

## Requirements

- [Python](https://www.python.org/downloads/) with **yt-dlp** installed
- [ffmpeg](https://ffmpeg.org/download.html) compiled with **librubberband** (required for `--Transpose`)

### Install yt-dlp

```powershell
pip install yt-dlp
```

### Install ffmpeg

```powershell
# via Chocolatey (includes librubberband)
choco install ffmpeg

# via winget
winget install ffmpeg
```

> **Note:** The `--Transpose` flag requires ffmpeg to be compiled with `librubberband`. The Chocolatey build includes it. Run `ffmpeg -filters 2>&1 | Select-String rubberband` to verify.

---

## Usage

```powershell
.\youtube-to-mp3.ps1 <youtube-url> [--Transpose <semitones>] [--OutputDir <path>]
```

### Parameters

| Parameter | Required | Description |
|---|---|---|
| `<youtube-url>` | Yes | URL of the YouTube video to download |
| `--Transpose` | No | Number of semitones to transpose (positive = up, negative = down). Creates a second file alongside the original with a `(+N)` or `(-N)` suffix. |
| `--OutputDir` | No | Directory to save files into. Defaults to the current working directory. |

### Examples

```powershell
# Download and process only
.\youtube-to-mp3.ps1 "https://www.youtube.com/watch?v=AIOAlaACuv4"

# Download and create a copy transposed up 2 semitones
.\youtube-to-mp3.ps1 "https://www.youtube.com/watch?v=AIOAlaACuv4" --Transpose 2

# Download, transpose down 1 semitone, save to a specific directory
.\youtube-to-mp3.ps1 "https://www.youtube.com/watch?v=AIOAlaACuv4" --Transpose -1 --OutputDir "D:\Music\Covers"
```

Given a video titled *Tracy Chapman - Fast Car*, `--Transpose 2` produces two files:

```
Tracy Chapman - Fast Car.mp3
Tracy Chapman - Fast Car (+2).mp3
```

---

## What it does

1. **Checks** that `yt-dlp` and `ffmpeg` are installed, and exits with a helpful message if either is missing.
2. **Fetches** the video title, which becomes the base filename.
3. **Downloads** the best available audio stream and converts it to MP3 via yt-dlp.
4. **Normalizes** the audio to 0 dB true peak using ffmpeg's two-pass `loudnorm` filter (linear mode, target integrated loudness −23 LUFS).
5. **Trims** silence from the start and end using ffmpeg's `silenceremove` filter.
6. **Saves** the processed file as `<title>.mp3` in the output directory.
7. **Transposes** (if `--Transpose` is specified): creates a second copy pitch-shifted by the requested semitones using the `rubberband` filter, which adjusts pitch without changing tempo. The copy is saved as `<title> (+N).mp3` or `<title> (-N).mp3`.

### Pitch shifting

The rubberband filter changes pitch while preserving tempo — equivalent to using a capo on a guitar or transposing on a keyboard. The pitch ratio applied is `2^(n/12)` per semitone:

| Semitones | Ratio |
|---|---|
| +1 | 1.059463 |
| +2 | 1.122462 |
| +3 | 1.189207 |
| −1 | 0.943874 |
| −2 | 0.890899 |
