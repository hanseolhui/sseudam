# 쓰담 — 구조 설계

## 0. 설계 원칙 (납품 조건에서 나온 제약)

| 조건 | 설계 결정 |
|---|---|
| 개발자가 아닌 교사가 M1 맥북에어에서 혼자 사용 | **맥 앱(.app) + DMG / 한 줄 설치**. 내부는 macOS 기본 `python3`(표준 라이브러리만, pip 0개) + 브라우저 UI |
| 납품 후 유지보수 | **GitHub 릴리스 기반 앱 내 업데이트** — 개발자는 `tools/release.sh` 한 번, 교사는 버튼 한 번 |
| 녹음을 학생별·폴더별로 저장하기 싫음 | **음성메모 자동 가져오기**, **메모 앱 받아쓰기 가져오기**, **시간표로 학급 자동 지정** — 녹음만 하면 끝 |
| 납품자 API/서버 사용 안 함 | 모든 데이터는 맥 안(`data/` 폴더, SQLite)에 저장. 외부로 나가는 건 **본인 Gemini 키 호출**과 **본인 구글시트** 전송뿐 |
| 사용자는 ChatGPT/Gemini 월 2~3만 원 구독만 있음 | ① **API 모드**: AI Studio에서 무료로 발급되는 본인 Gemini API 키 사용 (구독과 별개, 무료 등급 존재) ② **수동 모드**: 키가 없어도 동작 — 프로그램이 프롬프트를 만들어주면 Gemini/ChatGPT 웹에 붙여넣고, 답을 다시 붙여넣는 방식 |
| M1 8GB, 저사양 | 로컬 Whisper 같은 무거운 모델 없음. 음성 인식은 Gemini(오디오 입력) 또는 외부 전사앱(클로바노트 등) 붙여넣기 |
| 학교 환경, 오프라인 가능성 | UI는 외부 CDN 없이 순수 HTML/JS/CSS. 차트도 직접 SVG로 그림 |
| 학생 개인정보 | 서버는 `127.0.0.1`에만 열림(같은 와이파이의 다른 기기 접근 불가). 자동 백업. 이름은 세특 본문에 쓰지 않도록 프롬프트에서 금지 |

## 1. 전체 흐름

```
[아이폰]                                  [맥 — 쓰담.app (백그라운드 로컬 서버)]
 음성메모 녹음 ──iCloud──▶ 음성메모 보관함 ─┐   (전체 디스크 접근 권한, 내장 전사문 있으면 사용)
 메모 앱 받아쓰기 ─iCloud─▶ 메모 앱 '세특' ─┼─▶ ① 보관  data/audio/YYYY/MM/…  + DB
 단축어/파일 저장 ─iCloud─▶ 쓰담 녹음 폴더 ──┤      학급 지정: 제목·파일명(2-3) → 시간표(녹음 시각) → AI가 본문에서
 드래그&드롭 / 전사문 붙여넣기 ────────────┘
                                              ▼
                                    ② 전사(STT)  아이폰 전사문 / 메모 텍스트면 생략, 아니면 내 맥 Whisper(기본·외부 전송 없음) 또는 Gemini
                                              ▼
                                    ③ 학생별 분리  Gemini(JSON) 또는 이름 기준 규칙(키 없을 때 자동)
                                              ▼   → 교사 확인 화면에서 재지정·수정
                                    ④ 관찰기록 DB (학생 × 날짜 × 수업/상담 × 원문 × 녹음 링크)
                                              ▼
                                    ⑤ 세특 초안 (학생별/일괄, 바이트·금지어 검사, 줄이기, 버전)
                                              ▼
                                    ⑥ 구글시트 자동 반영 + 드라이브 일일 백업(Apps Script) / 엑셀 / 표 복사 / CSV
```

한 녹음·메모 안에 여러 학생이 섞여 있어도 이름 언급 위치로 나누므로, 학생별 파일·폴더 지정이 필요 없다.

## 2. 폴더 구조

