$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null
$env:TEMP = Join-Path $PSScriptRoot '.tmp'
$env:TMP = $env:TEMP
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (!(Test-Path -LiteralPath $venvPython)) {
    $pythonCandidates = @()
    if ($env:PYTHON_EXE) { $pythonCandidates += $env:PYTHON_EXE }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*WindowsApps*') { $pythonCandidates += $command.Source }
    $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyCommand) {
        $pythonCandidates += (& $pyCommand.Source -3 -c 'import sys;print(sys.executable)' 2>$null)
    }
    $pythonCandidates += Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
    $pythonCandidates += Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $selectedPython = $null
    foreach ($candidate in $pythonCandidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            & $candidate -c 'import sys;sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { $selectedPython = $candidate; break }
        }
    }
    if (!$selectedPython) {
        Write-Host 'Install Python 3.11 or newer from https://www.python.org/downloads/windows/ (enable Add Python to PATH).'
        Read-Host 'Press Enter to close'
        exit 1
    }
    & $selectedPython -m venv '.venv'
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python environment.' }
}

$signature = (Get-FileHash -LiteralPath 'requirements.txt' -Algorithm SHA256).Hash
$marker = Join-Path $PSScriptRoot '.venv\requirements.sha256'
if (!(Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne $signature) {
    & $venvPython -m pip install -r 'requirements.txt' --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network and retry.' }
    Set-Content -LiteralPath $marker -Value $signature -Encoding ascii
}
Write-Host 'Starting AI questionnaire simulator. Close this window to stop the local service.'
& $venvPython -m survey_sim.launcher
