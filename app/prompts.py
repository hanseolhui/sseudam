# -*- coding: utf-8 -*-
"""AI 프롬프트. API 모드와 수동(복사·붙여넣기) 모드가 같은 문구를 사용한다."""

FORBIDDEN_TERMS = [
    "토익", "TOEIC", "토플", "TOEFL", "텝스", "TEPS", "HSK", "JLPT", "DELF", "IELTS",
    "교외", "외부 대회", "올림피아드", "경시대회", "공모전", "수상", "입상", "금상", "은상", "동상", "대상을",
    "논문", "학회", "특허", "출판", "저서", "발명",
    "해외", "어학연수", "유학",
    "부모", "아버지", "어머니", "아빠", "엄마", "가정형편", "직업이",
    "학원", "과외", "인강",
]


def roster_text(students):
    if students is None:
        return "[여기에 학생 명단을 붙여넣으세요 — 한 줄에 '번호 이름' (예: 3 김민수)]"
    lines = []
    for s in students:
        line = "%s번 %s" % (s.get("number") if s.get("number") is not None else "-", s["name"])
        if s.get("class_label"):
            line = "[%s] %s" % (s["class_label"], line)
        if s.get("aliases"):
            line += " (다르게 들릴 수 있는 이름: %s)" % s["aliases"]
        lines.append(line)
    return "\n".join(lines) if lines else "(명단 없음)"


def transcribe(kind, class_label, students):
    context = "수업 중 교사가 학생들을 관찰·평가하며 말한 내용" if kind == "수업" else "교사와 학생의 개별 상담"
    return """다음 오디오는 한국 %s의 %s을(를) 녹음한 것입니다.
오디오를 한국어로 빠짐없이 그대로 받아 적어 주세요.

규칙
- 요약하지 말고 들리는 말을 그대로 적을 것. 불필요한 추임새(음, 어)는 생략 가능.
- 말의 흐름이 바뀌거나 학생이 바뀔 때마다 줄을 바꾸고, 각 문단 앞에 [분:초] 시각을 표시.
- 학생 이름은 아래 명단의 표기를 우선 사용. 명단에 없는 이름은 들리는 대로 적기.
- 교사와 학생의 말이 구분되면 "교사:", "학생:"을 앞에 붙이기.
- 설명이나 머리말 없이 전사문만 출력.

학급: %s
학생 명단
%s
""" % ("학교", context, class_label or "미지정", roster_text(students))


SEGMENT_SYSTEM = "너는 한국의 선생님(학교 · 유치원 · 학원 · 과외 · PT · 필라테스 강사)이 말로 남긴 학생 · 회원 관찰기록을 정리하는 조수다. 반드시 지시된 JSON만 출력한다."


def segment(kind, class_label, students, transcript, date):
    return """아래는 교사가 %s 중 학생들에 대해 말한 내용을 받아 적은 전사문입니다.
학생 명단과 대조하여 학생별 관찰 내용을 분리해 주세요.

[작업 규칙]
1. 교사가 특정 학생을 이름(또는 번호, 성을 뺀 이름)으로 언급하면 그 뒤의 평가·관찰 내용을 그 학생에게 배정.
   이름이 다시 나오지 않아도 다른 학생으로 넘어가기 전까지의 내용은 같은 학생의 것으로 봄.
2. 전사 오류로 이름이 조금 다르게 적혔으면 명단에서 가장 비슷한 학생으로 배정 (예: '김민서'→'김민수').
3. 명단에 없는 이름이거나 판단이 어려우면 unmatched에 넣음.
4. observation: 교사가 관찰한 사실(활동, 태도, 발언, 결과물, 성장)을 1~3문장으로 정리.
   교사의 말에 없는 내용을 지어내지 말 것. 문장은 '~함', '~임', '~보임' 같은 명사형 종결.
5. evidence: 근거가 된 전사문 원문 일부를 그대로 발췌(최대 200자).
6. category: 다음 중 하나 — 발표, 토론, 탐구, 과제, 수업태도, 협업, 질문, 성장, 상담, 기타
7. 한 학생이 여러 번 언급되면 내용별로 여러 항목으로 나누어도 됨.
8. 학급이 언급되면(예: '2학년 3반') class_hint에 적기.
9. 수업 진행 발언, 출결 호명처럼 평가 내용이 없는 언급은 제외.
10. 학생 관찰이 아닌 녹음(교사 회의, 개인 메모·할 일, 업무 통화, 수업 내용 설명만 있는 경우 등)이면
    items와 unmatched를 비우고 "general": true 로 표시.
11. 한 교시를 통째로 녹음한 경우 대부분이 수업 설명·진행 발언이고 학생 관찰은 중간중간 짧게 나옴.
    수업 설명, 질문에 답해 주는 설명, 출석·질서 지도("앉아", "조용히")는 무시하고 학생에 대한 관찰·평가만 뽑을 것.
    학생 관찰이 하나라도 있으면 "general": false.

[출력 형식 — 이 JSON만 출력]
{"class_hint": "", "general": false, "items": [{"number": 3, "name": "김민수", "category": "발표", "observation": "...", "evidence": "..."}], "unmatched": [{"name_heard": "...", "category": "기타", "observation": "...", "evidence": "..."}]}

[기록 정보] 날짜: %s / 유형: %s / 학급: %s

[학생 명단]
%s

[전사문]
%s
""" % (kind, date or "", kind, class_label or "미지정", roster_text(students), transcript)