```
sseudam/ (GitHub 저장소 = 코드만)
├─ app/                 ← 업데이트 단위 (seteuk-app.zip)
│  ├─ server.py         HTTP 서버·API·정적파일·오디오(Range)
│  ├─ db.py             SQLite, 데이터 위치, NEIS 바이트
│  ├─ gemini.py         Gemini REST(생성, File API, 모델 목록·자동 대체, 재시도)
│  ├─ prompts.py        전사/분리/초안/줄이기 프롬프트, 금지어
│  ├─ pipeline.py       작업 큐, 결과 적용, 이름 매칭, 시간표 학급 추정, 규칙 분리
│  ├─ watcher.py        가져오기: 수신 폴더 / 음성메모 보관함(+tsrp 전사문) / 메모 앱(JXA)
│  ├─ update.py         GitHub 릴리스 확인·내려받기·검증·설치·재시작
│  ├─ sheets.py         엑셀/구글시트 데이터, 자동 동기화, 드라이브 백업·복원
│  ├─ xlsx.py           표준 라이브러리 .xlsx 작성기
│  ├─ whisper.py        내 맥 받아쓰기(whisper.cpp), 모델 내려받기
│  ├─ version.py        VERSION, UPDATE_REPO
│  ├─ google_apps_script.gs
│  └─ static/           index.html, app.js, style.css
├─ macos/               SseudamApp.swift(네이티브 셸), start_server.sh, bin/whisper-cli, build_app.sh, icon
├─ tools/build_shortcuts.py  아이폰 단축어 생성·서명 / tools/make_prompt_doc.py  프롬프트_모음.md
├─ tools/release.sh     버전업→빌드→태그·푸시→GitHub 릴리스
├─ install.sh           curl 한 줄 설치
└─ 사용설명서.md · README.md · ARCHITECTURE.md

~/Library/Application Support/쓰담/   (사용자 맥 — 저장소에 올라가지 않음)
├─ data/  seteuk.db, audio/, backups/
├─ code/<버전>/app/    앱 내 업데이트로 받은 코드 (최근 2개)
└─ server.log
```

## 2-1. 설치·업데이트 구조

- **쓰담.app** (1.2~): `Contents/MacOS/Sseudam`(Swift 네이티브 셸, 유니버설) — 자기 창(WKWebView)·메뉴·Dock.
  `Resources/start_server.sh`로 파이썬 서버를 자식 프로세스로 띄우고, 비정상 종료 시 재시작, ⌘Q 시 함께 종료.
  창을 닫아도 앱은 남아 아이폰 기록을 계속 받는다. 예전 버전 서버가 떠 있으면 끄고 새로 띄운다.
  `Resources/bin/whisper-cli`(whisper.cpp, Metal, 정적 링크) 포함.
- 실행기는 **번들 코드와 `code/<버전>` 중 가장 높은 버전**을 실행 → 앱 번들을 건드리지 않고 코드만 교체(서명 유지).
- 앱 내 업데이트: `GET api.github.com/repos/<repo>/releases/latest` → `seteuk-app.zip` 다운로드 → SHA-256(digest) 검증 → 압축 경로 검사 → 버전 일치 확인 → `code/<버전>`에 설치 → DB 백업 후 `execv`로 재시작.
- 앱 자체(실행기·아이콘 등)가 바뀌면 `install.sh` 재실행 또는 DMG 재설치. 데이터는 별도 위치라 유지.
- 데이터 위치는 1.0의 `프로그램폴더/data`에서 자동 이전.

## 3. 데이터베이스 (SQLite)

| 테이블 | 주요 컬럼 | 비고 |
|---|---|---|
| `classes` | id, year, semester, grade, class_no, subject, label | "2학년 3반 국어" |
| `students` | id, class_id, number, name, aliases, memo | aliases = 전사 오인식 대비 별칭(예: "민수, 김민서") |
| `recordings` | id, class_id, kind(수업/상담), title, recorded_at, audio_path, transcript, status, error | status: 보관됨→전사중→전사완료→분리중→확인필요→완료 |
| `notes` | id, student_id, recording_id, date, kind, category, content, evidence, use_in_draft | 학생별 관찰기록(세특 재료) |
| `drafts` | id, student_id, area, content, bytes, status(초안/확정), created_at | 버전 이력 보관 |
| `unmatched` | id, recording_id, name_heard, content | 명단과 매칭 안 된 언급 → 수동 지정 |
| `settings` | key, value | API 키, 모델, 바이트 한도, 문체 예시, 수신 폴더, 시트 URL, 음성메모·메모 앱 사용, 교시 시간, 시간표 |
| `imported` | source, ext_id, sig, body, recording_id | 음성메모·메모 중복 방지, 메모 덧붙임 감지 |
| `jobs` | id, op, params, status, message | AI 작업 큐 |

## 4. AI 작업 설계

모든 AI 작업은 **(프롬프트 생성) → (Gemini 호출 또는 수동 붙여넣기) → (결과 적용)** 3단계로 분리되어 있어,
API 모드와 수동 모드가 같은 코드를 공유합니다.

| 작업 | 입력 | 출력 형식 |
|---|---|---|
| transcribe | 오디오 + 학생 명단 | 텍스트(문단마다 [mm:ss]) |
| segment | 전사문 + 명단(번호·이름·별칭) | JSON `{class_hint, items:[{number,name,category,observation,evidence}], unmatched:[…]}` |
| draft | 학생 관찰기록 전체 + 과목 + 바이트 한도 + 문체 예시 + 교사 강조점 | 세특 본문 텍스트 |
| shorten | 초안 + 목표 바이트 | 줄인 본문 |

