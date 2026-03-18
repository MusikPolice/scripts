# Remove-EmptyFolders

A PowerShell script that recursively scans a directory and deletes any empty folders found within. Never deletes files.

## Usage

```powershell
# Delete empty folders under the current directory
.\Remove-EmptyFolders.ps1

# Delete empty folders under a specific path
.\Remove-EmptyFolders.ps1 -Root "C:\Some\Path"

# Dry run — print what would be deleted without removing anything
.\Remove-EmptyFolders.ps1 -Root "C:\Some\Path" -WhatIf
```

## Parameters

| Parameter | Description |
|---|---|
| `-Root` | Directory to scan. Defaults to the current directory (`.`). |
| `-WhatIf` | Dry run. Lists directories that would be deleted without removing them. |
