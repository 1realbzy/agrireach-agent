<#
.SYNOPSIS
  OFFLINE FALLBACK demonstration launcher: API + farmer portal + officer portal on a
  brand-new disposable database. No language model, no judge model, no SMS/WhatsApp,
  no rainfall or source-page network calls.

.EXAMPLE
  .\scripts\start_demo_offline.ps1                 # start (prints the officer token once)
  .\scripts\start_demo_offline.ps1 -Stop -DemoRoot <folder printed at start>

  Farmer portal:  http://127.0.0.1:8501   Officer portal: http://127.0.0.1:8502
  API:            http://127.0.0.1:8000
#>
param(
    [string]$DemoRoot = (Join-Path $env:TEMP ('agrireach-demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))),
    [int]$ApiPort = 8000,
    [int]$FarmerPort = 8501,
    [int]$OfficerPort = 8502,
    [string]$OfficerName = 'Demo Officer',
    [string]$TokenFile = '',
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $DemoRoot 'pids.txt'

if ($Stop) {
    if (-not (Test-Path -LiteralPath $pidFile)) { throw "No pids.txt in $DemoRoot" }
    # /T also stops the child interpreter that the venv python.exe launcher starts on Windows.
    foreach ($id in Get-Content -LiteralPath $pidFile) { & taskkill.exe /T /F /PID ([int]$id) 2>&1 | Out-Null }
    Remove-Item -LiteralPath $pidFile
    Write-Output "Stopped demo services for $DemoRoot"
    exit 0
}

$python = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create the virtual environment first: py -3.13 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
}
# Never reuse a database: the demo must not touch pilot or historical records.
if (Test-Path -LiteralPath (Join-Path $DemoRoot 'demo.db')) { throw "$DemoRoot already has demo.db. Use a new folder." }
New-Item -ItemType Directory -Force -Path $DemoRoot, (Join-Path $DemoRoot 'logs') | Out-Null
$DemoRoot = (Resolve-Path -LiteralPath $DemoRoot).Path

# Remove every model and messaging credential from this process (children inherit it),
# so drafting falls back to the labelled offline stub and nothing can leave the PC.
foreach ($name in 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY', 'AGRIREACH_JUDGE_BASE_URL', 'AGRIREACH_JUDGE_API_KEY',
    'AGRIREACH_JUDGE_MODEL', 'OPENROUTER_API_KEY', 'AT_API_KEY', 'AT_USERNAME', 'MNOTIFY_API_KEY', 'WHATSAPP_ACCESS_TOKEN',
    'AGRIREACH_TTS', 'MNOTIFY_SMS_MODE') {
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
$env:PYTHONPATH = Join-Path $repo 'src'
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $DemoRoot 'demo.db')
$env:AGRIREACH_API = "http://127.0.0.1:$ApiPort"
$env:AGRIREACH_SIMULATOR = '0'
$env:SMS_ENABLED = '0'
$env:WHATSAPP_ENABLED = '0'
$env:AGRIREACH_SOURCE_CHECK = '0'
$env:AGRIREACH_RAINFALL = 'off'
$env:AGRIREACH_STT = 'none'
$env:AGRIREACH_MEDIA_DIR = Join-Path $DemoRoot 'media'
$env:AGRIREACH_OUTBOX = Join-Path $DemoRoot 'outbox'
$env:PYTHONIOENCODING = 'utf-8'

$token = (& $python (Join-Path $repo 'scripts\add_officer.py') $OfficerName | Select-Object -Last 1).Trim()
if (-not $token) { throw 'Officer registration failed.' }

$logs = Join-Path $DemoRoot 'logs'
$started = @()
$started += Start-Process -FilePath $python -WorkingDirectory $repo -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs 'api.out') -RedirectStandardError (Join-Path $logs 'api.err') `
    -ArgumentList '-m', 'uvicorn', 'agrireach.api:app', '--host', '127.0.0.1', '--port', "$ApiPort", '--ws', 'none', '--no-access-log'
foreach ($portal in @(@('farmer', $FarmerPort), @('officer', $OfficerPort))) {
    $started += Start-Process -FilePath $python -WorkingDirectory $repo -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "$($portal[0]).out") -RedirectStandardError (Join-Path $logs "$($portal[0]).err") `
        -ArgumentList '-m', 'streamlit', 'run', "src/agrireach/$($portal[0])_ui.py", '--server.address', '127.0.0.1',
        '--server.port', "$($portal[1])", '--server.headless', 'true', '--browser.gatherUsageStats', 'false'
}
$started | ForEach-Object { $_.Id } | Set-Content -LiteralPath $pidFile

$deadline = (Get-Date).AddSeconds(90)
$urls = @("http://127.0.0.1:$ApiPort/health", "http://127.0.0.1:$FarmerPort/_stcore/health", "http://127.0.0.1:$OfficerPort/_stcore/health")
foreach ($url in $urls) {
    while ($true) {
        try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $url).StatusCode -eq 200) { break } } catch { }
        if ((Get-Date) -gt $deadline) { throw "Service did not start: $url (see $logs)" }
        Start-Sleep -Seconds 1
    }
}
if ($TokenFile) { Set-Content -LiteralPath $TokenFile -Value $token -NoNewline }
Write-Output 'OFFLINE FALLBACK DEMO running (offline stub drafting; no model, judge, SMS or internet).'
Write-Output "Demo folder (disposable database and logs): $DemoRoot"
Write-Output "Farmer portal:  http://127.0.0.1:$FarmerPort"
Write-Output "Officer portal: http://127.0.0.1:$OfficerPort"
if (-not $TokenFile) { Write-Output "Officer sign-in token for '$OfficerName' (shown once, keep private):"; Write-Output $token }
Write-Output "Stop with: .\scripts\start_demo_offline.ps1 -Stop -DemoRoot '$DemoRoot'"