DRAFT_SYSTEM = "너는 한국 학교생활기록부(세특·행동특성·창의적 체험활동) 작성을 돕는 전문 조수다."

# 영역별 작성 지침 — 학교생활기록부 기재요령의 일반 원칙을 요약
AREA_GUIDE = {
    "subject": ("%(subject)s 과목 '세부능력 및 특기사항'",
                "- 수업 중 활동(발표·토론·탐구·과제·질문)에서 드러난 학업 역량, 과목에 대한 이해와 사고 과정을 중심으로.\n"
                "- 구체적 활동(무엇을 했는지) → 과정에서 드러난 태도·사고 → 역량·성장 순으로 연결."),
    "individual": ("'개인별 세부능력 및 특기사항'",
                   "- 교과 수업 밖에서 드러난 개인의 학업 관련 특기사항(자기주도 학습, 탐구, 학업 태도)을 중심으로."),
    "behavior": ("'행동특성 및 종합의견'",
                 "- 담임교사가 1년간 관찰한 학생의 인성·태도·공동체 역량·자기관리·성장 과정을 종합적으로.\n"
                 "- 구체적 사례를 근거로 쓰고, 부족한 점은 노력과 변화 가능성 중심으로 긍정적으로 서술.\n"
                 "- 학생을 한 사람으로 그려 내듯 전체를 아우르는 종합 의견으로 마무리."),
    "autonomy": ("창의적 체험활동 '자율·자치활동 특기사항'",
                 "- 학급 회의, 학생 자치, 학교 행사 등에서 맡은 역할과 참여 과정, 기여, 그 속에서 드러난 공동체 역량을 중심으로."),
    "career": ("창의적 체험활동 '진로활동 특기사항'",
               "- 진로 탐색 활동, 관심 분야를 깊이 알아보는 과정, 활동 후 생각의 변화와 진로 성숙을 중심으로.\n"
               "- 특정 대학·학과명은 쓰지 말 것."),
    "club": ("창의적 체험활동 '동아리활동 특기사항'%(club)s",
             "- 동아리 활동에서 맡은 역할, 참여 과정, 결과물, 협업과 기여, 드러난 역량을 중심으로.\n"
             "- 동아리 이름은 별도 칸에 적히므로 본문에 반복하지 말 것."),
}


