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
