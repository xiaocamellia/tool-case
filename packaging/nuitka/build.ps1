[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Version = "1.0.0",
    [string]$CertificateThumbprint,
    [string]$CertificatePath,
    [string]$CertificatePassword,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$SkipTests,
    [switch]$AllowUnsigned
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$OutputRoot = Join-Path $ProjectRoot "artifacts\nuitka"
$CompileRoot = Join-Path $OutputRoot "compile"
$ReleaseRoot = Join-Path $OutputRoot "release"
$BuildConfigPath = Join-Path $ProjectRoot "build-environment.json"
$BuildLog = Join-Path $OutputRoot ("build-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$NuitkaCacheDir = Join-Path $ProjectRoot "var\nuitka-cache"

function Assert-PathInsideRoot {
    param([string]$Path, [string]$Root)

    $candidate = [IO.Path]::GetFullPath($Path)
    $rootPath = [IO.Path]::GetFullPath($Root)
    $rootPrefix = $rootPath.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.Equals($rootPath, [StringComparison]::OrdinalIgnoreCase) -and
        -not $candidate.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify path outside workspace: $candidate"
    }
}

function Remove-DirectoryIfPresent {
    param([string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Assert-PathInsideRoot -Path $Path -Root $ProjectRoot
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Invoke-LoggedCommand {
    param([string]$FilePath, [string[]]$Arguments)

    Write-Host ("RUN: {0} {1}" -f $FilePath, ($Arguments -join " "))
    & $FilePath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath"
    }
}

function Get-NormalizedPackageName {
    param([string]$Name)
    return ($Name -replace "[-_.]+", "-").ToLowerInvariant()
}

function Get-LockedPackages {
    param([string]$LockPath)

    $locked = @{}
    foreach ($rawLine in Get-Content -LiteralPath $LockPath -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        if ($line -notmatch "^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)$") {
            throw "Invalid exact dependency pin in $LockPath`: $line"
        }
        $locked[(Get-NormalizedPackageName $Matches[1])] = $Matches[2]
    }
    return $locked
}

function Assert-LockedEnvironment {
    param([string]$PythonExecutable)

    $installed = @{}
    $freezeOutput = & $PythonExecutable -m pip list --format=freeze
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect installed build dependencies."
    }
    foreach ($line in $freezeOutput) {
        if ($line -match "^([A-Za-z0-9_.-]+)==([^;]+)$") {
            $installed[(Get-NormalizedPackageName $Matches[1])] = $Matches[2]
        }
    }

    foreach ($lockName in @("requirements.lock", "requirements-build.lock")) {
        $locked = Get-LockedPackages (Join-Path $ProjectRoot $lockName)
        foreach ($entry in $locked.GetEnumerator()) {
            if (-not $installed.ContainsKey($entry.Key) -or $installed[$entry.Key] -ne $entry.Value) {
                throw ("Locked dependency mismatch for {0}: expected {1}, found {2}" -f
                    $entry.Key, $entry.Value, $installed[$entry.Key])
            }
        }
    }
}

function Get-SignTool {
    $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kitsRoot) {
        $candidate = Get-ChildItem -LiteralPath $kitsRoot -Directory |
            Where-Object { $_.Name -match "^\d+\.\d+\.\d+\.\d+$" } |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
            Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1
        if ($candidate) {
            return $candidate
        }
    }
    throw "signtool.exe was not found in PATH or the Windows 10/11 SDK."
}

function Invoke-CodeSigning {
    param([string]$DistributionDirectory)

    if (-not $CertificateThumbprint -and -not $CertificatePath) {
        if (-not $AllowUnsigned) {
            throw "Release builds require a signing certificate. Use -AllowUnsigned only for local verification."
        }
        Write-Warning "Unsigned verification build created. This artifact must not be released."
        return
    }
    if ($CertificateThumbprint -and $CertificatePath) {
        throw "Use either -CertificateThumbprint or -CertificatePath, not both."
    }

    $signTool = Get-SignTool
    $portableFiles = Get-ChildItem -LiteralPath $DistributionDirectory -Recurse -File |
        Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".dll", ".pyd") } |
        Sort-Object FullName
    foreach ($file in $portableFiles) {
        $signArguments = @(
            "sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $TimestampUrl
        )
        if ($CertificatePath) {
            $resolvedCertificate = (Resolve-Path -LiteralPath $CertificatePath).Path
            $signArguments += @("/f", $resolvedCertificate)
            if ($CertificatePassword) {
                $signArguments += @("/p", $CertificatePassword)
            }
        }
        else {
            $signArguments += @("/sha1", $CertificateThumbprint)
        }
        $signArguments += $file.FullName
        Invoke-LoggedCommand -FilePath $signTool -Arguments $signArguments
    }

    foreach ($file in $portableFiles) {
        $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
        if ($signature.Status -ne "Valid") {
            throw "Authenticode validation failed for $($file.Name): $($signature.Status)"
        }
    }
}

$BuildConfig = Get-Content -LiteralPath $BuildConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$PythonExecutable = (& $Python -c "import sys; print(sys.executable)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $PythonExecutable) {
    throw "Unable to resolve Python executable: $Python"
}

$PythonVersion = (& $PythonExecutable -c "import platform; print(platform.python_version())").Trim()
$PythonBits = (& $PythonExecutable -c "import platform; print(platform.architecture()[0])").Trim()
if ($PythonVersion -ne $BuildConfig.python_version -or $PythonBits -ne $BuildConfig.python_architecture) {
    throw "Build Python must be $($BuildConfig.python_version) $($BuildConfig.python_architecture); found $PythonVersion $PythonBits"
}