- 모델명은 설정에서 선택(모델 목록 API로 자동 불러오기). 지정 모델이 없어지면 사용 가능한 flash 모델로 자동 대체 → 납품 후 모델 단종에도 견딤
- 429(요청 한도) 시 대기 후 재시도. 학급 일괄 생성은 큐에서 순차 처리
- 명단 매칭: 번호+이름 → 이름 → 별칭 → 유사도(편집거리) 순

## 5. 세특 작성 규칙(프롬프트·검사기에 반영)

- 명사형 종결(~함, ~임, ~보임), 학생 이름·'학생은' 주어 생략
- 관찰된 사실 기반, 구체적 활동 → 역량/성장으로 연결, 과장·추측 금지
- 기재 금지 항목 검사: 교외 대회/수상, 공인어학시험, 논문, 특허, 도서출판, 해외활동, 부모 직업 등 → 경고 표시
- NEIS 바이트: 한글 3B, 영문·숫자·공백 1B, 줄바꿈 2B, 기본 한도 1500B(설정 변경 가능)

## 6. 화면 구성

0. 상단 **업데이트 배너** (새 버전 있을 때)
1. **대시보드** — 요약 수치, 학급별 진행률(관찰기록 있는 학생 비율, 초안 완료율), 주간 기록 추이 차트, 기록이 부족한 학생, 최근 녹음
2. **학급·학생** — 학급 추가, 명단 일괄 붙여넣기(NEIS 엑셀에서 '번호 이름' 복사), 별칭 편집
3. **녹음함** — 업로드/붙여넣기, 처리 상태, 전사문 보기·재생, 분리 결과 확인·수정
4. **학생 상세** — 관찰기록 타임라인(원본 녹음 재생), 세특 초안 생성·편집·바이트 카운터·버전
5. **세특 일괄** — 학급별 표, 일괄 생성, 표 복사/CSV/구글시트 전송
6. **설정** — Gemini 키·모델·연결 테스트, API/수동 모드, 바이트 한도, 문체 예시, **아이폰 기록 가져오기(3가지 경로·권한 안내)**, **시간표**, 구글시트, 백업, **업데이트**

## 6-1. 백업 3중화

| 위치 | 주기 | 내용 | 복원 |
|---|---|---|---|
| 이 맥 `data/backups` | 하루 1회(실행 시) + 업데이트·복원 직전 | DB 전체 | 설정 → 백업·복원 |
| 구글 드라이브 '쓰담 백업' | 하루 1회(연결 시) | DB zip, 최근 30개 | 설정 → 백업·복원 (앱이 드라이브에서 직접 받아옴) |
| 구글시트 | 바뀐 내용 5분 내 | 보기용 표(학급별 세특·관찰기록) | 수동 확인용 |

Apps Script 요청은 앱이 자동 생성한 토큰으로 보호(스크립트 복사 시 토큰이 들어감). 오디오 원본은 맥에만 보관.

## 7. 보안

- `127.0.0.1` 바인딩, Host 헤더 검사(DNS 리바인딩 방지), API 요청에 커스텀 헤더 요구(다른 웹사이트의 위조 요청 차단)
- API 키는 로컬 DB에만 저장, 화면에는 일부만 표시
- 참고: Gemini **무료 등급**은 입력 데이터가 구글 제품 개선에 쓰일 수 있음 → 결제 등록(유료 등급, 사용량 매우 적으면 월 수백 원 수준) 권장을 설명서에 명시

## 8. 기기 사이 글 기록 동기화 (녹음 제외)

- 위치: iCloud 쓰담 컨테이너 `Documents/동기화/<기기 id>.json` (맥 `~/Library/Mobile Documents/iCloud~kr~sseudam~app/Documents/동기화`).
- 기기마다 **자기 파일 하나만** 쓰고, 그 기기가 아는 전체 기록(학급·학생·관찰기록·초안)을 담는다. 읽는 쪽은 모든 파일을 합쳐 기록(uid)마다 `updated_at`이 가장 큰 것을 고른다. 지운 기록은 `deleted: true`로 남긴다. 그래서 쓰기 충돌이 없다.
- uid: 학급 `c-` + sha1(학년도|학기|학년|반|과목|유형)[:16], 학생 `s-` + sha1(학급uid|이름)[:16]. 맥과 폰에서 따로 만들어도 하나로 합쳐진다. 기록·초안은 무작위 uid.
- 맥: `app/sync_text.py` (20초마다). DB 행에 uid 열을 더하고, 변경 감지는 `sync_state`(내용 해시)로 해서 기존 쓰기 코드는 건드리지 않았다.
- 폰: `mobile/ios/Sseudam/SyncData.swift` (`DataStore`).
- 녹음은 기존 경로(iCloud `Documents`, 구글 드라이브, AirDrop)로 따로 간다. 폰이 받아쓴 글은 m4a의 가사(©lyr) 메타데이터로 실어 보내고, 맥 `watcher.extract_iphone_transcript`가 읽는다.
- 폰에서 이미 나눈 녹음(`notes.source` = 파일 이름)은 맥이 다시 나누지 않고 연결만 한다 (`pipeline.segment_after_transcript`).
- 윈도우·안드로이드: 같은 형식을 구글 드라이브로 주고받을 예정 (미구현).

