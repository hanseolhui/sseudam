# 쓰담 (sseudam) — 말로 담고, 글로 씁니다

수업·상담 중 선생님이 말로 남긴 학생 관찰을 학생별로 자동 정리하고, 학기말 학교생활기록부(교과 세특 · 행동특성 및 종합의견 · 자율·자치/동아리/진로활동) 초안을 뽑아 주는 교사용 프로그램. 맥·윈도우 + 아이폰·안드로이드 녹음 앱.

- **네이티브 맥 앱**(Swift/WKWebView 셸) — 자기 창·메뉴·Dock, 로그인 시 자동 실행
- **앱 안에서 받아쓰기**: whisper.cpp(Metal) 내장, 모델은 앱에서 내려받기 → 로컬 받아쓰기를 사용할 때 녹음을 외부 AI로 보내지 않음
- 아이폰 **음성메모** 자동 가져오기 · **메모 앱 받아쓰기** · 서명된 **단축어**(원탭 녹음 → iCloud 자동 연동)
- 기록 정리: 지원 기기의 기기 안 AI 또는 이름 기준 분리. 별도 로컬 텍스트 모델 설치 없음
- 세특 초안: 플러스 이용자는 클라우드 AI로 생성. 무료 사용자는 **프롬프트 복사 → ChatGPT·Gemini에서 작성 → 결과 붙여넣기 → 저장·수정**
- **구글시트 자동 반영 + 구글 드라이브 일일 백업/복원**(Apps Script, 토큰 보호), **엑셀(.xlsx) 내보내기**
- 시간표로 학급 자동 지정, 대시보드, NEIS 바이트 계산
- 서버는 표준 라이브러리만 쓰는 Python 3.8+ (외부 의존성 0)
- 맥의 기록 원본은 `~/Library/Application Support/쓰담/data`에 저장 — 외부 AI·구글시트·클라우드 백업을 사용하면 해당 경로로도 내용 전송. 이 저장소에는 코드만 있음

사용자 안내: [사용설명서.md](사용설명서.md) · 구조: [ARCHITECTURE.md](ARCHITECTURE.md)

## 설치 (사용자)
```bash
curl -fsSL https://raw.githubusercontent.com/hanseolhui/sseudam/main/install.sh | bash
```
또는 [Releases](https://github.com/hanseolhui/sseudam/releases/latest)의 `Sseudam.dmg`.

## 구성

| 폴더 | 내용 |
|---|---|
| `app/` | 파이썬 서버 + 웹 UI (맥·윈도우 공용, 앱 내 업데이트 단위) |
| `macos/` | Swift 네이티브 셸, Whisper(Metal) 실행 파일, 빌드·공증 |
| `windows/` | 실행기(launcher.pyw), NSIS 설치 프로그램, 빌드 (임베디드 파이썬 + whisper.cpp OpenBLAS) |
| `mobile/ios/` | 아이폰 '쓰담' 녹음 앱 (SwiftUI, XcodeGen) — iCloud 컨테이너 + 구글 드라이브 업로드 |
| `mobile/android/` | 안드로이드 '쓰담' 녹음 앱 (Kotlin, Compose) — 포그라운드 녹음 + WorkManager 업로드 |
| `docs/` | GitHub Pages: 소개·개인정보 처리방침 |

## 개발
```bash
python3 app/server.py          # http://127.0.0.1:8765 (데이터: ~/Library/Application Support/쓰담/data)
SETEUK_DATA=/tmp/seteuk-test python3 app/server.py   # 테스트용 별도 데이터
```

### 휴대폰 앱
```bash
cd mobile/ios && xcodegen generate && open Sseudam.xcodeproj        # 아이폰 (Xcode에 Apple ID 로그인 필요)
cd mobile/android && ./gradlew bundleRelease                        # 안드로이드 (업로드 키: ~/.sseudam/keystore.properties)
```
안드로이드 업로드 키(`~/.sseudam/upload-keystore.jks`)는 저장소에 없습니다. 잃어버리면 Play 업데이트가 막히니 따로 백업하세요.

## 배포 (업데이트 내보내기)
```bash
git commit -am "변경 내용"
tools/release.sh 1.2.0 "바뀐 점 설명"
```
`app/version.py` 버전을 올리고, `macos/build_app.sh`로 `dist/`에 3개 파일을 만든 뒤 태그·푸시하고 GitHub 릴리스를 생성합니다.

| 파일 | 용도 |
|---|---|
| `Sseudam.dmg` | 처음 설치용 (드래그 설치) |
| `Sseudam-mac.zip` | `install.sh` 한 줄 설치용 |
| `seteuk-app.zip` | **앱 내 자동 업데이트용** (app/ 코드만) |
| `whisper-cli-arm64.zip` | 예전 앱에 Whisper 실행 파일이 없을 때 받아감 |
| `iPhone-Shortcuts.zip` | 아이폰 단축어 2개(한글 파일명 유지용 zip) (빌드 시 `shortcuts sign`으로 서명 — 이 맥 iCloud 로그인 필요) |

앱 셸(.app)이 바뀌면 `version.py`의 `SHELL_REQUIRED`를 올립니다. 예전 셸에서 새 코드가 돌면 화면에 '새 앱으로 바꾸기'가 떠서 `Sseudam-mac.zip`을 받아 스스로 교체합니다.

### Whisper 실행 파일 다시 빌드
```bash
git clone --depth 1 https://github.com/ggml-org/whisper.cpp && cd whisper.cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON \
  -DGGML_NATIVE=OFF -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0
cmake --build build -j --target whisper-cli && cp build/bin/whisper-cli ../sseudam/macos/bin/
```

사용자 앱은 실행 시 `releases/latest`를 확인 → 배너 표시 → 버튼을 누르면 `seteuk-app.zip`을 받아 SHA-256 검증 후
`~/Library/Application Support/쓰담/code/<버전>/`에 풀고 재시작합니다. 앱 번들은 수정하지 않으므로 서명이 깨지지 않으며,
실행기는 번들 코드와 내려받은 코드 중 높은 버전을 실행합니다. **저장소는 public이어야** 사용자가 토큰 없이 업데이트를 받습니다.

### 코드 서명 (선택)
기본은 ad-hoc 서명이라 DMG 첫 실행 시 "그래도 열기"가 필요합니다(`install.sh` 경로는 불필요).
Apple Developer ID가 있으면 `SIGN_ID="Developer ID Application: …" macos/build_app.sh` 후 공증(notarytool)하면 경고 없이 열립니다.
