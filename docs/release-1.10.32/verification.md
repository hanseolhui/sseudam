# Android 1.10.32: 신규 구독 중단 안내

- Play 운영 버전 1.10.31(11031)의 구매 계정 보호와 입력 수정 위에 최소 판매중단 변경을 적용했다.
- 연결 화면에 `유료 상품 곧 오픈`을 표시하고 신규 상품 표시, 직접 구매 함수와 Billing 진입을 막는다.
- 기존 구매 복원을 위한 계정 토큰 조회, 영수증 제출, 구독 상태와 관리 동선은 유지한다.
- 기록, 명단, 외부 AI 프롬프트 복사와 결과 붙여넣기 등의 무료 기능을 변경하지 않는다.
- 11월 6일의 별도 미커밋 기록/학교 상품 작업은 포함하지 않는다.

## 검증

- Python 35개, Node 18개 통과.
- Android Play/GitHub debug 컴파일 통과.
- Android JUnit 26개 통과. 초기화 전 직접 구매와 Billing 진입, 기존 상품 조회를 막는 실행 테스트 3개를 포함한다.
- Play release AAB와 GitHub release APK의 R8 및 lintVital 빌드 통과.
- AAB 서명 검증 통과. 이전 1.10.31 AAB와 서명 인증서 SHA-256이 같다.
- Robolectric 실제 화면 시험 통과. 가상 명단·기록 및 프롬프트 복사/결과 붙여넣기, 연결 화면의 판매중단 안내 접근을 확인했다.
- 실제 고객 데이터, 유료 AI, 실제 결제는 사용하지 않았다. 실기기 구매 복원과 마이크 녹음은 별도 검증이 필요하다.

## 배포 파일

- `mobile/android/app/build/outputs/bundle/playRelease/app-play-release.aab`
  - SHA-256: `5ee6818cc88d13d5a6ea986b8d3b9de53f4f8735696b7bb1a47927bef87e77ec`
- `mobile/android/app/build/outputs/apk/github/release/app-github-release.apk`
  - 버전: 1.10.32, versionCode 11032.
  - SHA-256: `938edd61dff90de43f8dbae0120b07845a8c5b627fa0c572c6ac4373498851af`

## 플랫폼 구분

서버는 `toktok-server` PR #1을 통해 운영에 반영했다. Google Play `plus`의 month/half/year 기본 요금제는 기존 갱신을 유지한 채 신규 판매만 비활성화했다.

iOS의 신규 구매 가드도 소스에 포함하고 unsigned Release 빌드를 확인했다. 다만 공개 iOS 버전은 1.1.0, 저장소 설정은 1.2.0/build24이므로 App Store Connect의 심사·TestFlight 상태를 확인하기 전 번호를 추측해 업로드하지 않는다. Apple의 상품 판매 중단은 기존 갱신도 멈추므로 이 작업에서 실행하지 않았다.

데스크톱/GitHub/Windows 배포는 별도 플랫폼 빌드·패키지 검증과 출시가 필요하다. `tools/release.sh`는 Mac 공증, Windows, Android, GitHub 릴리스, Homebrew 변경까지 함께 수행하므로 이번 Android 제출만을 위해 실행하지 않는다.
