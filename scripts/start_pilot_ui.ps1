param(
    [Parameter(Mandatory = $true)][string]$PilotRoot,
    [ValidateSet("farmer", "officer")][string]$Portal = "farmer",
    [int]$Port = 0
)
$ErrorActionPreference = 'Stop'
if ($Port -eq 0) { $Port = if ($Portal -eq "officer") { 8502 } else { 8501 } }
$sourceRoot = Split-Path -Parent $PSScriptRoot
$pilotPath = (Resolve-Path -LiteralPath $PilotRoot).Path
. (Join-Path $pilotPath 'pilot-env.ps1')

# Preserve the existing pilot configuration when changing the UI working directory.
if ($env:DATABASE_URL -like 'sqlite:///*') {
    $databasePath = $env:DATABASE_URL.Substring(10)
    if (-not [IO.Path]::IsPathRooted($databasePath)) {
        $env:DATABASE_URL = 'sqlite:///' + [IO.Path]::GetFullPath((Join-Path $pilotPath $databasePath))
    }
}
foreach ($setting in @('AGRIREACH_MEDIA_DIR', 'AGRIREACH_OUTBOX', 'AGRIREACH_RAINFALL_CACHE', 'AGRIREACH_STT_DIR', 'AGRIREACH_TTS_DIR')) {
    $settingValue = [Environment]::GetEnvironmentVariable($setting)
    if ($settingValue -and -not [IO.Path]::IsPathRooted($settingValue)) {
        [Environment]::SetEnvironmentVariable($setting, [IO.Path]::GetFullPath((Join-Path $pilotPath $settingValue)))
    }
}
$env:PYTHONPATH = Join-Path $sourceRoot 'src'
Remove-Item Env:AGRIREACH_UI_AUTH_DIAG -ErrorAction SilentlyContinue
Set-Location -LiteralPath $sourceRoot
$python = Join-Path $pilotPath '.venv\Scripts\python.exe'
# Windows PowerShell surfaces ordinary native stderr logs as ErrorRecords when
# the parent redirects streams. Streamlit logs startup there; it is not a failure.
$ErrorActionPreference = 'Continue'
& $python -m streamlit run (Join-Path $sourceRoot ("src\agrireach\{0}_ui.py" -f $Portal)) --server.address 127.0.0.1 --server.port $Port --server.headless true --browser.gatherUsageStats false
exit $LASTEXITCODE
