#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="FugeWeChat"
BUNDLE_ID="com.fuge.wechatcourier.macos"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="$ROOT_DIR/dist/$APP_NAME.app"

case "$MODE" in
  run|--build|build|--debug|debug|--logs|logs|--telemetry|telemetry|--verify|verify) ;;
  *) echo "usage: $0 [run|--build|--debug|--logs|--telemetry|--verify]" >&2; exit 2 ;;
esac

if [[ "$MODE" != "--build" && "$MODE" != "build" ]]; then
  pkill -x "$APP_NAME" >/dev/null 2>&1 || true
fi

export CLANG_MODULE_CACHE_PATH="$ROOT_DIR/macos/.build/clang-module-cache"
swift build --package-path "$ROOT_DIR/macos" --cache-path "$ROOT_DIR/macos/.build/cache"
BIN_DIR="$(swift build --package-path "$ROOT_DIR/macos" --cache-path "$ROOT_DIR/macos/.build/cache" --show-bin-path)"
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"
cp "$BIN_DIR/$APP_NAME" "$BIN_DIR/WeChatMacAgent" "$APP_BUNDLE/Contents/MacOS/"
cp "$ROOT_DIR/assets/fuge-logo.png" "$APP_BUNDLE/Contents/Resources/fuge-logo.png"
chmod +x "$APP_BUNDLE/Contents/MacOS/"*

ICONSET="$ROOT_DIR/macos/.build/FugeIcon.iconset"
mkdir -p "$ICONSET"
for SIZE in 16 32 128 256 512; do
  sips -z "$SIZE" "$SIZE" "$ROOT_DIR/assets/fuge-logo.png" --out "$ICONSET/icon_${SIZE}x${SIZE}.png" >/dev/null
  DOUBLE_SIZE=$((SIZE * 2))
  sips -z "$DOUBLE_SIZE" "$DOUBLE_SIZE" "$ROOT_DIR/assets/fuge-logo.png" --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP_BUNDLE/Contents/Resources/FugeIcon.icns"

cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleName</key><string>福格微信助手</string>
  <key>CFBundleDisplayName</key><string>福格微信助手</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleIconFile</key><string>FugeIcon</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# An existing Apple Development identity keeps privacy authorization stable
# across local rebuilds. Distribution still needs Developer ID/notarization.
SIGN_IDENTITY="${COURIER_SIGN_IDENTITY:-$(security find-identity -p codesigning -v | awk '/"Apple Development:/ {print $2; exit}')}"
SIGN_IDENTITY="${SIGN_IDENTITY:--}"
codesign --force --sign "$SIGN_IDENTITY" --identifier "$BUNDLE_ID.agent" "$APP_BUNDLE/Contents/MacOS/WeChatMacAgent"
codesign --force --sign "$SIGN_IDENTITY" "$APP_BUNDLE"

case "$MODE" in
  --build|build) echo "Built: $APP_BUNDLE" ;;
  run) /usr/bin/open -n "$APP_BUNDLE" ;;
  --debug|debug) lldb -- "$APP_BUNDLE/Contents/MacOS/$APP_NAME" ;;
  --logs|logs) /usr/bin/open -n "$APP_BUNDLE"; /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\"" ;;
  --telemetry|telemetry) /usr/bin/open -n "$APP_BUNDLE"; /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\"" ;;
  --verify|verify) /usr/bin/open -n "$APP_BUNDLE"; sleep 1; pgrep -x "$APP_NAME" >/dev/null; echo "Launch verified" ;;
esac
