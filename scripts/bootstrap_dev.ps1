[CmdletBinding()]
param(
    [string]$EnvironmentPath = ".venv"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "The reproducible development environment currently supports Windows only."
}

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$lockPath = Join-Path $repositoryRoot "requirements\dev-py313-windows.lock"
$pyprojectPath = Join-Path $repositoryRoot "pyproject.toml"

function Get-NormalizedTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $content = [IO.File]::ReadAllText($Path).Replace("`r`n", "`n").Replace("`r", "`n")
    $encoding = New-Object Text.UTF8Encoding($false)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha256.ComputeHash($encoding.GetBytes($content))
    } finally {
        $sha256.Dispose()
    }
    return [BitConverter]::ToString($hashBytes).Replace("-", "").ToLowerInvariant()
}

if ([IO.Path]::IsPathRooted($EnvironmentPath)) {
    $resolvedEnvironmentPath = [IO.Path]::GetFullPath($EnvironmentPath)
} else {
    $resolvedEnvironmentPath = [IO.Path]::GetFullPath(
        (Join-Path $repositoryRoot $EnvironmentPath)
    )
}

if ($resolvedEnvironmentPath.TrimEnd("\") -eq $repositoryRoot.TrimEnd("\")) {
    throw "The virtual environment path must not be the repository root."
}

if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw "Development lock file not found: $lockPath"
}

$lockHeader = Get-Content -LiteralPath $lockPath -TotalCount 8
$hashLine = $lockHeader | Where-Object {
    $_ -match '^# pyproject-normalized-sha256: ([0-9a-f]{64})$'
}
if ($null -eq $hashLine) {
    throw "The development lock file has no valid normalized pyproject SHA-256 binding."
}

$expectedPyprojectHash = [regex]::Match(
    [string]$hashLine,
    '^# pyproject-normalized-sha256: ([0-9a-f]{64})$'
).Groups[1].Value
$actualPyprojectHash = Get-NormalizedTextSha256 -Path $pyprojectPath
if ($expectedPyprojectHash -ne $actualPyprojectHash) {
    throw "The development lock is stale. Run .\scripts\update_dev_lock.ps1 and review the diff."
}

$requestedPython = & py -3.13 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $requestedPython.Trim() -ne "3.13") {
    throw "CPython 3.13 is required for the locked development environment."
}

$environmentPython = Join-Path $resolvedEnvironmentPath "Scripts\python.exe"
$environmentConfig = Join-Path $resolvedEnvironmentPath "pyvenv.cfg"
if (Test-Path -LiteralPath $resolvedEnvironmentPath) {
    if (
        -not (Test-Path -LiteralPath $environmentConfig -PathType Leaf) -or
        -not (Test-Path -LiteralPath $environmentPython -PathType Leaf)
    ) {
        throw "Environment path exists but is not a usable Windows venv: $resolvedEnvironmentPath"
    }
} else {
    Write-Host "Creating Python 3.13 virtual environment at $resolvedEnvironmentPath"
    & py -3.13 -m venv $resolvedEnvironmentPath
    if ($LASTEXITCODE -ne 0) {
        throw "Python failed to create the virtual environment."
    }
}

$environmentVersion = & $environmentPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $environmentVersion.Trim() -ne "3.13") {
    throw "The selected virtual environment must use CPython 3.13."
}

Write-Host "Installing the hash-locked development dependency baseline"
& $environmentPython -m pip install `
    --disable-pip-version-check `
    --require-hashes `
    --requirement $lockPath
if ($LASTEXITCODE -ne 0) {
    throw "Installing the locked development dependencies failed."
}

Write-Host "Installing this checkout as an editable package without resolving dependencies"
& $environmentPython -m pip install `
    --disable-pip-version-check `
    --no-build-isolation `
    --no-deps `
    --editable $repositoryRoot
if ($LASTEXITCODE -ne 0) {
    throw "Installing the project in editable mode failed."
}

$installedVersion = & $environmentPython -c `
    "from importlib.metadata import version; print(version('guarded-desktop-agent'))"
if ($LASTEXITCODE -ne 0) {
    throw "The installed project could not be imported from the virtual environment."
}

Write-Host "Development environment ready."
Write-Host "Python: $environmentPython"
Write-Host "Project version: $($installedVersion.Trim())"
Write-Host "Activation is optional; invoke the environment's executables directly."
