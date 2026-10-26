# -*- coding: utf-8 -*-
# 릴리스할 때 tools/release.sh 가 VERSION 을 올립니다.
VERSION = "1.10.15"

# 업데이트를 받아올 GitHub 저장소 ("소유자/저장소"). 비우면 업데이트 확인을 하지 않습니다.
# 저장소는 공개(public)여야 선생님 맥에서 토큰 없이 받아올 수 있습니다. (코드만 올라가고 학생 데이터는 올라가지 않음)
UPDATE_REPO = "hanseolhui/sseudam"

# 릴리스에 첨부하는 코드 묶음 파일 이름 (예전 버전이 이 이름을 찾으므로 바꾸지 않음)
UPDATE_ASSET = "seteuk-app.zip"

# 앱 셸(창·메뉴·Whisper 실행 파일이 든 .app) 버전. 셸이 이보다 낮으면 화면에서 '앱 업데이트'를 안내한다.
SHELL_REQUIRED = 5  # 5 = 기기 안 AI 도우미·쓰담 내장 AI(llama-server)가 든 앱
APP_ASSET = "Sseudam-mac.zip"
WHISPER_ASSET = "whisper-cli-arm64.zip"
