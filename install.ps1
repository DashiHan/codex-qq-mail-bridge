param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$mailerRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'qq_job_mailer')).Path
$skillsRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex\skills' }
$destination = Join-Path $skillsRoot 'qq-job-mail'
$source = Join-Path $PSScriptRoot 'skills\qq-job-mail'
$skill = [IO.File]::ReadAllText((Join-Path $source 'SKILL.md')).Replace('__MAILER_ROOT__', $mailerRoot)
$metadata = [IO.File]::ReadAllText((Join-Path $source 'agents\openai.yaml'))
foreach ($entry in @(@('SKILL.md', $skill), @('agents\openai.yaml', $metadata))) {
    $output = Join-Path $destination $entry[0]
    if ((Test-Path -LiteralPath $output) -and ([IO.File]::ReadAllText($output) -ne $entry[1])) {
        throw "An existing skill differs; review it before replacement: $output"
    }
}
if ($CheckOnly) { Write-Output "Checked: $destination; mail tool: $mailerRoot"; return }
New-Item -ItemType Directory -Force -Path (Join-Path $destination 'agents') | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $destination 'SKILL.md'), $skill, $utf8)
[IO.File]::WriteAllText((Join-Path $destination 'agents\openai.yaml'), $metadata, $utf8)
Write-Output "Installed personal skill: $destination"
Write-Output 'Keep this checkout in place. Open a new Codex chat and invoke $qq-job-mail. No email was sent.'
