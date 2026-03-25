param(
    [string]$SourceDir = "onionrelay_src"
)

$ErrorActionPreference = "Stop"
$isGitHubActions = ($env:GITHUB_ACTIONS -eq "true")

$repoRoot = (Resolve-Path ".").Path

function Get-MsysBashPath {
    $candidates = @()

    $bashFromPath = (Get-Command bash -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    if ($bashFromPath) {
        $candidates += $bashFromPath
    }
    if ($env:MSYS2_ROOT) {
        $candidates += (Join-Path $env:MSYS2_ROOT "usr\bin\bash.exe")
    }
    if ($env:RUNNER_TEMP) {
        $candidates += (Join-Path $env:RUNNER_TEMP "msys64\usr\bin\bash.exe")
    }
    if ($env:ChocolateyInstall) {
        $candidates += (Join-Path $env:ChocolateyInstall "lib\msys2\tools\usr\bin\bash.exe")
    }
    $candidates += "C:\msys64\usr\bin\bash.exe"
    $candidates += "C:\tools\msys64\usr\bin\bash.exe"

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not $candidate) {
            continue
        }
        if (-not (Test-Path $candidate)) {
            continue
        }

        # Reject WSL/Git-for-Windows bash; verify this bash can resolve pacman.
        & $candidate -lc "command -v pacman >/dev/null 2>&1"
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }

    return $null
}

$bash = Get-MsysBashPath
if (-not $bash) {
    if ($isGitHubActions) {
        throw "MSYS2 bash not found from setup-msys2 environment (expected under `$RUNNER_TEMP\\msys64)."
    }
    throw "MSYS2 bash not found. Install MSYS2 (or run msys2/setup-msys2 in CI) and retry."
}
if (-not (Test-Path $SourceDir)) {
    throw "Source directory not found: $SourceDir"
}

New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot "build") | Out-Null

$srcFull = (Resolve-Path $SourceDir).Path
$cfgLog = Join-Path $repoRoot "build\onionrelay_configure.log"
$makeLog = Join-Path $repoRoot "build\onionrelay_make.log"

function Convert-ToMsysPath([string]$windowsPath) {
    $resolved = [System.IO.Path]::GetFullPath($windowsPath)
    $drive = $resolved.Substring(0, 1).ToLowerInvariant()
    $tail = $resolved.Substring(2).Replace('\', '/')
    return "/$drive$tail"
}

$srcMsys = Convert-ToMsysPath $srcFull
$cfgLogMsys = Convert-ToMsysPath $cfgLog
$makeLogMsys = Convert-ToMsysPath $makeLog

$bashScript = @'
source /etc/profile
set -euo pipefail
export MSYSTEM=MINGW64
export PATH=/mingw64/bin:/usr/bin:$PATH

# Bootstrap required build deps for local/dev usage.
# In GitHub Actions, setup-msys2 already installs these packages.
if [[ -z "${GITHUB_ACTIONS:-}" ]] && command -v pacman >/dev/null 2>&1; then
  pacman --noconfirm --needed -Sy \
    mingw-w64-x86_64-toolchain \
    mingw-w64-x86_64-openssl \
    mingw-w64-x86_64-libevent \
    mingw-w64-x86_64-xz \
    mingw-w64-x86_64-zstd \
    mingw-w64-x86_64-zlib \
    autoconf \
    automake \
    libtool \
    make \
    pkgconf \
    gettext
fi

cd "__SRC_DIR__"

make distclean >/dev/null 2>&1 || true
chmod +x ./scripts/build/combine_libs || true

if [[ ! -f "./configure" ]]; then
  chmod +x ./autogen.sh
  ./autogen.sh || true

  if [[ ! -f "./configure" ]] && command -v autoreconf >/dev/null 2>&1; then
    autoreconf -i -f || true
  fi

  if [[ ! -f "./configure" ]]; then
    echo "Failed to generate ./configure (autogen/autoreconf)." >&2
    exit 1
  fi
fi
chmod +x ./configure

./configure \
  --disable-asciidoc \
  --disable-module-relay \
  --disable-module-dirauth \
  --disable-module-pow \
  > "__CFG_LOG__" 2>&1

make -j"$(nproc)" > "__MAKE_LOG__" 2>&1

src_bin="$(find src/app -maxdepth 1 -type f -name '*.exe' | head -n1)"
if [[ -z "${src_bin}" ]]; then
  echo "No Windows executable found under src/app after build" >&2
  exit 1
fi
cp -f "${src_bin}" src/app/onionrelay.exe

src_lib="$(find . -maxdepth 1 -type f -name 'lib*.a' | head -n1)"
if [[ -n "${src_lib}" ]]; then
  cp -f "${src_lib}" libonionrelay.a
fi

cp -f /mingw64/bin/libcrypto-3-x64.dll src/app/
cp -f /mingw64/bin/libssl-3-x64.dll src/app/
cp -f /mingw64/bin/libevent-7.dll src/app/
cp -f /mingw64/bin/liblzma-5.dll src/app/
cp -f /mingw64/bin/zlib1.dll src/app/
cp -f /mingw64/bin/libzstd.dll src/app/
cp -f /mingw64/bin/libwinpthread-1.dll src/app/
'@

$bashScript = $bashScript.Replace("__SRC_DIR__", $srcMsys)
$bashScript = $bashScript.Replace("__CFG_LOG__", $cfgLogMsys)
$bashScript = $bashScript.Replace("__MAKE_LOG__", $makeLogMsys)
$bashScript = $bashScript -replace "`r`n", "`n"

$tmpScript = Join-Path $repoRoot "build\onionrelay_build_tmp.sh"
[System.IO.File]::WriteAllText(
    $tmpScript,
    $bashScript,
    (New-Object System.Text.UTF8Encoding($false))
)

try {
    $tmpScriptMsys = Convert-ToMsysPath $tmpScript
    & $bash -lc "bash '$tmpScriptMsys'"
    if ($LASTEXITCODE -ne 0) {
        throw "OnionRelay build script failed with exit code $LASTEXITCODE"
    }
}
finally {
    Remove-Item -Force $tmpScript -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Build complete:"
Write-Host "  onionrelay.exe : $srcFull\src\app\onionrelay.exe"
Write-Host "  libonionrelay.a: $srcFull\libonionrelay.a"
Write-Host "  configure log  : $cfgLog"
Write-Host "  make log       : $makeLog"
