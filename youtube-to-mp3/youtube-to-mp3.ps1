[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [string]$Url,

    [Parameter()]
    [Nullable[int]]$Transpose = $null,

    [Parameter()]
    [string]$OutputDir = (Get-Location)
)

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Tool checks
# ---------------------------------------------------------------------------

$missing = @()

if (-not (python -m yt_dlp --version 2>&1 | Select-Object -First 1)) {
    $missing += '  yt-dlp  ->  pip install yt-dlp'
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    $missing += '  ffmpeg  ->  winget install ffmpeg  (or choco install ffmpeg)'
}

if ($missing.Count -gt 0) {
    $list = $missing -join [System.Environment]::NewLine
    Write-Error ("Missing required tools. Please install:" + [System.Environment]::NewLine + $list)
    exit 1
}

# ---------------------------------------------------------------------------
# Resolve output directory
# ---------------------------------------------------------------------------

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

# ---------------------------------------------------------------------------
# Step 1: get the video title (used as the final filename)
# ---------------------------------------------------------------------------

Write-Host 'Fetching video title...' -ForegroundColor Cyan
# Filter out ErrorRecord objects so yt-dlp warnings on stderr don't get mixed into the title
$title = python -m yt_dlp --get-title --no-playlist $Url 2>&1 |
    Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } |
    Select-Object -Last 1
if (-not $title -or $LASTEXITCODE -ne 0) {
    Write-Error 'Could not retrieve video title. Check the URL and your internet connection.'
    exit 1
}

# Sanitize title for use as a filename
$invalidChars = [System.IO.Path]::GetInvalidFileNameChars() -join ''
$title = $title -replace "[$([regex]::Escape($invalidChars))]", '_'
Write-Host "  Title: $title" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 2: download audio to a predictable temp filename
# ---------------------------------------------------------------------------

$tempBase = 'yt_tmp_' + [System.IO.Path]::GetRandomFileName().Replace('.', '')
$tempMp3  = Join-Path $OutputDir ($tempBase + '.mp3')

Write-Host 'Downloading audio...' -ForegroundColor Cyan
$outputTemplate = Join-Path $OutputDir ($tempBase + '.%(ext)s')
python -m yt_dlp `
    --extract-audio `
    --audio-format mp3 `
    --audio-quality 0 `
    --no-playlist `
    --output $outputTemplate `
    $Url

if ($LASTEXITCODE -ne 0 -or -not (Test-Path $tempMp3)) {
    Write-Error "Download failed - expected file not found: $tempMp3"
    exit 1
}
Write-Host '  Downloaded to temp file.' -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 3: normalize to 0 dB true peak + trim leading/trailing silence
# ---------------------------------------------------------------------------

Write-Host 'Normalizing and trimming silence...' -ForegroundColor Cyan

$processedMp3 = Join-Path $OutputDir ($tempBase + '.processed.mp3')

# First pass -- measure loudnorm stats
$stats = ffmpeg -i $tempMp3 -af 'loudnorm=I=-23:LRA=7:TP=0.0:print_format=json' -f null - 2>&1 | Out-String

$measuredI      = if ($stats -match '"input_i"\s*:\s*"([^"]+)"')      { $Matches[1] } else { '-23' }
$measuredTP     = if ($stats -match '"input_tp"\s*:\s*"([^"]+)"')     { $Matches[1] } else { '0'   }
$measuredLRA    = if ($stats -match '"input_lra"\s*:\s*"([^"]+)"')    { $Matches[1] } else { '7'   }
$measuredThresh = if ($stats -match '"input_thresh"\s*:\s*"([^"]+)"') { $Matches[1] } else { '-30' }

$audioFilter = (
    "loudnorm=I=-23:LRA=7:TP=0.0:" +
    "measured_I=${measuredI}:measured_LRA=${measuredLRA}:" +
    "measured_TP=${measuredTP}:measured_thresh=${measuredThresh}:linear=true," +
    "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-60dB:" +
    "stop_periods=-1:stop_duration=1:stop_threshold=-60dB"
)

ffmpeg -y -i $tempMp3 -af $audioFilter -codec:a libmp3lame -qscale:a 0 $processedMp3 2>&1 | Out-Null

if (-not (Test-Path $processedMp3)) {
    Remove-Item $tempMp3 -Force -ErrorAction SilentlyContinue
    Write-Error 'ffmpeg normalization failed.'
    exit 1
}

Remove-Item $tempMp3 -Force
Write-Host '  Normalized and silence trimmed.' -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 4: rename to final title-based filename
# ---------------------------------------------------------------------------

$finalMp3 = Join-Path $OutputDir ($title + '.mp3')
if (Test-Path $finalMp3) { Remove-Item $finalMp3 -Force }
Rename-Item $processedMp3 $finalMp3

Write-Host "  Saved: $finalMp3" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 5 (optional): create transposed copy
# ---------------------------------------------------------------------------

if ($null -ne $Transpose -and $Transpose -ne 0) {
    $suffix        = if ($Transpose -gt 0) { "(+$Transpose)" } else { "($Transpose)" }
    $transposedMp3 = Join-Path $OutputDir ($title + ' ' + $suffix + '.mp3')
    $pitchRatio    = [Math]::Round([Math]::Pow(2.0, $Transpose / 12.0), 6)

    Write-Host "Creating transposed copy ($suffix, pitch ratio $pitchRatio)..." -ForegroundColor Cyan

    ffmpeg -y -i $finalMp3 -af "rubberband=pitch=$pitchRatio" -codec:a libmp3lame -qscale:a 0 $transposedMp3 2>&1 | Out-Null

    if (Test-Path $transposedMp3) {
        Write-Host "  Saved: $transposedMp3" -ForegroundColor Green
    } else {
        Write-Warning 'Transposition failed - original file is still intact.'
    }
}

Write-Host 'Done.' -ForegroundColor Cyan
