# Starts the app on this computer and keeps it up to date with GitHub.
#
#   Double-click start.bat (Windows), or run:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
#
# It pulls the latest code, installs what changed, opens the backend and the frontend in their own
# windows and opens the browser. Then this window checks GitHub every minute. Code changes reload by
# themselves (the dev servers watch their files); when dependencies change, it restarts the servers.
# Works in Windows PowerShell 5.1 and PowerShell 7.

param([int]$EverySeconds = 60)

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$Shell = (Get-Process -Id $PID).Path  # start the servers in the same kind of PowerShell
$Servers = @{}

function Say($text, $colour = 'Gray') { Write-Host "[$(Get-Date -Format HH:mm)] $text" -ForegroundColor $colour }

function Stop-WithMessage($text) {
    Write-Host $text -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

function Require($command, $hint) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { Stop-WithMessage "$command isn't installed. $hint" }
}

function Test-Port($port) {
    try {
        $client = New-Object Net.Sockets.TcpClient
        $client.Connect('127.0.0.1', $port)
        $client.Close()
        return $true
    } catch { return $false }
}

# Pulls from GitHub. Returns the files that changed (none if already up to date or the pull failed).
function Update-Code {
    $before = (git rev-parse HEAD).Trim()
    git pull --ff-only --quiet | Out-Host  # keep git's output out of the return value
    if ($LASTEXITCODE -ne 0) {
        Say "Couldn't get the latest version (no network, or files edited on this computer). Carrying on with what you have." 'Yellow'
        return @()
    }
    $after = (git rev-parse HEAD).Trim()
    if ($before -eq $after) { return @() }
    return @(git diff --name-only $before $after)
}

function Test-FrontendStale {
    $marker = Join-Path $Root 'frontend/node_modules/.package-lock.json'
    if (-not (Test-Path $marker)) { return $true }
    return (Get-Item (Join-Path $Root 'frontend/package-lock.json')).LastWriteTime -gt (Get-Item $marker -Force).LastWriteTime
}

function Install-Backend {
    Say 'Installing backend packages...'
    Push-Location (Join-Path $Root 'backend'); uv sync; Pop-Location
}

function Install-Frontend {
    Say 'Installing frontend packages...'
    Push-Location (Join-Path $Root 'frontend'); npm install --no-audit --no-fund; Pop-Location
}

function Start-Server($name, $folder, $command, $port) {
    if (Test-Port $port) {
        Say "The $name is already running on port $port; leaving it as it is." 'DarkGray'
        return
    }
    $title = "`$Host.UI.RawUI.WindowTitle = 'council $name'"
    $Servers[$name] = Start-Process $Shell -PassThru -WorkingDirectory (Join-Path $Root $folder) `
        -ArgumentList '-NoExit', '-NoProfile', '-Command', "$title; $command"
    Say "Started the $name (its own window)."
}

function Start-Servers {
    Start-Server 'backend' 'backend' 'uv run uvicorn app.main:app --reload --port 8000' 8000
    Start-Server 'frontend' 'frontend' 'npm run dev' 3000
}

function Stop-Servers {
    foreach ($name in @($Servers.Keys)) {
        # /T stops the whole tree: the window and the server running in it.
        taskkill /PID $Servers[$name].Id /T /F | Out-Null
        $Servers.Remove($name)
    }
    Start-Sleep -Seconds 2
}

# ---------------------------------------------------------------- first start

Require 'git' 'Install it from https://git-scm.com/downloads, then run this again.'
Require 'uv' 'Install it with:  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"  then reopen and run this again.'
Require 'npm' 'Install Node.js (LTS) from https://nodejs.org, then run this again.'

if (-not (Test-Path (Join-Path $Root '.env'))) {
    Copy-Item (Join-Path $Root '.env.example') (Join-Path $Root '.env')
    Write-Host 'Created your settings file (.env). Fill in OPENROUTER_API_KEY, ADMIN_EMAIL and ADMIN_PASSWORD' -ForegroundColor Cyan
    Write-Host '(10+ characters), then save and close Notepad to carry on.' -ForegroundColor Cyan
    Start-Process notepad (Join-Path $Root '.env') -Wait
}

Say 'Getting the latest version from GitHub...'
$null = Update-Code
Install-Backend
if (Test-FrontendStale) { Install-Frontend }
Start-Servers

Say 'Waiting for the app to come up...'
for ($i = 0; $i -lt 90 -and -not (Test-Port 3000); $i++) { Start-Sleep -Seconds 1 }
Start-Process 'http://localhost:3000'

Write-Host ''
Write-Host 'The app is running at http://localhost:3000' -ForegroundColor Green
Write-Host "This window checks GitHub for updates every $EverySeconds seconds and applies them by itself."
Write-Host 'To stop everything, close this window and the backend and frontend windows.'
Write-Host ''

# ---------------------------------------------------------------- keep up to date

while ($true) {
    Start-Sleep -Seconds $EverySeconds
    $changed = Update-Code
    if ($changed.Count -eq 0) { continue }
    Say "Updated from GitHub: $($changed.Count) file(s) changed." 'Green'
    $backendDeps = @($changed | Where-Object { $_ -match '^backend/(pyproject\.toml|uv\.lock)$' }).Count -gt 0
    $frontendDeps = Test-FrontendStale
    $envExample = @($changed | Where-Object { $_ -eq '.env.example' }).Count -gt 0
    if ($backendDeps -or $frontendDeps) {
        # New packages can't be installed under running servers on Windows: restart them.
        Say 'New packages: restarting the servers...' 'Yellow'
        if ($Servers.Count -lt 2) { Say 'Close any backend or frontend window you started yourself; they will be started again.' 'Yellow' }
        Stop-Servers
        if ($backendDeps) { Install-Backend }
        if ($frontendDeps) { Install-Frontend }
        Start-Servers
        Say 'Restarted. Refresh the browser.' 'Green'
    } else {
        Say 'The app reloads by itself; refresh the browser if a page looks stale.'
    }
    if ($envExample) { Say 'New settings were added to .env.example; compare it with your .env.' 'Yellow' }
}