# 학교 밖 선생님의 글 — (제목, 초점, 문체, 받는 사람에게 보내는 글인지)
OTHER_GUIDE = {
    "kinder_obs": ("유아 관찰 기록",
                   "- 놀이와 일상에서 관찰된 유아의 말 · 행동 · 선택을 사실 그대로 쓰고, 누리과정 5개 영역(신체운동·건강, 의사소통, 사회관계, 예술경험, 자연탐구) 중 관련 영역을 괄호로 짚기.\n"
                   "- 평가나 비교 대신 '무엇을 하며 어떤 모습을 보였는지' 중심으로.",
                   "'~함', '~보임' 같은 관찰 기록 문체", False),
    "kinder_eval": ("학기말 유아 발달 종합 의견",
                    "- 한 학기 동안 관찰된 모습을 누리과정 5개 영역에 걸쳐 고르게 엮고, 유아가 즐겨 하는 놀이와 성장한 점, 앞으로 함께 지원할 점을 따뜻하게.\n"
                    "- 부족한 점은 '~하는 경험이 늘면 좋겠음'처럼 성장 가능성으로.",
                    "'~함', '~보임' 같은 기록 문체", False),
    "kinder_home": ("학부모에게 보내는 알림장 글",
                    "- 오늘(이번 주) 아이가 놀이하며 보인 구체적인 모습 한두 가지를 생생하게 전하고, 가정에서 함께 이야기 나눠 볼 거리를 한 줄 덧붙이기.",
                    "학부모님께 쓰는 다정한 존댓말(~했어요, ~답니다)", True),
    "lesson_report": ("학부모에게 보내는 학습 리포트",
                      "- 이번 기간 배운 내용, 학생이 잘한 점(구체적인 문제 · 장면), 보완할 점, 다음 기간 학습 계획 순서로.\n"
                      "- 성적 · 점수는 관찰기록에 있을 때만 쓰고, 다른 학생과 비교하지 말 것.",
                      "학부모님께 쓰는 정중한 존댓말(~했습니다, ~할 예정입니다)", True),
    "lesson_msg": ("수업 뒤 학부모에게 보내는 피드백 문자",
                   "- 오늘 수업에서 한 것, 학생이 잘한 점 한 가지, 집에서 해 오면 좋을 것 한 가지를 짧게.",
                   "학부모님께 보내는 짧은 문자 존댓말(~했어요)", True),
    "fit_log": ("회원 수업 일지",
                "- 오늘 한 운동 · 동작, 자세에서 좋아진 점과 교정한 점, 회원의 컨디션 · 불편함, 다음 수업 목표 순서로.\n"
                "- 무게 · 횟수 · 세트 · 시간은 관찰기록에 있을 때만 숫자로 쓰기.",
                "'~함', '~필요' 같은 기록 문체", False),
    "fit_report": ("회원에게 보내는 진행 리포트",
                   "- 그동안의 수업에서 좋아진 점(자세 · 가동 범위 · 체력 · 습관), 아직 신경 쓸 점, 다음 기간 목표와 집에서 할 운동 한두 가지를 구체적으로.\n"
                   "- 진단 · 처방처럼 들리는 의학적 표현은 쓰지 말고, 통증이 있으면 '전문가 상담을 권함' 정도로.",
                   "회원님께 쓰는 정중하고 응원하는 존댓말(~하셨어요)", True),
    "fit_msg": ("수업 뒤 회원에게 보내는 메시지",
                "- 오늘 수업에서 잘하신 점 한 가지, 다음에 신경 쓸 점 한 가지, 집에서 할 간단한 동작이나 회복 팁 한 가지를 짧게.",
                "회원님께 보내는 짧은 메시지 존댓말(~하셨어요)", True),
}


def draft_system(area):
    if area in OTHER_GUIDE:
        return "너는 선생님 · 강사가 학생 · 회원에 대해 남긴 관찰기록으로 기록 · 리포트 · 메시지를 쓰는 조수다. 관찰기록에 없는 사실은 지어내지 않는다."
    return DRAFT_SYSTEM


def draft_other(student, class_info, notes, settings, extra, area, context, target):
    """유치원 · 학원 · 과외 · PT · 필라테스 — 생기부 규칙(명사형 종결 · 사교육 금지 등) 없이 받는 사람에 맞춘 글."""
    import db, pipeline
    title, focus, tone, to_person = OTHER_GUIDE[area]
    limit = int(target) if target else db.area_limit(area, settings)
    approx = int(limit / 3 * 0.95)
    who = "회원" if area.startswith("fit_") else ("유아" if area.startswith("kinder_") else "학생")
    lines = []
    for n in notes:
        line = "%s" % strip_names(pipeline.strip_class_words(n["content"]), student)
        if n.get("evidence"):
            line += "  (원문: %s)" % strip_names(n["evidence"][:160], student)
        lines.append("- [%s] %s" % (n.get("date") or "", line))
    out = """%s 초안을 작성해 주세요.

[이 글의 초점]
%s

[작성 원칙]
- 아래 관찰기록에 있는 사실만 근거로. 기록에 없는 활동 · 성과 · 숫자 · 대화는 지어내지 말 것.
- 문체: %s.
- %s
- 막연한 칭찬어만 늘어놓지 말고 관찰된 장면을 근거로.
- 건강 · 가정사 같은 민감한 내용은 관찰기록에 있어도 꼭 필요한 만큼만, 조심스럽게.
- 분량: 한글 약 %d자 이내(%d바이트). 기록이 적으면 그만큼 짧게.
- 머리말 · 설명 · 따옴표 없이 본문만 출력.
""" % (title, focus, tone,
       ("받는 분을 부르는 말로 시작해도 되지만, 이름 자리는 'OO'으로 두기." if to_person
        else "%s 이름이나 '%s은'이라는 주어는 쓰지 말 것." % (who, who)),
       approx, limit)
    ctx = context or {}
    if (ctx.get("topic") or "").strip():
        out += "\n[수업 정보] %s\n" % ctx["topic"].strip()
    guidance = (settings.get("draft_guidance") or "").strip()
    if guidance:
        out += "\n[선생님의 추가 지침]\n%s\n" % guidance
    if extra:
        out += "\n[이번에 특히 강조할 점]\n%s\n" % extra
    out += "\n[수업] %s\n" % (class_info.get("label") or class_info.get("subject") or "")
    out += "[%s] %s (이름은 본문에 쓰지 말 것)\n" % (who, student.get("number") or "-")
    if student.get("memo"):
        out += "[메모] %s\n" % student["memo"]
    out += "\n[관찰기록 %d건]\n%s\n" % (len(notes), "\n".join(lines) if lines else "(기록 없음)")
    return out


