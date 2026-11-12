"""초안 줄이기 — AI 없이 문장 단위로 덜어낸다.

문장을 고쳐 쓰지 않는다. 통째로 남기거나 통째로 덜어낼 뿐이라 사실 · 숫자 · 주체가 바뀌지 않는다.
(2026-11-12 확인: 생각을 끈 작은 모델은 바이트를 맞추지 못했다 — docs/s2b/prompt-check-20261112)
"""
import re

import db

# 문장 끝: 마침표 · 물음표 · 느낌표 뒤의 공백. '3.5', 'y=2x+1.' 같은 것은 뒤에 공백이 없으면 나누지 않는다.
_SPLIT = re.compile(r"(?<=[.!?])\s+")
# 수행 범위를 한정하는 문장 (설정이 '그대로 적기'면 끝까지 지킨다)
_LIMITING = re.compile(r"않|못함|못하|못한|늦게|기한\s*(하루|이틀|뒤)|잘못|틀리|틀렸|미흡|부족|절반")
# 구체적인 사실의 표지: 숫자, 식 · 영문, 따옴표로 묶은 말
_CONCRETE = re.compile(r"\d|[A-Za-z]=|[A-Za-z]{2,}|['\"‘’“”]")
# 해석 · 평가로만 이루어지기 쉬운 말
_INTERPRET = re.compile(r"태도|역량|모습|관심|의미|돋보|드러|성장|자세|능력")


def sentences(text):
    return [s for s in _SPLIT.split((text or "").strip()) if s.strip()]


def _rank(s, keep_weak):
    """낮을수록 먼저 덜어낸다."""
    if keep_weak and _LIMITING.search(s):
        return 9
    r = 2
    if _CONCRETE.search(s):
        r += 2
    if _INTERPRET.search(s) and not _CONCRETE.search(s):
        r -= 1
    return r


def fit(text, limit, keep_weak=True):
    """limit 바이트 이하가 되도록 문장을 덜어낸다.
    돌려주는 값: (줄인 글, 덜어낸 문장 목록). 문장을 덜어내는 것만으로 맞출 수 없으면 (None, [])."""
    parts = sentences(text)
    if db.neis_bytes(" ".join(parts)) <= limit:
        return " ".join(parts), []
    keep = list(range(len(parts)))
    removed = []

    def size(idx):
        return db.neis_bytes(" ".join(parts[i] for i in idx))

    while size(keep) > limit:
        if len(keep) <= 1:
            return None, []
        low = min(_rank(parts[i], keep_weak) for i in keep)
        if low >= 9:      # 남은 것이 모두 지켜야 하는 문장
            return None, []
        cands = [i for i in keep if _rank(parts[i], keep_weak) == low]
        over = size(keep) - limit
        # 하나만 덜어 맞출 수 있으면 그중 가장 짧은 문장을, 아니면 가장 긴 문장을 덜어 남는 글을 많게 한다
        enough = [i for i in cands if db.neis_bytes(parts[i]) + 1 >= over]
        pick = min(enough, key=lambda i: (db.neis_bytes(parts[i]), -i)) if enough else max(cands, key=lambda i: (db.neis_bytes(parts[i]), i))
        keep.remove(pick)
        removed.append(pick)
    return " ".join(parts[i] for i in keep), [parts[i] for i in sorted(removed)]
