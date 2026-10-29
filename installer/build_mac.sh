#!/bin/bash
# Builds the Mac app (Q DATA.app) and packs it two ways:
#   Q-DATA-<version>-macOS-<arch>.dmg  first install: open it and drag Q DATA into Applications
#   Q-DATA-<version>-macOS-<arch>.zip  what the installed app downloads to update itself
# GitHub Actions runs this on an Apple Silicon Mac (arm64) and an Intel Mac (x86_64). To build by hand on a Mac
# (Python 3.12 installed):
#   pip install -r requirements.txt -r requirements-desktop.txt
#   bash installer/build_mac.sh 1.0.0 owner/repo
set -euo pipefail
VERSION="${1:-1.0.0}"
REPO="${2:-}"
cd "$(dirname "$0")/.."
ARCH="$(python -c 'import platform; m=platform.machine().lower(); print("arm64" if m in ("arm64","aarch64") else "x86_64")')"
NAME="Q-DATA-${VERSION}-macOS-${ARCH}"

# The version and the update source are written into the app so it knows what it is and where to look for updates.
cat > backend/version.py <<EOF
"""The app version. The release build replaces it with the version from the git tag (for example v1.2.0 -> 1.2.0)."""
__version__ = "${VERSION}"
UPDATE_REPO = "${REPO}"          # owner/repo on GitHub that publishes releases; the release build fills this in
EOF

# The Mac icon (.icns) made from the same artwork as the Windows icon.
rm -rf build/icon.iconset && mkdir -p build/icon.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s assets/icon.png --out "build/icon.iconset/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z $d $d assets/icon.png --out "build/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns build/icon.iconset -o build/icon.icns

python -m PyInstaller --noconfirm --clean --windowed --name "Q DATA" --icon build/icon.icns \
  --osx-bundle-identifier com.qdata.app \
  --add-data "frontend:frontend" --add-data "assets:assets" --add-data ".env.example:." \
  --collect-submodules uvicorn --collect-data tzdata \
  --hidden-import webview.platforms.cocoa --hidden-import pystray._darwin \
  NQES.py

APP="dist/Q DATA.app"
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${VERSION}" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string ${VERSION}" "$PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${VERSION}" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 11.0" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :NSHumanReadableCopyright string Q DATA" "$PLIST" 2>/dev/null || true

# Without a paid Apple Developer account the app is signed "ad hoc" (no developer name). That is enough for it to run once
# you allow it the first time; see the README.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

mkdir -p dist/installer
rm -f "dist/installer/${NAME}.zip" "dist/installer/${NAME}.dmg"
ditto -c -k --sequesterRsrc --keepParent "$APP" "dist/installer/${NAME}.zip"

rm -rf build/dmg && mkdir -p build/dmg
ditto "$APP" "build/dmg/Q DATA.app"
ln -s /Applications build/dmg/Applications
hdiutil create -volname "Q DATA" -srcfolder build/dmg -ov -format UDZO "dist/installer/${NAME}.dmg" >/dev/null

ls -la dist/installer
