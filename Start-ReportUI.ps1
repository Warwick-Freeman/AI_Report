<#
.SYNOPSIS
    Starts the SCORE report review front end and opens it in a browser.

.DESCRIPTION
    Runs report_server.py from the repository's virtual environment. The server
    binds to the loopback address only and the page loads no script from any
    network, so this works with the machine offline.

.PARAMETER Study
    A study folder or EEG file to open on start. Optional - the front end can
    take one on its first screen.

.PARAMETER Port
    Port to listen on. Defaults to 8731.

.PARAMETER NoBrowser
    Start the server without opening a browser.

.EXAMPLE
    .\Start-ReportUI.ps1

.EXAMPLE
    .\Start-ReportUI.ps1 -Study 'C:\Studies\Patient.eeg'
#>
[CmdletBinding()]
param(
    [string] $Study,
    [int]    $Port = 8731,
    [switch] $NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Error "No virtual environment at $python. Create it before running the UI."
    return
}

$server = Join-Path $root 'report_server.py'
if (-not (Test-Path $server)) {
    Write-Error "report_server.py is missing from $root."
    return
}

$arguments = @($server, '--port', $Port)
if ($Study) {
    if (-not (Test-Path $Study)) {
        Write-Error "Study not found: $Study"
        return
    }
    $arguments += @('--study', (Resolve-Path $Study).Path)
}
if ($NoBrowser) { $arguments += '--no-browser' }

Write-Host 'SCORE report review front end' -ForegroundColor Cyan
Write-Host "  http://127.0.0.1:$Port/"
Write-Host '  Ctrl+C to stop'
Write-Host ''

Push-Location $root
try {
    & $python @arguments
}
finally {
    Pop-Location
}
