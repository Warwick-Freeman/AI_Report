<#
.SYNOPSIS
    Starts the ProfusionEEG study browser.

.DESCRIPTION
    Launches study_browser.py using the project's own virtual environment, so it
    works from any prompt without activating anything first. Paths are resolved
    from this script's location rather than the current directory, so the script
    can be run from anywhere or pinned to a shortcut.

    The working directory is set to the project root while the browser runs,
    because a relative output folder such as the default ".\reports" is resolved
    against it.

.PARAMETER StudyFolder
    Folder holding ProfusionEEG study subfolders and their _CMPStudyList.mdb.
    Optional - the browser remembers the last folder used and has a Browse
    button.

.EXAMPLE
    .\Start-StudyBrowser.ps1

.EXAMPLE
    .\Start-StudyBrowser.ps1 -StudyFolder "D:\Studies"

.EXAMPLE
    .\Start-StudyBrowser.ps1 "ProfusionEEGSDK\DemoStudies"

.NOTES
    If PowerShell refuses to run this ("running scripts is disabled on this
    system"), either unblock it for the current session:

        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

    or run it once without changing any policy:

        powershell -ExecutionPolicy Bypass -File .\Start-StudyBrowser.ps1
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string] $StudyFolder
)

$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$app = Join-Path $projectRoot 'study_browser.py'

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error ("No virtual environment at $python.`n" +
        "Create it and install the dependencies from the project root:`n" +
        "    uv venv --python 3.12 .venv`n" +
        "    .\.venv\Scripts\python.exe -m pip install -r requirements.txt")
    exit 1
}

if (-not (Test-Path -LiteralPath $app)) {
    Write-Error "study_browser.py is not next to this script (looked in $projectRoot)."
    exit 1
}

# Non-fatal checks. Neither stops the browser starting, but both stop a report
# part-way through, so they are worth knowing about before a four-minute run.
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'arialuni.ttf'))) {
    Write-Warning ("arialuni.ttf is missing from the project root - PDF generation " +
        "will fail. Copy a Unicode TrueType font there, e.g.`n" +
        "    Copy-Item C:\Windows\Fonts\arial.ttf $projectRoot\arialuni.ttf")
}

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'config.env'))) {
    Write-Warning ("config.env is missing - the LLM report will be unavailable. " +
        "The analysis and the PDF do not need it.")
}

if ($StudyFolder -and -not (Test-Path -LiteralPath $StudyFolder)) {
    Write-Warning "Study folder '$StudyFolder' does not exist - opening the browser anyway."
}

$arguments = @($app)
if ($StudyFolder) { $arguments += $StudyFolder }

Write-Host "Starting the ProfusionEEG study browser..." -ForegroundColor Cyan
Write-Host "  Python : $python"
Write-Host "  Project: $projectRoot"
if ($StudyFolder) { Write-Host "  Studies: $StudyFolder" }
Write-Host "  (this prompt stays busy until the window is closed)"

Push-Location -LiteralPath $projectRoot
try {
    & $python @arguments
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Write-Warning "The study browser exited with code $exitCode."
}
exit $exitCode