## 9. AI 엔진과 요금제

| 엔진 | 요금 | 하는 일 | 상태 |
|---|---|---|---|
| 규칙 | 무료 | 이름·학년반·한글 숫자·동명이인·자모 1개 차이 이름으로 나누기 | 맥·폰 |
| 기기 안 AI (Foundation Models) | 무료 | 이름 없는 문장의 주인 정하기 (그 녹음에 나온 학생 중에서만) | 폰 (iOS 26+, 애플 인텔리전스) |
| 내 API 키 (BYOK) | 1회 결제 예정 | 학생 요약·초안 | 맥은 Gemini 키 사용 가능 / 폰은 구조만 (`OwnKeyEngine.enabled = false`) |
| 쓰담 플러스 | 구독 | 서버 받아쓰기·요약·초안·암호화 동기화 | 구조만 (`PlusEngine.enabled = false`) |

- 폰 화면은 `AIRouter.engine(for:)`만 부른다. 플러스 → 내 키 → 기기 안 AI 순으로 쓸 수 있는 엔진을 고르고, 없으면 그 기능을 숨긴다 (`mobile/ios/Sseudam/AIEngine.swift`).
- 밖으로 나가는 엔진(내 키·플러스)에는 학생 이름을 'OO'로 가려서 보낸다. 서버는 결과를 보관하지 않고, 사용자별·하루 상한을 둔다 (`수익모델_시뮬레이션.md` 참고).

### 9-1. 내 맥 AI (2026-10-24)
- 학생별 분리 엔진 `seg_engine`: auto(기본) | gemini | local | apple | rules. auto = Gemini 키 → 내 맥 AI 앱 → 기기 안 AI → 이름 기준.
- **기기 안 AI**: `macos/sseudam_ai.swift` → 앱 안 `Resources/bin/sseudam-ai` (Foundation Models, macOS 26+, Apple Intelligence). 파이썬 `app/localai.py` 가 `status`/`owners`/`generate` 로 호출.
- **내 맥 AI 앱**: Ollama(`127.0.0.1:11434/v1`)·LM Studio(`127.0.0.1:1234/v1`) OpenAI 호환. 주소는 localhost만 허용.
- 분리 방식(`pipeline.local_segment`): 이름이 나온 문장은 규칙, 이름 없는 문장만 AI가 '그 녹음에 이름이 나온 학생' 중에서 고름(아이폰 LocalAI와 동일). 30문장씩 나눠 처리, 실패하면 rule_segment.
- 세특 초안: Gemini 키가 없고 `draft_local=1`이면 내 맥 AI 앱으로(기기 안 AI는 초안엔 안 씀).
- **쓰담 AI 모델 (내장)**: 앱 안 `Resources/bin/llama-server`(llama.cpp 정적 빌드, Metal 내장, OpenSSL 없음 — `macos/bin/LLAMA_CPP_VERSION`). 설정에서 모델 받기(이어받기 지원) → `~/Library/Application Support/쓰담/models/llm/`. `local_ai_url = "builtin"`이면 쓸 때만 127.0.0.1:8781에 켜고 10분 쉬면 끔(앱 종료·SIGTERM 때도 끔, 다음 시작 때 남은 프로세스 정리).
  - 가볍게: Qwen3.5 4B Q4_K_M 2.7GB (8GB 맥) · 추천: Gemma 4 E4B Q4_K_M 5.0GB (16GB+). 2026-10-24 비교(이름 없는 문장 18개): Gemma 4 E4B 18 · Gemma 4 12B 17 · Qwen3.5 4B 16 · Qwen3.5 9B 16 · Apple 기기 안 AI 14 · Gemma 4 E2B 13 · Kanana 2 3B 11 · Qwen3.5 2B 7. Qwen3.5는 chat_template_kwargs enable_thinking=false 로 부름.
- 앱 셸 버전 5(`SHELL_REQUIRED`): 새 도우미·엔진은 코드 zip이 아니라 앱 전체 교체로만 들어가므로, 자동 업데이트가 코드 → 새 앱 순서로 설치.