def strip_names(text, student):
    """관찰기록 속 학생 이름(성 뺀 이름 포함)을 지워서 AI가 본문에 이름을 쓰지 않게."""
    import re
    name = (student or {}).get("name") or ""
    t = text or ""
    for n in sorted({name, name[1:] if len(name) >= 3 else ""} - {""}, key=len, reverse=True):
        t = re.sub(re.escape(n) + r"(이가|이는|이도|이를|이랑|이|가|는|은|도|를|을|랑|와|과|의)?\s*", "", t)
    return t.strip()


def clean_draft(text, student=None):
    """AI 초안에서 세특에 쓰면 안 되는 군더더기를 걸러낸다: 날짜·'오늘', '학생은', 학생 이름, 머리말."""
    import re
    t = (text or "").strip().strip('"').strip()
    t = re.sub(r"^```\w*\s*|\s*```$", "", t).strip()
    t = re.sub(r"^(세특\s*초안|초안|답변)\s*[:：]\s*", "", t)
    # 날짜: 2026년 10월 24일 / 2026 년 10 월 24 일 / 10월 24일 / 2026-10-24 / 2026.10.24 (+ '에', '의')
    t = re.sub(r"(\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일(\s*\([월화수목금토일]\))?\s*(에|의|에는)?\s*", "", t)
    t = re.sub(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}\s*(에|의)?\s*", "", t)
    t = re.sub(r"(오늘|어제|금일|이번\s*시간)(의|에|은|는)?\s+", "", t)
    # 반·번호 말 ('육반', '2학년 6반', '3번')
    t = re.sub(r"((?<![가-힣])([일이삼사오육]|\d)\s*학년\s*)?(?<![가-힣\d])(십?[일이삼사오육칠팔구]|\d{1,2})\s*반(?![가-힣])\s*", "", t)
    if student:
        t = strip_names(t, student)
    t = re.sub(r"^(이\s*)?학생은\s*", "", t)
    t = re.sub(r"([,.]\s*)(이\s*)?학생은\s+", r"\1", t)   # 문장 중간의 '학생은'도
    t = re.sub(r"\s{2,}", " ", t).replace(" .", ".").strip()
    return t


