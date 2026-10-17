param([Parameter(ValueFromRemainingArguments=$true)][string[]]$MailerArgs)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$venv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venv) { & $venv "$PSScriptRoot\mailer.py" @MailerArgs; exit $LASTEXITCODE }
$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) { & $launcher.Source -3 "$PSScriptRoot\mailer.py" @MailerArgs; exit $LASTEXITCODE }
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python -and $python.Source -notmatch 'WindowsApps') { & $python.Source "$PSScriptRoot\mailer.py" @MailerArgs; exit $LASTEXITCODE }
throw 'Install Python 3.10+ or create qq_job_mailer/.venv first.'
