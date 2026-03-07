param(
    [string]$Root = ".",
    [switch]$WhatIf
)

Write-Host "Scanning for empty directories under: $Root"
Write-Host ""

# Get all directories, deepest first
$dirs = Get-ChildItem -Path $Root -Directory -Recurse |
        Sort-Object { $_.FullName.Split('\').Count } -Descending

foreach ($dir in $dirs) {

    # Check for any files inside this directory (recursively)
    $fileCount = Get-ChildItem -Path $dir.FullName -File -Recurse -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count

    # Check for any subdirectories inside this directory (recursively)
    $subDirCount = Get-ChildItem -Path $dir.FullName -Directory -Recurse -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count

    if ($fileCount -eq 0 -and $subDirCount -eq 0) {
        Write-Host "Deleting empty directory: $($dir.FullName)"
        if (-not $WhatIf) {
            Remove-Item -LiteralPath $dir.FullName -Force -Recurse
        }
    }
}