# Downloads the prebuilt native libraries ShieldVPN needs.
#
#   libv2ray.aar                       -> Xray core (VLESS / Reality / XHTTP / TCP+TLS)
#   app/libs/<abi>/libhev-socks5-tunnel.so <- TUN -> SOCKS5 bridge for CoreVpnService
#
# hev is shipped as a bare .so (taken out of the official AAR) instead of the AAR
# itself, because hev-socks5-tunnel.aar declares minSdk 29 and would force the whole
# app to Android 10+. The native library is only loaded in hev mode, and
# SettingsManager.isUsingHevTun() falls back to the Xray tun inbound below API 29.
$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $PSScriptRoot
$libsDir = Join-Path $projectDir "app\libs"
New-Item -ItemType Directory -Force -Path $libsDir | Out-Null

$XrayLiteVersion = "v26.11.9"
$HevVersion = "2.19.3"
$ProgressPreference = "SilentlyContinue"

# ---------------------------------------------------------------- libv2ray.aar
$libv2ray = Join-Path $libsDir "libv2ray.aar"
if (-not (Test-Path $libv2ray) -or (Get-Item $libv2ray).Length -eq 0) {
    Write-Host "Downloading libv2ray.aar ($XrayLiteVersion)..."
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 900 `
        -Uri "https://github.com/2dust/AndroidLibXrayLite/releases/download/$XrayLiteVersion/libv2ray.aar" `
        -OutFile $libv2ray
}

# ------------------------------------------------- libhev-socks5-tunnel.so
$hevSo = Join-Path $libsDir "arm64-v8a\libhev-socks5-tunnel.so"
if (-not (Test-Path $hevSo) -or (Get-Item $hevSo).Length -eq 0) {
    $hevAar = Join-Path $libsDir "hev-socks5-tunnel.aar"
    Write-Host "Downloading hev-socks5-tunnel.aar ($HevVersion) and extracting .so files..."
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 900 `
        -Uri "https://github.com/heiher/hev-socks5-tunnel/releases/download/$HevVersion/hev-socks5-tunnel.aar" `
        -OutFile $hevAar

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($hevAar)
    try {
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -match '^jni/([^/]+)/libhev-socks5-tunnel\.so$') {
                $abi = $Matches[1]
                $abiDir = Join-Path $libsDir $abi
                New-Item -ItemType Directory -Force -Path $abiDir | Out-Null
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile(
                    $entry, (Join-Path $abiDir "libhev-socks5-tunnel.so"), $true)
            }
        }
    } finally {
        $zip.Dispose()
    }

    # The AAR manifest must never reach the app manifest merger.
    Remove-Item $hevAar -Force
}

Get-ChildItem $libsDir -Recurse -File | Select-Object FullName, Length

# ------------------------------------------------- ByeDPI (ciadpi) for Android
# YouTube is throttled by the Russian DPI, so the app runs the upstream ciadpi
# binary as a local SOCKS5 proxy (127.0.0.1:1080) and Xray routes the YouTube
# domains into it. The binary is stored as libciadpi.so so Android extracts it to
# nativeLibraryDir, the only directory mounted executable for the app.
$ByeDpiVersion = "v0.17.3"
$byedpiAssets = @{
    "arm64-v8a"   = "byedpi-17.3-aarch64.tar.gz"
    "armeabi-v7a" = "byedpi-17.3-armv7l.tar.gz"
    "x86_64"      = "byedpi-17.3-x86_64.tar.gz"
    "x86"         = "byedpi-17.3-i686.tar.gz"
}

foreach ($abi in $byedpiAssets.Keys) {
    $target = Join-Path $libsDir "$abi\libciadpi.so"
    if ((Test-Path $target) -and (Get-Item $target).Length -gt 0) {
        continue
    }
    $asset = $byedpiAssets[$abi]
    $archive = Join-Path $env:TEMP $asset
    $extract = Join-Path $env:TEMP "byedpi-$abi"
    Write-Host "Downloading $asset ($ByeDpiVersion)..."
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 600 `
        -Uri "https://github.com/hufrea/byedpi/releases/download/$ByeDpiVersion/$asset" `
        -OutFile $archive
    New-Item -ItemType Directory -Force -Path $extract | Out-Null
    tar -xzf $archive -C $extract
    $binary = Get-ChildItem $extract -File | Where-Object { $_.Name -like "ciadpi*" } | Select-Object -First 1
    if ($null -eq $binary) { throw "ciadpi binary not found in $asset" }
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Copy-Item $binary.FullName $target -Force
    Remove-Item $archive -Force -ErrorAction SilentlyContinue
    Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
}

Get-ChildItem $libsDir -Recurse -File | Where-Object { $_.Name -like "*ciadpi*" } | Select-Object FullName, Length

# ------------------------------------------------------- geo databases (Xray)
# Xray rejects the config when routing uses geosite:/geoip: rules and the .dat
# files are absent, so they are packed into the APK and unpacked on first launch.
$assetsDir = Join-Path $projectDir "app\src\main\assets"
New-Item -ItemType Directory -Force -Path $assetsDir | Out-Null

$geoFiles = @{
    "geoip.dat"                 = "https://github.com/v2fly/geoip/releases/latest/download/geoip.dat"
    "geosite.dat"               = "https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat"
    "geoip-only-cn-private.dat" = "https://github.com/Loyalsoldier/geoip/releases/latest/download/geoip-only-cn-private.dat"
}

foreach ($name in $geoFiles.Keys) {
    $target = Join-Path $assetsDir $name
    if ((Test-Path $target) -and (Get-Item $target).Length -gt 0) {
        continue
    }
    Write-Host "Downloading $name..."
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 900 -Uri $geoFiles[$name] -OutFile $target
}

Get-ChildItem (Join-Path $assetsDir "*.dat") | Select-Object Name, Length
