# scripts
Useful scripts for one-off jobs that might come in handy at a later date

## Remove-EmptyFolders.ps1
A powershell script that recursively inspects the provided `-Root` directory, deleting any empty directories found within. Never deletes files. Pass the `-WhatIf` flag to do a dry run that outputs directories that _would_ be deleted if the flag were not present.
