#!/bin/bash
# 쓰담.app 이 호출: 파이썬을 찾고, 가장 높은 버전의 코드로 서버를 실행한다.
# 종료 코드 3 = 파이썬(명령어 라인 도구) 없음 → 앱이 설치 안내를 띄움
SUPPORT="$HOME/Library/Application Support/쓰담"
mkdir -p "$SUPPORT"
LOG="$SUPPORT/server.log"
# 로그가 너무 커지면 정리
[ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt 5000000 ] && mv -f "$LOG" "$LOG.old"
# 파이썬 캐시(.pyc)는 앱 밖에 — 앱 안에 쓰면 코드 서명이 깨짐 (마이크 권한 등이 풀릴 수 있음)
export PYTHONPYCACHEPREFIX="$HOME/Library/Caches/쓰담/pycache"

PY=""
for c in /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
  [ -x "$c" ] || continue
  if [ "$c" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
  if "$c" -c "import sys, sqlite3; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || exit 3

RES="$(cd "$(dirname "$0")" && pwd)"
# 앱에 들어 있는 코드와 업데이트로 내려받은 코드 중 가장 높은 버전
CODE="$("$PY" - "$RES/app" "$SUPPORT/code" <<'PYEOF'
import os, re, sys
def ver(app):
    try:
        m = re.search(r'VERSION\s*=\s*"([^"]+)"', open(os.path.join(app, "version.py"), encoding="utf-8").read())
        return tuple(int(x) for x in re.findall(r"\d+", m.group(1))[:3])
    except Exception:
        return None
best, best_v = sys.argv[1], ver(sys.argv[1]) or (0,)
root = sys.argv[2]
if os.path.isdir(root):
    for d in os.listdir(root):
        app = os.path.join(root, d, "app")
        v = ver(app)
        if v and os.path.exists(os.path.join(app, "server.py")) and v > best_v:
            best, best_v = app, v
print(best)
PYEOF
)"
[ -n "$CODE" ] || CODE="$RES/app"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') 시작: $CODE ($PY)" >> "$LOG"
exec "$PY" "$CODE/server.py" >> "$LOG" 2>&1
