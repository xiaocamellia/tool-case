[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DistributionRoot,
    [string]$Python = "python",
    [switch]$RequireSignature
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$DistributionRoot = (Resolve-Path -LiteralPath $DistributionRoot).Path
$ExecutablePath = Join-Path $DistributionRoot "PortableRadarToolbox.exe"
$IconPath = Join-Path $DistributionRoot "image\rose.ico"

if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Missing packaged executable: $ExecutablePath"
}
if (-not (Test-Path -LiteralPath $IconPath -PathType Leaf)) {
    throw "Missing packaged icon resource: $IconPath"
}

$RuntimeMarkers = @(
    "PyQt5",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "docx",
    "lxml"
)
foreach ($marker in $RuntimeMarkers) {
    $markerPath = Join-Path $DistributionRoot $marker
    if (-not (Test-Path -LiteralPath $markerPath)) {
        throw "Missing runtime package directory: $marker"
    }
}

$QtPlatformPlugin = Get-ChildItem -LiteralPath $DistributionRoot -Recurse -File |
    Where-Object {
        $_.Name -eq "qwindows.dll" -and
        $_.Directory.Name -eq "platforms" -and
        $_.FullName -match "PyQt5"
    } |
    Select-Object -First 1
if (-not $QtPlatformPlugin) {
    throw "PyQt5 Windows platform plugin was not packaged."
}

$MatplotlibFont = Get-ChildItem -LiteralPath $DistributionRoot -Recurse -File |
    Where-Object {
        $_.Extension -eq ".ttf" -and $_.FullName -match "matplotlib"
    } |
    Select-Object -First 1
if (-not $MatplotlibFont) {
    throw "matplotlib font data was not packaged."
}

$PortableFiles = Get-ChildItem -LiteralPath $DistributionRoot -Recurse -File |
    Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".dll", ".pyd") } |
    Sort-Object FullName
if ($RequireSignature) {
    foreach ($file in $PortableFiles) {
        $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
        if ($signature.Status -ne "Valid") {
            throw "Authenticode validation failed for $($file.Name): $($signature.Status)"
        }
    }
}

foreach ($requiredMetadata in @(
    "build-manifest.json",
    "sbom.cdx.json",
    "third-party-components.json"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $DistributionRoot $requiredMetadata) -PathType Leaf)) {
        throw "Missing release metadata: $requiredMetadata"
    }
}

$TempRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "PortableRadarToolbox-verify-" + [guid]::NewGuid().ToString("N")
)
$InstallRoot = Join-Path $TempRoot "installed"
$AppRoot = Join-Path $InstallRoot "PortableRadarToolbox"
$DataRoot = Join-Path $TempRoot "AppData"
$StandardOutput = Join-Path $TempRoot "stdout.log"
$StandardError = Join-Path $TempRoot "stderr.log"

New-Item -ItemType Directory -Path $AppRoot -Force | Out-Null
New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
try {
    Get-ChildItem -LiteralPath $DistributionRoot -Force |
        Copy-Item -Destination $AppRoot -Recurse -Force

    $savedAppData = $env:APPDATA
    $savedPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:APPDATA = $DataRoot
        $env:QT_QPA_PLATFORM = "offscreen"
        $process = Start-Process `
            -FilePath (Join-Path $AppRoot "PortableRadarToolbox.exe") `
            -ArgumentList "--smoke-test" `
            -WorkingDirectory $AppRoot `
            -RedirectStandardOutput $StandardOutput `
            -RedirectStandardError $StandardError `
            -NoNewWindow `
            -Wait `
            -PassThru
    }
    finally {
        $env:APPDATA = $savedAppData
        $env:QT_QPA_PLATFORM = $savedPlatform
    }

    if ($process.ExitCode -ne 0) {
        $stderr = if (Test-Path -LiteralPath $StandardError) {
            Get-Content -LiteralPath $StandardError -Raw
        } else {
            ""
        }
        throw "Packaged smoke test failed with exit code $($process.ExitCode): $stderr"
    }
}
finally {
    $tempFullPath = [IO.Path]::GetFullPath($TempRoot)
    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd(
        [IO.Path]::DirectorySeparatorChar
    ) + [IO.Path]::DirectorySeparatorChar
    if ($tempFullPath.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $tempFullPath -Recurse -Force
    }
}

Write-Host "Release directory verified: $DistributionRoot"
