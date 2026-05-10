# heic-to-jpg

Recursively converts HEIC photos (shot on iPhone) to JPG. Writes each JPG alongside its source file, then deletes the original HEIC after a confirmed successful conversion. Skips files where a JPG already exists. Supports `-WhatIf` for a dry run.

## Quick Start

```powershell
.\heic-to-jpg.ps1 -SourceFolder "D:\Pictures to Import\Jon"
```

## Requirements

- **ImageMagick** — handles HEIC decoding and JPG encoding.

  ```powershell
  # winget
  winget install ImageMagick.ImageMagick

  # Chocolatey
  choco install imagemagick

  # Manual download
  # https://imagemagick.org/script/download.php#windows
  ```

  After installing, restart your terminal so `magick` is on your PATH.

## Usage

```powershell
.\heic-to-jpg.ps1 [-SourceFolder] <string> [-Quality <int>] [-WhatIf]
```

| Parameter       | Required | Default | Description                                                  |
|-----------------|----------|---------|--------------------------------------------------------------|
| `-SourceFolder` | Yes      | —       | Root folder to scan. All subdirectories are included.        |
| `-Quality`      | No       | `95`    | JPG quality, 1–100. Higher values mean larger files.         |
| `-WhatIf`       | No       | —       | Preview what would be converted without making any changes.  |

## Notes

- The script validates that ImageMagick is available before doing any work, and prints install instructions if it isn't.
- A JPG is only written if one doesn't already exist at the target path. Existing JPGs are never overwritten.
- The original HEIC is deleted only after the JPG has been confirmed to exist on disk. A failed conversion leaves the source file untouched.
- This script is intentionally silent about folder organization — use a separate tool (e.g. [Elodie](https://github.com/jmathai/elodie)) to import and sort the resulting JPGs into your archive.
