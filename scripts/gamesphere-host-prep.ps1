# GameSphere host stream prep — StreamTweak-style session hooks for Windows.
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("start", "stop")]
    [string]$Action
)

$InstallDir = if ($env:GAMESPHERE_IMPORT_DIR) { $env:GAMESPHERE_IMPORT_DIR } else {
    Join-Path $env:LOCALAPPDATA "GameSphere\gamesphere-import-tool"
}
if (-not (Test-Path $InstallDir)) {
    $InstallDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

Push-Location $InstallDir
try {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $runner = "uv"
        $runnerArgs = @("run", "python", "-c", "import json,sys; from host_tuning.service import prep_start, prep_stop, write_prep_scripts; write_prep_scripts(); fn=prep_start if sys.argv[1]=='start' else prep_stop; print(json.dumps(fn()))", $Action)
    } else {
        $runner = "python"
        $runnerArgs = @("-c", "import json,sys; from host_tuning.service import prep_start, prep_stop, write_prep_scripts; write_prep_scripts(); fn=prep_start if sys.argv[1]=='start' else prep_stop; print(json.dumps(fn()))", $Action)
    }
    & $runner @runnerArgs | Out-Null
} finally {
    Pop-Location
}
