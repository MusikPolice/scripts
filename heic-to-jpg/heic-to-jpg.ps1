[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory, Position = 0)]
    [string]$SourceFolder,

    [Parameter()]
    [ValidateRange(1, 100)]
    [int]$Quality = 95
)

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

Write-Host "Checking dependencies..." -ForegroundColor Cyan

if (!(Get-Command magick -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Warning "ImageMagick is not installed or not on your PATH."
    Write-Host ""
    Write-Host "Install it using one of the following methods:"
    Write-Host "  winget:       winget install ImageMagick.ImageMagick"
    Write-Host "  Chocolatey:   choco install imagemagick"
    Write-Host "  Manually:     https://imagemagick.org/script/download.php#windows"
    Write-Host ""
    Write-Host "After installing, restart your terminal and run this script again."
    exit 1
}

Write-Host "  imagemagick ... " -NoNewline
Write-Host "OK" -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# Discover files
# ---------------------------------------------------------------------------

Write-Host "Scanning for HEIC files in $SourceFolder ..." -ForegroundColor Cyan

if (!(Test-Path $SourceFolder)) {
    Write-Error "Source folder not found: $SourceFolder"
    exit 1
}

$files = @(Get-ChildItem -Path $SourceFolder -Filter *.heic -Recurse)
$total = $files.Count

if ($total -eq 0) {
    Write-Host "No HEIC files found. Nothing to do." -ForegroundColor Yellow
    exit 0
}

Write-Host "Found " -NoNewline
Write-Host $total -NoNewline -ForegroundColor Cyan
Write-Host " HEIC file(s) to process."
Write-Host ""

# ---------------------------------------------------------------------------
# Convert
# ---------------------------------------------------------------------------

$converted = 0
$skipped   = 0
$failed    = 0
$index     = 0

foreach ($file in $files) {
    $index++
    $sourceFile = $file.FullName
    $targetFile = Join-Path $file.DirectoryName "$($file.BaseName).jpg"
    $remaining  = $total - $index
    $prefix     = "[$index/$total]"

    if (Test-Path $targetFile) {
        Write-Host "$prefix " -NoNewline
        Write-Host "Skipped  " -NoNewline -ForegroundColor Yellow
        Write-Host "$($file.Name) (JPG already exists)"
        $skipped++
        continue
    }

    Write-Host "$prefix " -NoNewline
    Write-Host "Converting" -NoNewline -ForegroundColor Cyan
    Write-Host " $($file.Name) ..." -NoNewline

    if ($PSCmdlet.ShouldProcess($sourceFile, "Convert to JPG and delete original")) {
        magick -quality $Quality "$sourceFile" "$targetFile"

        if ($LASTEXITCODE -ne 0 -or !(Test-Path $targetFile)) {
            Write-Host " " -NoNewline
            Write-Host "FAILED" -ForegroundColor Red
            Write-Warning "magick returned an error for: $sourceFile"
            $failed++
            continue
        }

        Remove-Item -Path $sourceFile
        Write-Host " " -NoNewline
        Write-Host "done" -NoNewline -ForegroundColor Green
        Write-Host "  ($remaining remaining)"
        $converted++
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "----------------------------------------"
Write-Host "Converted : " -NoNewline; Write-Host $converted -ForegroundColor Green
Write-Host "Skipped   : " -NoNewline; Write-Host "$skipped  (JPG already existed)" -ForegroundColor Yellow
Write-Host "Failed    : " -NoNewline; Write-Host $failed -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "White" })
Write-Host "----------------------------------------"

if ($failed -gt 0) {
    Write-Host ""
    Write-Warning "$failed file(s) could not be converted. The original HEIC files have been left in place."
}