def draft(student, class_info, notes, settings, extra="", area="subject", context=None, target=None, deep=False):
    import db
    if area in OTHER_GUIDE:
        return draft_other(student, class_info, notes, settings, extra, area, context, target)
    limit = db.area_limit(area, settings)
    if target:   # 학생별로 정한 분량이 있으면 그걸 씀
        limit = int(target)
    approx_chars = int(limit / 3 * 0.95)
    subject = (class_info.get("subject") or settings.get("teacher_subject") or "해당 교과")
    title_t, guide_t = AREA_GUIDE.get(area, AREA_GUIDE["subject"])
    title = title_t % {"subject": subject, "club": (" (동아리: %s)" % class_info["subject"]) if class_info.get("subject") else ""}
    note_lines = []
    for n in notes:
        # 날짜는 넘기지 않음 — 작은 AI가 '2026년 10월 24일'처럼 본문에 옮겨 적는 걸 막기 위해 (세특엔 날짜를 쓰지 않음)
        tag = "[%s%s]" % (n.get("kind") or "", ("/" + n["category"]) if n.get("category") else "")
        import pipeline
        line = "%s %s" % (tag, strip_names(pipeline.strip_class_words(n["content"]), student))
        if n.get("evidence"):
            line += "  (원문: %s)" % strip_names(n["evidence"][:160], student)
        note_lines.append("- " + line)
    style = (settings.get("style_examples") or "").strip()
    guidance = (settings.get("draft_guidance") or "").strip()
    grade = ("%s학년 " % class_info["grade"]) if class_info.get("grade") else ""
    out = """%s학교생활기록부 %s 초안을 작성해 주세요.

[이 영역의 초점]
%s

[작성 원칙]
- 아래 교사의 관찰기록에 있는 사실만 근거로 작성. 기록에 없는 활동·성과·역량을 지어내지 말 것.
- 문장은 '~함', '~임', '~보임', '~돋보임' 등 명사형 종결. 학생 이름이나 '학생은'이라는 주어를 쓰지 말 것.
- 날짜·요일·시각·'오늘'·'이번 시간' 같은 기록 시점, 다른 교사의 이름이나 '○○ 교사의 요청에 따라' 같은 말, 녹음·메모라는 말은 쓰지 말 것.
- 막연한 칭찬어(성실함, 우수함)만 나열하지 말고 관찰된 근거와 함께 서술.
- **요약하지 말고 세특 문장으로 새로 쓰기.** 관찰기록을 그대로 옮기지 말고, 다음 흐름으로 서술:
  ① 어떤 수업·활동 상황이었는지(수업 정보가 있으면 그 맥락) → ② 학생이 구체적으로 한 행동·발언·선택
  → ③ 그 행동에서 드러나는 역량·태도(이 수업에서 기르는 역량과 연결) → ④ 성장·의미.
- **절대 지어내지 말 것**: 관찰기록에 없는 경기·장면·대화·결과·숫자·역할(예: '전략적 판단이 미흡하자 휴식을 제안함' 같은 일)은 쓰지 않음.
  해석은 '이 행동이 어떤 태도·역량을 보여 주는지'까지만. 확실하지 않으면 쓰지 않음.
- 기록이 여러 건이면 공통된 강점으로 묶어 한 흐름의 글로 엮기. 같은 내용이 두 번 있으면 한 번만.
- 꾸밈을 아낄 것: '인상적임', '돋보임', '탁월함' 같은 평가어는 글 전체에서 두 번 이하, 같은 말은 반복하지 말 것.
  평가어는 반드시 그 근거가 된 관찰 사실 바로 뒤에만. 기록에 없는 탐구 단계(가설 설정, 변인 통제, 추가 조사 등)를 덧붙이지 말 것.
- 상담 기록은 학업·진로·성장과 관련된 내용만 활용하고, 가정사·건강·교우 갈등 등 민감한 개인사는 쓰지 말 것.
- 기재 금지: 교외 대회·수상, 공인어학시험 점수, 논문·학회, 특허, 도서 출간, 해외 활동, 부모의 직업·사회경제적 지위, 사교육, 특정 대학·기관·상호명.
- 분량: NEIS 기준 %d바이트 이내(한글 약 %d자 이내), 한 문단, 줄바꿈 없이. 기록이 충분하면 한도의 80~95%%까지 쓰고,
  **기록이 적으면 그만큼 짧게** 쓸 것 (분량을 채우려고 내용을 만들어 내지 말 것).
- 예시(형식만 참고, 내용은 쓰지 말 것) — 관찰: "모둠 실험에서 측정값이 이상하자 다시 재 보자고 함"
  → 세특: "산과 염기 중화 실험에서 모둠의 측정값이 예상과 다르게 나오자 오차의 원인을 짚어 보고 측정을 다시 하자고 제안함. 결과를 그대로 받아들이기보다 근거를 확인하려는 태도에서 과학적 탐구 역량이 돋보이며, 모둠원과 측정 절차를 함께 점검하며 협력적으로 문제를 해결하는 모습을 보임."
- 머리말·설명·따옴표 없이 본문만 출력.
""" % (grade, title, guide_t, limit, approx_chars)
    ctx = context or {}
    lesson = []
    if (ctx.get("topic") or "").strip():
        lesson.append("- 수업 내용(종목·단원): %s → 글의 활동 맥락으로 꼭 넣기 (예: '농구 3대3 리그전에서 …')" % ctx["topic"].strip())
    if (ctx.get("competencies") or "").strip():
        lesson.append("- 이 수업에서 기르는 역량: %s → 관찰된 행동이 이 역량 중 무엇을 보여 주는지 연결해서 쓰기" % ctx["competencies"].strip())
    if (ctx.get("philosophy") or "").strip():
        lesson.append("- 교사의 수업 철학: %s → 이 관점에서 학생의 어떤 모습을 의미 있게 보는지 반영하기" % ctx["philosophy"].strip())
    if lesson:
        # 작은 AI도 놓치지 않게 지시문 맨 앞쪽(제목 바로 아래)에 넣는다
        block = ("\n[수업 정보 — 반드시 초안에 반영할 것. 단, 관찰기록에 없는 활동·성과를 지어내지는 말 것]\n%s\n"
                 % "\n".join(lesson))
        out = out.replace("\n[이 영역의 초점]", block + "\n[이 영역의 초점]", 1)
    if deep:
        # 쓰담 플러스 '정성 초안': 사실은 늘리지 않되, 의미를 깊게 풀어 분량을 채움
        out += ("\n[정성 초안 — 더 깊게]\n"
                "- 분량: 한글 **최소 %d자 이상, %d자 이하**(%d바이트 한도의 85~95%%). 짧게 끝내지 말 것. 단, 관찰 사실을 새로 만들지 말고\n"
                "  ① 수업 상황과 과제의 의미 ② 학생이 한 행동의 구체적인 과정 ③ 그 행동이 보여 주는 역량을 수업의 성취 역량과 연결한 해석\n"
                "  ④ 다음 배움으로 이어질 성장 방향을 차례로 깊게 풀어 써서 채울 것.\n"
                "- 기록이 아주 적으면(1~2건) 억지로 늘리지 말고 해석을 충실히 한 만큼만 쓸 것.\n"
                "- 문장마다 어떤 관찰 사실에 근거했는지 분명해야 함. 교사가 그대로 옮겨 적어도 될 만큼 완성된 문장으로.\n"
                % (int(approx_chars * 0.9), approx_chars, limit))
    if guidance:
        out += "\n[교사의 추가 지침]\n%s\n" % guidance
    if style:
        out += "\n[문체 참고 예시 — 문체만 참고하고 내용은 베끼지 말 것]\n%s\n" % style
    if extra:
        out += "\n[이번 학생에 대해 특히 강조할 점]\n%s\n" % extra
    out += "\n[학교급] %s\n" % (settings.get("school_level") or "고등학교")
    out += "[학생] %s번 (이름은 본문에 쓰지 말 것)\n" % (student.get("number") or "-")
    if student.get("memo"):
        out += "[교사 메모] %s\n" % student["memo"]
    out += "\n[관찰기록 %d건]\n%s\n" % (len(notes), "\n".join(note_lines) if note_lines else "(기록 없음)")
    return out


