#!/usr/bin/env bash
# TailFin Wireless ADB Pairing, Deployment & Memory Benchmark Script
# Target Device: Moto G Power (2021) — Android 11 (API 30)

set -euo pipefail

PHONE_IP="${1:-${PHONE_IP:-192.168.1.XXX}}"
PAIR_PORT="${2:-${PAIR_PORT:-}}"
CONNECT_PORT="${3:-${CONNECT_PORT:-5555}}"

echo "========================================================"
echo " TailFin Wireless Deployment — Moto G Power (2021) API 30"
echo "========================================================"

if [[ "$PHONE_IP" == "192.168.1.XXX" ]]; then
    echo "Usage: $0 <PHONE_IP> [PAIR_PORT] [CONNECT_PORT]"
    echo "Example: $0 192.168.1.42 39123 41855"
    exit 1
fi

# 1. Pair ADB over Wi-Fi if PAIR_PORT is provided
if [[ -n "$PAIR_PORT" ]]; then
    echo "[1/6] Pairing ADB over Wi-Fi at ${PHONE_IP}:${PAIR_PORT}..."
    adb pair "${PHONE_IP}:${PAIR_PORT}"
else
    echo "[1/6] Skipping pairing step (no PAIR_PORT provided)..."
fi

# 2. Connect to the main Wireless Debugging port
echo "[2/6] Connecting to Wireless Debugging port ${PHONE_IP}:${CONNECT_PORT}..."
adb connect "${PHONE_IP}:${CONNECT_PORT}"

# 3. Verify Android 11 device is online
echo "[3/6] Verifying device status..."
adb devices -l

# 4. Build and install TailFin Debug APK
echo "[4/6] Building and installing TailFin Debug APK..."
cd /home/mrnicholas/Dev/Tail-Fin
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk

# 5. Set TailFin as default Home Launcher for testing
echo "[5/6] Setting com.tailfin.launcher as default HOME role holder..."
adb shell cmd role add-role-holder android.app.role.HOME com.tailfin.launcher

# 6. Benchmark memory footprint and stream live TailFin logs
echo "[6/6] Benchmarking memory usage (dumpsys meminfo com.tailfin.launcher)..."
adb shell am start -n com.tailfin.launcher/com.galaxyrio.gracelauncher.MainActivity
sleep 2
adb shell dumpsys meminfo com.tailfin.launcher | head -n 35

echo "Streaming live TailFin logs (Ctrl+C to exit)..."
adb logcat -v color --pid="$(adb shell pidof -s com.tailfin.launcher)"
