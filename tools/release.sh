#!/bin/bash
# 새 버전 배포:  tools/release.sh 1.5.0 "바뀐 점 설명"
# → 버전 올리기, 맥(공증)·윈도우·안드로이드 빌드, git 커밋·태그·푸시, GitHub 릴리스 생성
# 선생님 컴퓨터의 쓰담이 실행될 때 새 버전을 알려주고, 버튼 한 번으로 업데이트됩니다.
set -euo pipefail
V="${1:?사용법: tools/release.sh 1.5.0 \"바뀐 점\"}"
NOTES="${2:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
[[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "버전은 1.5.0 형식으로"; exit 1; }
if [ -n "$(git status --porcelain)" ]; then echo "커밋하지 않은 변경이 있습니다. 먼저 커밋하세요."; git status --short; exit 1; fi
sed -i '' "s/^VERSION = .*/VERSION = \"$V\"/" app/version.py
./macos/build_app.sh                       # 맥: 서명·공증 DMG, 앱 zip, 업데이트용 코드, 단축어
./windows/build_windows.sh                 # 윈도우: Sseudam-Setup.exe
(cd mobile/android && ./gradlew -q assembleGithubRelease bundlePlayRelease) && cp mobile/android/app/build/outputs/apk/github/release/app-github-release.apk dist/Sseudam-Android.apk
git add app/version.py 프롬프트_모음.md
git commit -m "Release v$V"
git tag "v$V"
git push origin HEAD --tags
if [ -n "$NOTES" ]; then N=(--notes "$NOTES"); else N=(--generate-notes); fi
ASSETS=(dist/Sseudam.dmg dist/Sseudam-mac.zip dist/Sseudam-Setup.exe dist/Sseudam-Android.apk dist/seteuk-app.zip dist/whisper-cli-arm64.zip)
[ -f dist/iPhone-Shortcuts.zip ] && ASSETS+=(dist/iPhone-Shortcuts.zip)
gh release create "v$V" "${ASSETS[@]}" --title "쓰담 $V" "${N[@]}"
# Homebrew 탭(hanseolhui/tap)도 새 버전으로 — brew install --cask hanseolhui/tap/sseudam
TAP="$HOME/Desktop/Projects/homebrew-tap"
if [ -d "$TAP/.git" ]; then
  SHA=$(shasum -a 256 dist/Sseudam-mac.zip | cut -d' ' -f1)
  cat > "$TAP/Casks/sseudam.rb" <<CASK
cask "sseudam" do
  version "$V"
  sha256 "$SHA"

  url "https://github.com/hanseolhui/sseudam/releases/download/v#{version}/Sseudam-mac.zip"
  name "쓰담"
  name "Sseudam"
  desc "Teacher voice notes: record, split by student, and draft school records"
  homepage "https://hanseolhui.github.io/sseudam/"

  depends_on macos: :monterey

  app "쓰담.app"

  uninstall quit: "kr.sseudam.desktop"
  # 학생 기록(~/Library/Application Support/쓰담)은 지우지 않음
end
CASK
  (cd "$TAP" && git add Casks/sseudam.rb && git commit -qm "sseudam $V" && git push -q) && echo "Homebrew 탭 갱신: $V"
fi
echo "배포 완료: v$V"
