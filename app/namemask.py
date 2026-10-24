# -*- coding: utf-8 -*-
"""학생 이름 가리기 — 쓰담 플러스 AI로 보내기 전에 이름을 '학생1'처럼 바꾸고, 답이 오면 되돌린다.
우리 서버도 AI 회사도 실명을 보지 않게. 명단(학생 이름 · 다르게 들릴 수 있는 이름)에 있는 이름만 가린다."""
import re

import db

TOKEN = re.compile(r"학생(\d{1,4})")
# 되돌릴 때 받침에 맞춰 고칠 조사 (뒤에 한글이 바로 이어지면 조사가 아니므로 그대로)
PAIR = {"이": ("이", "가"), "가": ("이", "가"), "은": ("은", "는"), "는": ("은", "는"),
        "을": ("을", "를"), "를": ("을", "를"), "과": ("과", "와"), "와": ("과", "와"), "이랑": ("이랑", "랑"), "랑": ("이랑", "랑")}
TOKEN_P = re.compile(r"학생(\d{1,4})(?:(이랑|랑|[이가은는을를과와])(?![가-힣]))?")
# 이름 뒤에 붙는 조사 · 호칭
POST = "(?:이가|이는|이도|이를|이랑|이와|이의|이한테|이에게|이네|이야|이가요|한테|에게|께서|께|가|는|은|도|를|을|랑|와|과|의|야|아|씨|네|님|학생|군|양)"


class Masker:
    def __init__(self, students):
        self.back = {}          # 번호 → 실명
        pairs = []              # (가릴 글자, 학생 번호)
        given_seen = {}
        for i, s in enumerate(students, 1):
            name = (s.get("name") or "").strip()
            if not name:
                continue
            self.back[i] = name
            pairs.append((name, i))
            if len(name) >= 3:                       # 성 뺀 이름 (같은 이름이 둘이면 앞 학생)
                given_seen.setdefault(name[1:], i)
            for a in re.split(r"[,\s/·]+", s.get("aliases") or ""):
                if len(a) >= 2:
                    pairs.append((a, i))
        self.given = {g: i for g, i in given_seen.items() if len(g) >= 2}
        # 긴 것부터 (김민수 → 민수 순서)
        uniq = {}
        for text, i in sorted(pairs, key=lambda p: -len(p[0])):
            uniq.setdefault(text, i)
        self.map = dict(uniq)
        for g, i in self.given.items():
            self.map.setdefault(g, i)
        # 받아쓰기가 이름 사이에 띄어쓰기를 넣는 경우가 많아서("샘플 준이") 글자 사이 공백 하나는 허용
        spaced = lambda t: r"\s?".join(re.escape(ch) for ch in t)
        full = "|".join(spaced(t) for t in sorted(uniq, key=len, reverse=True))
        # 성 뺀 이름은 뒤에 조사·호칭이 오거나 글자가 끝날 때만 (지우개 · 하늘색 같은 낱말은 그대로)
        given = "|".join(spaced(g) for g in sorted(self.given, key=len, reverse=True) if g not in uniq)
        parts = ([full] if full else []) + (["(?:%s)(?=%s|[^가-힣]|$)" % (given, POST)] if given else [])
        self.rx = re.compile("|".join(parts)) if parts else None

    def mask(self, text):
        if not text or not self.rx:
            return text
        # 원래 글에 '학생3' 같은 말이 있으면 되돌릴 때 헷갈리므로 살짝 바꿔 둠
        text = TOKEN.sub(lambda m: "학생 " + m.group(1), text)
        return self.rx.sub(lambda m: "학생%d" % self.map[re.sub(r"\s", "", m.group(0))], text)

    def unmask(self, text):
        if not text:
            return text

        def fix(m):
            name = self.back.get(int(m.group(1)))
            if not name:
                return m.group(0)
            p = m.group(2) or ""
            if p:   # 실명 받침에 맞게 조사 고치기 (학생2가 → 김민준이, 학생3은 → 이수아는)
                last = ord(name[-1]) - 0xAC00
                batchim = 0 <= last <= 11171 and last % 28 != 0
                p = PAIR[p][0 if batchim else 1]
            return name + p
        return TOKEN_P.sub(fix, text)


def for_all_students():
    conn = db.connect()
    try:
        rows = db.rows(conn, "SELECT id, name, aliases FROM students ORDER BY id")
    finally:
        conn.close()
    return Masker(rows)