def shorten(text, target_bytes, current_bytes):
    return """다음 학교생활기록부 세특 문장을 NEIS 기준 %d바이트 이하(한글 약 %d자 이하)로 줄여 주세요.
현재 %d바이트입니다. 핵심 활동과 역량 서술은 남기고 중복·수식어를 덜어내세요.
명사형 종결(~함, ~임)을 유지하고, 새로운 내용을 추가하지 말고, 본문만 출력하세요.

%s
""" % (target_bytes, int(target_bytes / 3 * 0.95), current_bytes, text)


def check_forbidden(text):
    found = []
    low = (text or "").lower()
    for t in FORBIDDEN_TERMS:
        if t.lower() in low and t not in found:
            found.append(t)
    return found


# ───────────────────────── 프롬프트 안내 (웹 채팅에서 직접 쓰기) ─────────────────────────

def gem_instructions(settings):
    limit = int(settings.get("byte_limit") or 1500)
    return """너는 한국 %s 교사의 학교생활기록부 작성(교과 세특, 행동특성 및 종합의견, 자율·자치·동아리·진로활동 특기사항)을 돕는 조수다.

[내가 주는 것]
- 수업 중 학생들을 관찰하며 말한 녹음의 전사문, 또는 학생별로 정리된 관찰기록

[네가 하는 일]
1. 전사문을 주면: 학생 이름이 언급된 곳을 기준으로 학생별 관찰 내용을 나눈다. 명단을 주면 명단과 대조하고, 명단에 없는 이름은 따로 표시한다.
2. 한 학생의 관찰기록과 영역(예: 교과 세특, 행동특성, 동아리)을 주면: 그 영역에 맞는 초안을 쓴다.
   - 교과 세특: 수업 중 학업 역량과 사고 과정 / 행동특성: 인성·태도·공동체 역량·성장의 종합 의견
   - 자율·자치: 맡은 역할과 공동체 기여 / 동아리: 역할·과정·결과물·협업 / 진로: 탐색 과정과 진로 성숙
3. "줄여줘"라고 하면: 같은 내용을 더 짧게 다듬는다.

[세특 작성 원칙]
- 관찰기록에 있는 사실만 근거로 쓴다. 없는 활동·성과·역량을 지어내지 않는다.
- 구체적 활동 → 과정에서 드러난 태도·사고 → 역량·성장 순으로 자연스럽게 연결한다.
- 문장은 '~함', '~임', '~보임' 등 명사형으로 끝낸다. 학생 이름이나 '학생은'이라는 주어를 쓰지 않는다.
- 막연한 칭찬(성실함, 우수함)만 나열하지 말고 관찰된 근거와 함께 쓴다.
- 상담 내용은 학업·진로 관련만 쓰고 가정사·건강·교우관계 등 민감한 개인사는 쓰지 않는다.
- 기재 금지: 교외 대회·수상, 공인어학시험, 논문·학회, 특허, 도서 출간, 해외 활동, 부모 직업·사회경제적 지위, 사교육, 특정 대학·기관·상호명.
- 분량: 교과 세특은 NEIS 기준 %d바이트 이내(한글 약 %d자). 다른 영역은 내가 알려주는 분량을 따른다. 한 문단, 줄바꿈 없이.
- 결과는 머리말·설명 없이 본문만 준다.%s""" % (
        settings.get("school_level") or "고등학교", limit, int(limit / 3 * 0.95),
        ("\n\n[교사의 추가 지침]\n" + settings["draft_guidance"].strip()) if (settings.get("draft_guidance") or "").strip() else "")


