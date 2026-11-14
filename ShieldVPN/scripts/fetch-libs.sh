#!/usr/bin/env bash
# Downloads the prebuilt native libraries ShieldVPN needs.
#
#   libv2ray.aar                            -> Xray core (VLESS / Reality / XHTTP / TCP+TLS)
#   app/libs/<abi>/libhev-socks5-tunnel.so  -> TUN -> SOCKS5 bridge for CoreVpnService
#
# hev is shipped as a bare .so (taken out of the official AAR) instead of the AAR
# itself, because hev-socks5-tunnel.aar declares minSdk 29 and would force the whole
# app to Android 10+. The native library is only loaded in hev mode, and
# SettingsManager.isUsingHevTun() falls back to the Xray tun inbound below API 29.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIBS_DIR="$PROJECT_DIR/app/libs"
mkdir -p "$LIBS_DIR"

XRAY_LITE_VERSION="v26.11.9"
HEV_VERSION="2.19.3"

# ---------------------------------------------------------------- libv2ray.aar
if [ ! -s "$LIBS_DIR/libv2ray.aar" ]; then
  echo "Downloading libv2ray.aar ($XRAY_LITE_VERSION)..."
  curl -fL --retry 3 --retry-delay 5 \
    -o "$LIBS_DIR/libv2ray.aar" \
    "https://github.com/2dust/AndroidLibXrayLite/releases/download/${XRAY_LITE_VERSION}/libv2ray.aar"
fi

# ------------------------------------------------- libhev-socks5-tunnel.so
if [ ! -s "$LIBS_DIR/arm64-v8a/libhev-socks5-tunnel.so" ]; then
  echo "Downloading hev-socks5-tunnel.aar ($HEV_VERSION) and extracting .so files..."
  TMP_AAR="$(mktemp -t hev-socks5-tunnel.XXXXXX.aar)"
  curl -fL --retry 3 --retry-delay 5 \
    -o "$TMP_AAR" \
    "https://github.com/heiher/hev-socks5-tunnel/releases/download/${HEV_VERSION}/hev-socks5-tunnel.aar"

  for abi in arm64-v8a armeabi-v7a x86 x86_64; do
    if unzip -l "$TMP_AAR" "jni/$abi/libhev-socks5-tunnel.so" > /dev/null 2>&1; then
      mkdir -p "$LIBS_DIR/$abi"
      unzip -o -j "$TMP_AAR" "jni/$abi/libhev-socks5-tunnel.so" -d "$LIBS_DIR/$abi" > /dev/null
    fi
  done

  rm -f "$TMP_AAR"
fi

# Never let the AAR manifest reach the manifest merger.
rm -f "$LIBS_DIR/hev-socks5-tunnel.aar"

find "$LIBS_DIR" -type f -exec ls -lh {} \;
