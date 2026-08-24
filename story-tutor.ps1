[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $TutorArguments
)

$projectRoot = $PSScriptRoot
$sourceRoot = Join-Path $projectRoot 'src'
$configPath = Join-Path $projectRoot 'config\settings.json'

if (-not (Test-Path -LiteralPath $sourceRoot)) {
    throw "Story Tutor source folder was not found: $sourceRoot"
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw 'Python was not found. Install Python 3.11 or newer and ensure python.exe is available in PATH.'
}

$env:PYTHONPATH = $sourceRoot
Push-Location $projectRoot
try {
    # -S prevents unrelated/broken global site-packages startup hooks from
    # affecting this dependency-free application.
    & $pythonCommand.Source -S -m story_tutor --config $configPath @TutorArguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

