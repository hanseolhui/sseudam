#!/bin/bash
# 쓰담.app(네이티브 창) + 설치용 DMG + 업데이트용 코드 묶음 + Whisper + 아이폰 단축어를 dist/ 에 만든다.
python3 "$(dirname "$0")/../tools/make_prompt_doc.py" >/dev/null
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' app/version.py)
BUILD="$ROOT/build"; DIST="$ROOT/dist"
APP="$BUILD/쓰담.app"
rm -rf "$BUILD" "$DIST"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/bin" "$DIST"

# 1) 네이티브 셸 (Apple Silicon + Intel 유니버설)
swiftc -O -target arm64-apple-macos12.0 macos/SseudamApp.swift -o "$BUILD/app-arm64"
swiftc -O -target x86_64-apple-macos12.0 macos/SseudamApp.swift -o "$BUILD/app-x86_64"
lipo -create "$BUILD/app-arm64" "$BUILD/app-x86_64" -output "$APP/Contents/MacOS/Sseudam"
# 기기 안 AI 도우미 (애플 Foundation Models — Apple Silicon 전용, macOS 26 미만에선 '사용 불가'로만 답함)
swiftc -O -target arm64-apple-macos12.0 -Xlinker -weak_framework -Xlinker FoundationModels macos/sseudam_ai.swift -o "$BUILD/sseudam-ai"

# 2) 서버 코드 · 실행 스크립트 · Whisper
rsync -a --exclude '__pycache__' --exclude '*.pyc' app "$APP/Contents/Resources/"
cp macos/start_server.sh "$APP/Contents/Resources/start_server.sh"
cp macos/bin/whisper-cli macos/bin/WHISPER_CPP_LICENSE macos/bin/WHISPER_CPP_VERSION "$APP/Contents/Resources/bin/"
cp "$BUILD/sseudam-ai" "$APP/Contents/Resources/bin/sseudam-ai"
cp macos/bin/llama-server macos/bin/LLAMA_CPP_LICENSE macos/bin/LLAMA_CPP_VERSION "$APP/Contents/Resources/bin/"   # 쓰담 AI 모델 엔진
chmod +x "$APP/Contents/Resources/bin/llama-server"
chmod +x "$APP/Contents/Resources/start_server.sh" "$APP/Contents/Resources/bin/whisper-cli" "$APP/Contents/Resources/bin/sseudam-ai"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>쓰담</string>
  <key>CFBundleDisplayName</key><string>쓰담</string>
  <key>CFBundleIdentifier</key><string>kr.sseudam.desktop</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>Sseudam</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleDevelopmentRegion</key><string>ko</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.education</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>쓰담 $VERSION — 말로 담고, 글로 씁니다</string>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSAppleEventsUsageDescription</key><string>메모 앱의 받아쓰기 메모를 가져오기 위해 필요합니다.</string>
</dict></plist>
PLIST

# 3) 아이콘
ICONSET="$BUILD/AppIcon.iconset"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s macos/icon-1024.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) macos/icon-1024.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

# 4) 서명: Developer ID 인증서가 있으면 자동 사용(+ 공증), 없으면 ad-hoc
if [ -z "${SIGN_ID:-}" ]; then
  SIGN_ID=$(security find-identity -v -p codesigning | awk '/Developer ID Application/ {print $2; exit}')
fi
NOTARY_PROFILE="${NOTARY_PROFILE:-notary}"
if [ -n "$SIGN_ID" ]; then
  echo "서명: Developer ID ($SIGN_ID)"
  SIGN=(codesign --force --timestamp --options runtime --sign "$SIGN_ID")
else
  echo "서명: ad-hoc (Developer ID 없음)"
  SIGN=(codesign --force --sign -)
fi
"${SIGN[@]}" "$APP/Contents/Resources/bin/whisper-cli"
"${SIGN[@]}" "$APP/Contents/Resources/bin/sseudam-ai"
"${SIGN[@]}" "$APP/Contents/Resources/bin/llama-server"
"${SIGN[@]}" "$APP"
codesign --verify --strict "$APP"

notarize() {  # $1 = 공증할 파일(.zip/.dmg)
  [ -n "$SIGN_ID" ] && [ "${SKIP_NOTARIZE:-0}" != "1" ] || return 0
  echo "애플 공증 제출: $(basename "$1") …"
  xcrun notarytool submit "$1" --keychain-profile "$NOTARY_PROFILE" --wait --timeout 30m | tail -3
}
if [ -n "$SIGN_ID" ] && [ "${SKIP_NOTARIZE:-0}" != "1" ]; then
  ditto -c -k --keepParent "$APP" "$BUILD/notarize-app.zip"
  notarize "$BUILD/notarize-app.zip"
  xcrun stapler staple "$APP"
fi

# 5) 배포 파일
ditto -c -k --norsrc --keepParent "$APP" "$DIST/Sseudam-mac.zip"          # install.sh 용
(cd "$ROOT" && zip -qr "$DIST/seteuk-app.zip" app -x '*/__pycache__/*' '*.pyc')   # 앱 내 업데이트용
(cd "$APP/Contents/Resources/bin" && zip -q "$DIST/whisper-cli-arm64.zip" whisper-cli WHISPER_CPP_LICENSE WHISPER_CPP_VERSION)  # 예전 앱용 Whisper
STAGE="$BUILD/dmg"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
cp 사용설명서.md 프롬프트_모음.md "$STAGE/" 2>/dev/null || true
hdiutil create -quiet -volname "쓰담 $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DIST/Sseudam.dmg"
if [ -n "$SIGN_ID" ]; then
  codesign --force --timestamp --sign "$SIGN_ID" "$DIST/Sseudam.dmg"
  notarize "$DIST/Sseudam.dmg" && [ "${SKIP_NOTARIZE:-0}" != "1" ] && xcrun stapler staple "$DIST/Sseudam.dmg"
fi

# 6) 아이폰 단축어 (이 맥이 iCloud에 로그인돼 있어야 서명됨 — 실패해도 빌드는 계속)
if python3 tools/build_shortcuts.py; then
  # GitHub 첨부 파일 이름은 영문만 안전 → 한글 이름 단축어는 zip 안에 (아이폰은 파일 이름을 단축어 이름으로 씀)
  (cd "$DIST" && mkdir -p "쓰담 단축어" && mv "쓰담 녹음.shortcut" "쓰담 받아쓰기.shortcut" "쓰담 단축어/" \
     && ditto -c -k --norsrc --keepParent "쓰담 단축어" iPhone-Shortcuts.zip && rm -rf "쓰담 단축어")
else
  echo "⚠︎ 단축어 서명 실패 — 사용설명서의 수동 만들기 안내를 이용하세요"
fi
echo "완료: $DIST (버전 $VERSION)"; ls -la "$DIST"