def guide(settings):
    """프롬프트 안내 화면·문서에 쓰는 템플릿 목록."""
    placeholder_note = [{"date": "[날짜]", "kind": "수업", "category": "", "content": "[여기에 이 학생의 관찰기록을 붙여넣으세요 — 쓰담 학생 화면의 '관찰기록 복사' 버튼]", "evidence": ""}]
    return [
        {"key": "gem", "title": "① 한 번만 설정: Gemini 'Gem' / ChatGPT 'GPT' 만들기 (추천)",
         "when": "매번 긴 프롬프트를 붙여넣기 귀찮을 때. 한 번 만들어 두면 이후엔 자료만 붙여넣으면 됩니다.",
         "steps": ["Gemini: gemini.google.com → 왼쪽 'Gem 탐색' → '새 Gem 만들기' → 이름 '세특 도우미' → '안내' 칸에 아래 내용 붙여넣기 → 저장",
                   "ChatGPT: chatgpt.com → 'GPT 탐색' → '만들기' → '구성' 탭 → '지침' 칸에 아래 내용 붙여넣기 → 만들기 (나만 보기)",
                   "이후 사용: 그 Gem/GPT를 열고 '이 학생 세특 써줘' + 관찰기록 붙여넣기"],
         "prompt": gem_instructions(settings)},
        {"key": "transcribe", "title": "② 녹음 → 글자 (전사)",
         "when": "Gemini 웹에서 녹음 파일을 직접 받아쓰게 할 때. (쓰담의 Whisper 받아쓰기나 아이폰 메모 받아쓰기를 쓰면 필요 없음)",
         "steps": ["gemini.google.com 새 대화 → '+'(파일 추가)로 녹음 파일(m4a) 첨부",
                   "아래 프롬프트에서 [학생 명단] 부분을 바꿔 붙여넣고 보내기",
                   "결과 전체 복사 → 쓰담 녹음함 → '전사문 붙여넣기'"],
         "prompt": transcribe("수업", "[학급]", None)},
        {"key": "segment", "title": "③ 전사문 → 학생별로 나누기",
         "when": "AI로 더 정확하게 학생별 관찰 내용을 정리하고 싶을 때. (쓰담의 '이름 기준 분리'는 AI 없이도 됩니다)",
         "steps": ["아래 프롬프트의 [학생 명단]과 [전사문]을 바꿔 붙여넣기",
                   "AI가 준 결과(중괄호 { }로 된 내용) 전체 복사 → 쓰담 녹음 화면 → 'AI로 학생별 분리' → 수동 창에 붙여넣기 → 적용",
                   "※ 쓰담이 수동 모드일 때는 녹음 화면에서 버튼을 누르면 명단·전사문이 이미 채워진 프롬프트가 나옵니다"],
         "prompt": segment("수업", "[학급]", None, "[여기에 전사문을 붙여넣으세요]", "[날짜]")},
        {"key": "draft", "title": "④ 관찰기록 → 세특 초안",
         "when": "한 학생의 세특 초안을 웹 채팅에서 만들 때.",
         "steps": ["쓰담 학생 화면 → '관찰기록 복사' (그 학생 기록이 날짜순으로 복사됨)",
                   "아래 프롬프트의 [관찰기록] 부분에 붙여넣고 보내기 (Gem을 만들었다면 '세특 써줘' + 기록만)",
                   "결과 복사 → 쓰담 학생 화면 편집창에 붙여넣기 → 바이트 확인 → 확정"],
         "prompt": draft({"number": "[번호]"}, {"grade": "", "subject": "[과목]"}, placeholder_note, settings).lstrip()},
        {"key": "shorten", "title": "⑤ 너무 길 때 줄이기",
         "when": "NEIS 바이트(기본 1,500)를 넘었을 때.",
         "steps": ["아래 프롬프트의 [세특 문장]에 초안을 붙여넣고 보내기", "결과를 편집창에 붙여넣고 바이트 확인"],
         "prompt": shorten("[여기에 세특 문장을 붙여넣으세요]", int(settings.get("byte_limit") or 1500), 0).replace("현재 0바이트입니다. ", "")},
    ]

