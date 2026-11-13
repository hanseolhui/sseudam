# 쓰담 (sseudam) — 말로 담고, 글로 씁니다

수업·상담 중 선생님이 말로 남긴 학생 관찰을 학생별로 자동 정리하고, 학기말 학교생활기록부(교과 세특 · 행동특성 및 종합의견 · 자율·자치/동아리/진로활동) 초안을 뽑아 주는 교사용 프로그램. 맥·윈도우 + 아이폰·안드로이드 녹음 앱.

- **네이티브 맥 앱**(Swift/WKWebView 셸) — 자기 창·메뉴·Dock, 로그인 시 자동 실행
- **앱 안에서 받아쓰기**: whisper.cpp(Metal) 내장, 모델은 앱에서 내려받기 → 로컬 받아쓰기를 사용할 때 녹음을 외부 AI로 보내지 않음
- 아이폰 **음성메모** 자동 가져오기 · **메모 앱 받아쓰기** · 서명된 **단축어**(원탭 녹음 → iCloud 자동 연동)
- 기록 정리: 지원 기기의 기기 안 AI 또는 이름 기준 분리. 별도 로컬 텍스트 모델 설치 없음
- 세특 초안: 플러스 이용자는 클라우드 AI로 생성. 무료 사용자는 **프롬프트 복사 → ChatGPT·Gemini에서 작성 → 결과 붙여넣기 → 저장·수정**
- **구글시트 자동 반영 + 구글 드라이브 일일 백업/복원**(Apps Script, 토큰 보호), **엑셀(.xlsx) 내보내기**
- **iCloud·OneDrive 폴더 백업**: 기록 ZIP·엑셀과 함께 녹음 원본도 선택해서 보관. 음성 백업은 기본 꺼짐이며, 따로 켜면 앱 실행 중 한 시간마다 새 파일과 변경 파일을 확인
- 시간표로 학급 자동 지정, 대시보드, NEIS 바이트 계산
- 서버는 표준 라이브러리만 쓰는 Python 3.8+ (외부 의존성 0)
- 맥의 기록 원본은 `~/Library/Application Support/쓰담/data`에 저장 — 외부 AI·구글시트·클라우드 백업을 사용하면 해당 경로로도 내용 전송. 이 저장소에는 코드만 있음

사용자 안내: [사용설명서.md](사용설명서.md) · [녹음 원본 백업·복원 안내](docs/클라우드-녹음-백업.md) · 구조: [ARCHITECTURE.md](ARCHITECTURE.md)

지원 대상은 **Windows 10·11 x64, macOS 12 이상, iOS·iPadOS 16 이상 아이폰·아이패드, Android 8 이상 안드로이드폰**입니다. 맥의 로컬 Whisper 받아쓰기는 M1 이상, 기기 내 AI 학생별 정리는 macOS 26 이상과 Apple Intelligence 준비가 필요합니다. Intel 맥은 텍스트 가져오기 또는 별도 Gemini API를 통한 온라인 받아쓰기를 사용합니다. Windows ARM·32비트, Linux·Chromebook은 현재 정식 지원 대상이 아닙니다. [기기별 자세한 조건](https://apps.seoriarts.com/sseudam-guide#devices)

기록 조회·편집·로컬 백업과 모델 준비가 끝난 로컬 받아쓰기는 오프라인으로 사용할 수 있습니다. 새 플러스 AI 초안, 로그인·구매 확인, QR 연동·기기 간 동기화, 클라우드 업로드에는 인터넷이 필요합니다. 같은 계정 로그인만으로 기록이 동기화되지는 않으며, 폴더에 백업 사본을 저장한 상태와 클라우드 업로드 완료도 다릅니다. [오프라인·온라인 상세 안내](https://apps.seoriarts.com/sseudam-guide#offline-online)

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


### 학기 마감·외부 초안 검토 (2026-11-01)

- 초안 → 학기 마감 점검: 현재 학기의 모든 학급·기재 영역을 기록 없음, 초안 없음, 검토 필요, 분량 초과, 완료로 확인합니다. 확정 후 새 초안이 생기면 완료로 간주하지 않습니다.
- 외부에서 만든 초안 붙여넣기 → 학생별로 비교하기: 이전 내용과 비교하고 글자·바이트 수를 확인한 뒤 선택한 학생만 새 버전으로 저장합니다. 문단과 기존 확정본을 보존합니다.
- 비교 후 다른 초안이 저장되면 재확인을 요구합니다. 기존 버전은 학생 화면의 버전 기록에서 다시 불러올 수 있습니다.