$SourceDateEpoch = 0
$GitRoot = $ProjectRoot.Replace("\", "/")
$gitOutput = (& git -c "safe.directory=$GitRoot" -C $ProjectRoot show -s --format=%ct HEAD 2>&1 | Out-String)
if ($LASTEXITCODE -eq 0 -and $gitOutput.Trim() -match "^\d+$") {
    $SourceDateEpoch = [int]$gitOutput.Trim()
}
$env:SOURCE_DATE_EPOCH = "$SourceDateEpoch"

Remove-DirectoryIfPresent -Path $OutputRoot
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $CompileRoot -Force | Out-Null
New-Item -ItemType Directory -Path $NuitkaCacheDir -Force | Out-Null
$env:NUITKA_CACHE_DIR = $NuitkaCacheDir
Start-Transcript -Path $BuildLog -Append | Out-Null
$TranscriptActive = $true

try {
    Invoke-LoggedCommand -FilePath $PythonExecutable -Arguments @(
        (Join-Path $ProjectRoot "scripts\verify_lock_hash.py")
    )
    Assert-LockedEnvironment -PythonExecutable $PythonExecutable
    Invoke-LoggedCommand -FilePath $PythonExecutable -Arguments @("-m", "pip", "check")

    if (-not $SkipTests) {
        $env:QT_QPA_PLATFORM = "offscreen"
        Invoke-LoggedCommand -FilePath $PythonExecutable -Arguments @(
            "-m", "pytest", "-q", "-W", "error"
        )
    }

    $NuitkaVersionOutput = (& $PythonExecutable -m nuitka --version 2>&1 | Out-String)
    $NuitkaVersionMatch = [regex]::Match($NuitkaVersionOutput, "(?m)^\s*(\d+\.\d+\.\d+)\s*$")
    if (-not $NuitkaVersionMatch.Success -or $NuitkaVersionMatch.Groups[1].Value -ne $BuildConfig.nuitka_version) {
        throw "Nuitka must be $($BuildConfig.nuitka_version); version output was: $NuitkaVersionOutput"
    }

    $ImageRoot = Join-Path $ProjectRoot "image"
    $EntryScript = Join-Path $ProjectRoot "radar_tool\run.py"
    $NuitkaArguments = @(
        "-m", "nuitka",
        "--standalone",
        "--windows-disable-console",
        "--enable-plugin=pyqt5",
        "--deployment",
        "--assume-yes-for-downloads",
        "--msvc=$($BuildConfig.msvc_version)",
        "--lto=no",
        "--include-package=radar_tool",
        "--include-package=PyQt5",
        "--include-package-data=PyQt5",
        "--include-package=matplotlib",
        "--include-package-data=matplotlib",
        "--include-package=numpy",
        "--include-package=pandas",
        "--include-package=scipy",
        "--include-package=openpyxl",
        "--include-package-data=openpyxl",
        "--include-package=docx",
        "--include-package-data=docx",
        "--include-package=xlrd",
        "--include-package-data=xlrd",
        "--include-data-dir=$ImageRoot=image",
        "--output-dir=$CompileRoot",
        "--output-filename=PortableRadarToolbox.exe",
        "--company-name=Portable Radar Toolbox",
        "--product-name=Portable Radar Toolbox",
        "--file-version=$Version",
        "--product-version=$Version",
        "--copyright=Portable Radar Toolbox contributors",
        "--remove-output",
        $EntryScript
    )
    Invoke-LoggedCommand -FilePath $PythonExecutable -Arguments $NuitkaArguments

    $Executable = Get-ChildItem -LiteralPath $CompileRoot -Recurse -File |
        Where-Object { $_.Name -eq "PortableRadarToolbox.exe" } |
        Sort-Object FullName |
        Select-Object -First 1
    if (-not $Executable) {
        throw "Nuitka did not produce PortableRadarToolbox.exe."
    }

    $NinjaDistribution = $Executable.Directory.FullName
    New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
    Get-ChildItem -LiteralPath $NinjaDistribution -Force |
        Copy-Item -Destination $ReleaseRoot -Recurse -Force

    Invoke-CodeSigning -DistributionDirectory $ReleaseRoot

    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
    $TranscriptActive = $false
    Invoke-LoggedCommand -FilePath $PythonExecutable -Arguments @(
        (Join-Path $ProjectRoot "scripts\generate_release_metadata.py"),
        "--root", $ProjectRoot,
        "--release-dir", $ReleaseRoot,
        "--version", $Version,
        "--source-date-epoch", "$SourceDateEpoch",
        "--build-log", $BuildLog
    )

    $VerifyArguments = @{
        DistributionRoot = $ReleaseRoot
        Python = $PythonExecutable
        RequireSignature = [bool]($CertificateThumbprint -or $CertificatePath)
    }
    & (Join-Path $PSScriptRoot "verify_release.ps1") @VerifyArguments

    $ArchiveName = "PortableRadarToolbox-$Version-win64.zip"
    $ArchivePath = Join-Path $OutputRoot $ArchiveName
    Invoke-LoggedCommand -FilePath $PythonExecutable -Arguments @(
        (Join-Path $ProjectRoot "scripts\package_release.py"),
        "--release-dir", $ReleaseRoot,
        "--output", $ArchivePath,
        "--source-date-epoch", "$SourceDateEpoch"
    )

    $ArchiveHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $HashPath = Join-Path $OutputRoot "$ArchiveName.sha256"
    "$ArchiveHash *$ArchiveName" | Set-Content -LiteralPath $HashPath -Encoding Ascii
    Write-Host "Release archive: $ArchivePath"
    Write-Host "Release SHA256: $ArchiveHash"
}
finally {
    if ($TranscriptActive) {
        Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
    }
}