def draft_batch(class_info, items, settings, area="subject", context=None):
    """반 전체를 한 번에: 학생마다 [번호] 머리표를 붙인 기록 → AI가 학생마다 '[3번] 초안' 한 줄씩.
    items = [(학생, 관찰기록 목록, 목표 바이트)]"""
    import pipeline
    head = draft({"name": "", "number": None}, class_info, [], settings, "", area, context=context)
    head = head.split("\n[학교급]")[0].split("\n[수업] ")[0]
    head = head.replace("초안을 작성해 주세요.", "초안을 아래 %d명 각각 따로 작성해 주세요." % len(items), 1)
    out = head + ("" if area in OTHER_GUIDE else "\n[학교급] %s\n" % (settings.get("school_level") or "고등학교"))
    out += """
[출력 형식 — 꼭 지키기]
한 사람마다 한 줄씩, 맨 앞에 [번호]를 붙이고 바로 초안 본문만 쓰기. 사람 사이에 다른 말 쓰지 않기.
[1번] 초안 본문…
[2번] 초안 본문…
"""
    for st, notes, target in items:
        tag = "%s번" % (st.get("number") if st.get("number") is not None else st["id"])
        lines = []
        for n in notes:
            t = strip_names(pipeline.strip_class_words(n["content"]), st)
            lines.append("- [%s%s] %s" % (n.get("kind") or "", ("/" + n["category"]) if n.get("category") else "", t))
        out += "\n### [%s]%s\n%s\n" % (tag, (" (분량 %d바이트 이내)" % int(target)) if target else "", "\n".join(lines))
    return out


def expand(text, target_bytes, current_bytes, notes_text=""):
    """초안이 너무 짧을 때: 사실은 그대로, 세특답게 더 자세히."""
    return """아래 학교생활기록부 세특 초안이 너무 짧습니다(현재 %d바이트). %d바이트 안팎(한글 약 %d자)으로 다시 써 주세요.
- 관찰 사실은 바꾸거나 새로 지어내지 말 것. 대신 그 행동이 보여 주는 역량·태도·성장의 의미를 구체적으로 풀어 쓸 것.
- '~함', '~임', '~보임' 명사형 종결, 한 문단, 학생 이름·날짜·'학생은' 쓰지 말 것. 본문만 출력.

[관찰기록]
%s

[지금 초안]
%s
""" % (current_bytes, int(target_bytes * 0.9), int(target_bytes * 0.9 / 3), notes_text or "(위 초안 참고)", text)

