"""전자책 스튜디오의 글쓰기 엔진.

두 가지 모드로 동작한다.
- AI 모드: Anthropic API 자격증명(ANTHROPIC_API_KEY 등)이 있으면 Claude로 주제/리서치/목차/원고를 생성.
- 템플릿 모드: 자격증명이 없으면 규칙 기반 초안을 만든다. 실제 AI가 아니라는 사실을 UI에 그대로 표시한다.
"""
import json
import os
import re

MODEL = os.environ.get("EBOOK_MODEL", "claude-opus-5-5")

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


def ai_available():
    if anthropic is None:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def mode_label():
    return "AI 모드 (Claude)" if ai_available() else "템플릿 모드 (API 키 없음)"


class AIError(RuntimeError):
    pass


SYSTEM = (
    "너는 한국어 실용 전자책(PDF, 20~100쪽)을 기획하고 집필하는 베테랑 편집자다. "
    "독자는 스마트폰으로 읽는다. 문단은 짧게, 소제목과 체크리스트를 적극 쓰고, "
    "AI가 쓴 티가 나는 표현(예: '~에 대해 알아보겠습니다', '결론적으로', 과도한 이모지, 뻔한 일반론)을 피한다. "
    "저자의 실제 경험과 구체적 사례, 숫자, 실천 단계를 중심으로 쓴다. 근거 없는 수치나 출처를 지어내지 않는다."
)


def _client():
    if not ai_available():
        raise AIError("API 키가 없어 AI 모드를 쓸 수 없습니다.")
    return anthropic.Anthropic()


def _call(prompt, schema=None, effort="medium", max_tokens=16000, web_search=False):
    """Claude 호출. schema가 있으면 JSON(dict)을, 없으면 텍스트를 돌려준다."""
    client = _client()
    output_config = {"effort": effort}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM,
        output_config=output_config,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if web_search:
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}]

    messages = [{"role": "user", "content": prompt}]
    try:
        for _ in range(4):  # pause_turn(서버 도구 장시간 실행) 대비 이어받기
            with client.beta.messages.stream(messages=messages, **kwargs) as stream:
                msg = stream.get_final_message()
            if msg.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": msg.content}]
    except anthropic.AuthenticationError:
        raise AIError("API 키가 올바르지 않습니다.")
    except anthropic.RateLimitError:
        raise AIError("요청이 많아 잠시 제한되었습니다. 1분 뒤 다시 시도하세요.")
    except anthropic.APIStatusError as e:
        raise AIError(f"AI 서버 오류({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise AIError("AI 서버에 연결할 수 없습니다. 네트워크를 확인하세요.")

    if msg.stop_reason == "refusal":
        raise AIError("AI가 이 요청을 처리하지 않았습니다. 주제나 표현을 바꿔 다시 시도하세요.")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if schema is None:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise AIError("AI 응답을 해석하지 못했습니다. 다시 시도하세요.")


def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


S = {"type": "string"}
A_S = {"type": "array", "items": S}

# ---------------------------------------------------------------- 1. 주제 추천

def suggest_topics(profile):
    persona = profile.get("persona", "").strip() or "평범한 직장인"
    experience = profile.get("experience", "").strip()
    interest = profile.get("interest", "").strip()
    if ai_available():
        schema = _obj({"topics": {"type": "array", "items": _obj({
            "title": S, "target": S, "pain": S, "why_sells": S, "keywords": A_S, "score": {"type": "integer"},
        })}})
        prompt = (
            f"나는 '{persona}'야. 내 경험/노하우: {experience or '(없음)'}. 관심 분야: {interest or '(없음)'}.\n"
            "전자책을 하나 써서 팔고 싶어. 모두를 위한 책이 아니라 뾰족한 틈새 독자를 노린 주제 10개를 추천해줘.\n"
            "각 주제마다 제목(구체적 결과/숫자/기간이 들어간 판매형 제목), 핵심 독자, 독자의 고민, 팔리는 이유, "
            "유튜브/검색창에 넣어볼 수요 확인용 키워드 3~5개, 시장성 점수(1~100)를 줘. 점수 높은 순으로 정렬."
        )
        return _call(prompt, schema)["topics"]
    return _offline_topics(persona, experience, interest)


def _offline_topics(persona, experience, interest):
    base = interest or experience or persona
    seed = re.split(r"[,./\n]", base)[0].strip() or "내 경험"
    templates = [
        ("{p}가 알려주는 {s} 시작 30일 로드맵", "{s}를 처음 시작하려는 사람", "어디서부터 시작해야 할지 모른다"),
        ("{s}, 실패 없이 하는 7단계 체크리스트", "{s}에 한 번 실패해 본 사람", "같은 실수를 반복할까 두렵다"),
        ("월 50만 원 더 버는 {s} 부업 가이드", "{s}로 부수입을 원하는 직장인/주부", "본업 외 수입이 필요하다"),
        ("{s} 때문에 상처받지 않는 법", "{s} 문제로 마음고생 중인 사람", "감정적으로 지쳐 있다"),
        ("하루 15분, {s} 습관 만들기", "바빠서 꾸준히 못 하는 사람", "작심삼일로 끝난다"),
        ("{p}의 {s} 실전 노하우 33가지", "검증된 실전 팁이 필요한 사람", "이론만 있고 실전 정보가 없다"),
        ("50대부터 시작하는 {s}", "은퇴 전후 중장년", "늦었다는 생각에 망설인다"),
        ("{s} 초보가 가장 많이 묻는 질문 50", "{s} 입문자", "물어볼 곳이 없다"),
        ("돈 안 들이고 하는 {s}", "비용 부담이 큰 사람", "비싼 강의/장비가 부담된다"),
        ("100일 만에 바뀌는 {s} 프로젝트", "변화가 절실한 사람", "동기부여가 오래가지 않는다"),
    ]
    out = []
    for i, (t, target, pain) in enumerate(templates):
        title = t.format(p=persona, s=seed)
        out.append({
            "title": title,
            "target": target.format(s=seed),
            "pain": pain,
            "why_sells": "구체적 대상과 결과가 제목에 드러나는 틈새형 주제입니다. (템플릿 모드: 실제 수요는 2단계에서 직접 확인하세요)",
            "keywords": [seed, f"{seed} 방법", f"{seed} 초보", f"{seed} 후기"],
            "score": 80 - i * 3,
        })
    return out


# ---------------------------------------------------------------- 2. 시장성 검증

def search_links(keywords):
    from urllib.parse import quote
    links = []
    for k in keywords[:5]:
        q = quote(k)
        links.append({
            "keyword": k,
            "youtube": f"https://www.youtube.com/results?search_query={q}",
            "kmong": f"https://kmong.com/search?type=gig&keyword={q}",
            "naver": f"https://search.naver.com/search.naver?query={q}",
            "kyobo": f"https://search.kyobobook.co.kr/search?keyword={q}",
        })
    return links


def validate_topic(topic):
    links = search_links(topic.get("keywords") or [topic.get("title", "")])
    if ai_available():
        prompt = (
            f"전자책 주제: {topic.get('title')}\n핵심 독자: {topic.get('target')}\n"
            "이 주제가 실제로 팔릴지 웹 검색으로 확인해줘. 유튜브 인기 영상 조회수, 크몽/교보 등 유사 전자책·책의 리뷰 수와 가격, "
            "검색 관심도 등 확인 가능한 근거를 출처와 함께 정리하고, 확인하지 못한 수치는 지어내지 말고 '확인 불가'라고 써. "
            "마지막에 '판정: 추천/보완 필요/비추천'과 차별화 포인트 3가지, 적정 가격대를 제시해. 마크다운으로."
        )
        report = _call(prompt, effort="medium", web_search=True)
    else:
        report = (
            "### 템플릿 모드: 직접 확인 체크리스트\n"
            "AI가 없어 수요를 자동 조사하지 못합니다. 아래 링크로 5분만 확인하세요.\n\n"
            "1. **유튜브**: 키워드 검색 → 최근 1년 내 조회수 10만+ 영상이 3개 이상이면 수요 있음\n"
            "2. **크몽 전자책**: 같은 주제 상품의 리뷰 수 × 5~10 ≈ 판매량 추정, 가격대 메모\n"
            "3. **교보/네이버 책**: 리뷰 수 많은 종이책이 있으면 전자책으로 '실전 요약판' 차별화 가능\n"
            "4. **판정 기준**: 수요(조회수/리뷰) 있음 + 경쟁 상품의 불만 리뷰가 보임 → 진행\n"
        )
    return {"report": report, "links": links}


# ---------------------------------------------------------------- 3. 리서치

def research(topic):
    if ai_available():
        prompt = (
            f"전자책 '{topic.get('title')}' 집필용 자료조사를 해줘. 독자: {topic.get('target')}.\n"
            "웹 검색으로 국내 자료와 해외 연구/논문(가능하면 저자·연도·저널)을 찾아, 원고에 인용할 만한 핵심 사실, 통계, "
            "실천 기법을 정리해. 항목마다 출처 URL을 붙이고, 확인 안 된 내용은 넣지 마. 마크다운 글머리표로."
        )
        return _call(prompt, effort="high", max_tokens=32000, web_search=True)
    return (
        "### 템플릿 모드: 리서치 메모 양식\n"
        f"- 주제: {topic.get('title')}\n"
        "- [ ] 내 경험 중 가장 극적인 전/후 사례 1개 (숫자로)\n"
        "- [ ] 독자가 가장 많이 하는 실수 3가지\n"
        "- [ ] 참고할 책/논문 2~3개 (Google Scholar, RISS, DBpia에서 키워드 검색)\n"
        "- [ ] 인용할 통계 1~2개 (통계청 KOSIS 등 공식 출처)\n"
        "- [ ] 바로 따라 할 수 있는 실천 도구(체크리스트/표/양식)\n\n"
        "여기에 찾은 내용을 적어두면 목차·원고 단계에서 반영됩니다."
    )


# ---------------------------------------------------------------- 4. 목차

TOC_SCHEMA = _obj({
    "title": S, "subtitle": S, "hook": S,
    "chapters": {"type": "array", "items": _obj({"title": S, "points": A_S})},
})


def make_toc(topic, research_notes, pages=30, revise_request="", current=None):
    if ai_available():
        prompt = (
            f"주제: {topic.get('title')}\n독자: {topic.get('target')}\n독자의 고민: {topic.get('pain')}\n"
            f"목표 분량: 약 {pages}쪽(스마트폰 기준).\n리서치 메모:\n{research_notes[:6000]}\n\n"
            "사고 싶어지는 책 제목, 부제, 한 줄 후킹 문구, 그리고 장(chapter) 목차를 만들어줘. "
            "장 제목은 결과가 보이는 매력적인 문장으로, 장마다 다룰 소주제 3~5개."
        )
        if current and revise_request:
            prompt += f"\n\n현재 목차(JSON): {json.dumps(current, ensure_ascii=False)}\n수정 요청: {revise_request}\n요청을 반영해 고쳐줘."
        return _call(prompt, TOC_SCHEMA)
    n = max(4, min(10, pages // 5))
    title = topic.get("title", "나의 전자책")
    stages = [
        ("왜 지금 이 책이 필요한가", ["독자의 현재 고민", "내가 같은 고민을 겪었던 이야기", "이 책을 읽고 나면 달라지는 것"]),
        ("시작 전에 반드시 알아야 할 것", ["흔한 오해 3가지", "준비물과 마음가짐", "첫 주에 할 일"]),
        ("핵심 방법 1단계: 기초 다지기", ["원리 이해", "따라 하기 예시", "체크리스트"]),
        ("핵심 방법 2단계: 실전 적용", ["실제 사례", "단계별 실행표", "막힐 때 해결법"]),
        ("가장 많이 하는 실수와 해결법", ["실수 TOP 5", "실수를 기회로 바꾼 사례", "점검표"]),
        ("꾸준히 이어가는 습관 설계", ["작게 시작하기", "기록과 피드백", "슬럼프 대처"]),
        ("한 단계 더: 응용과 확장", ["응용 아이디어", "추천 도구", "다음 목표 세우기"]),
        ("독자 Q&A", ["자주 묻는 질문", "상황별 처방", "추가 자료"]),
        ("실천 워크북", ["30일 실천 계획표", "회고 질문", "나만의 기록장"]),
    ]
    chapters = [{"title": t, "points": p} for t, p in stages[: n - 1]]
    chapters.append({"title": "마치며: 당신의 다음 30일", "points": ["핵심 요약", "응원의 말", "저자에게 연락하는 법"]})
    toc = {"title": title, "subtitle": f"{topic.get('target', '독자')}를 위한 실전 가이드", "hook": topic.get("pain", ""), "chapters": chapters}
    if revise_request:
        toc["subtitle"] += f" (수정 요청 메모: {revise_request} — 템플릿 모드에서는 직접 편집하세요)"
    return toc


# ---------------------------------------------------------------- 5. 원고

def write_chapter(book, idx, voice=""):
    toc = book["toc"]
    ch = toc["chapters"][idx]
    pages = book.get("pages", 30)
    per = max(1, pages // max(1, len(toc["chapters"])))
    if ai_available():
        outline = "\n".join(f"{i+1}. {c['title']}" for i, c in enumerate(toc["chapters"]))
        prompt = (
            f"책 제목: {toc['title']} — {toc['subtitle']}\n독자: {book['topic'].get('target')}\n"
            f"저자 소개/경험: {book['profile'].get('persona')} / {book['profile'].get('experience')}\n"
            f"문체 요청: {voice or '따뜻하지만 단호한 코치 말투, 존댓말'}\n전체 목차:\n{outline}\n\n"
            f"리서치 메모(인용 시 출처 표기):\n{book.get('research', '')[:5000]}\n\n"
            f"이제 {idx+1}장 '{ch['title']}'을 써줘. 소주제: {', '.join(ch['points'])}.\n"
            f"분량은 스마트폰 기준 약 {per}쪽(한 쪽 ≈ 600자). 마크다운으로, '## 소제목', 짧은 문단, "
            "필요하면 '- ' 목록과 '> ' 강조 인용을 써. 장 제목(# )은 쓰지 마. 마지막에 '### 오늘의 실천' 체크리스트."
        )
        return _call(prompt, effort="high", max_tokens=32000)
    lines = []
    for p in ch["points"]:
        lines += [
            f"## {p}",
            f"[여기에 '{p}'에 대한 당신의 경험을 적으세요. 템플릿 모드 초안입니다.]",
            "",
            "처음 이 문제를 마주했을 때를 떠올려 보세요. 무엇이 가장 막막했나요? 그때 했던 선택과 결과를 숫자와 함께 적으면 독자는 그 장면에 자신을 대입합니다.",
            "",
            "> 핵심 한 줄: 독자가 이 소주제에서 꼭 가져가야 할 문장을 적으세요.",
            "",
            "- 실천 1: 오늘 바로 할 수 있는 행동",
            "- 실천 2: 이번 주 안에 할 행동",
            "- 실천 3: 한 달 뒤 점검할 것",
            "",
        ]
    lines += ["### 오늘의 실천", "- [ ] 이 장에서 가장 와닿은 문장 하나 적기", "- [ ] 실천 1 바로 해보기"]
    return "\n".join(lines)


# ---------------------------------------------------------------- 6. 휴먼 터치 다듬기

AI_TELLS = [
    (r"에 대해 알아보겠습니다\.?", "을 이야기해 보겠습니다."),
    (r"결론적으로,?\s*", ""),
    (r"요약하자면,?\s*", ""),
    (r"다양한\s+", "여러 "),
    (r"매우\s+", ""),
    (r"중요합니다\.", "꼭 기억하세요."),
    (r"할 수 있습니다\.", "할 수 있어요."),
]


def humanize(text, instructions=""):
    if ai_available():
        prompt = (
            "아래 원고를 사람이 쓴 것처럼 다듬어줘. 규칙: 뻔한 접속어·상투구 제거, 같은 어미 반복 피하기, "
            "추상적 문장을 구체적 장면/숫자로, 문단은 3~4줄 이내, 의미와 사실·출처는 그대로 유지. "
            f"추가 요청: {instructions or '없음'}. 마크다운 구조 유지, 다듬은 원고만 출력.\n\n{text}"
        )
        return _call(prompt, effort="medium", max_tokens=32000)
    out = text
    for pat, rep in AI_TELLS:
        out = re.sub(pat, rep, out)
    return out


# ---------------------------------------------------------------- 10. 광고/판매 문구

COPY_SCHEMA = _obj({
    "landing": _obj({"headline": S, "subhead": S, "pains": A_S, "benefits": A_S, "author_intro": S, "faq": {"type": "array", "items": _obj({"q": S, "a": S})}}),
    "ads": {"type": "array", "items": _obj({"angle": S, "hook": S, "primary_text": S, "headline": S, "cta": S})},
})


def marketing_copy(book):
    toc = book["toc"]
    if ai_available():
        prompt = (
            f"전자책: {toc['title']} — {toc['subtitle']}\n독자: {book['topic'].get('target')}\n고민: {book['topic'].get('pain')}\n"
            f"저자: {book['profile'].get('persona')} / {book['profile'].get('experience')}\n"
            f"목차: {', '.join(c['title'] for c in toc['chapters'])}\n가격: {book.get('price', '')}원\n\n"
            "1) 판매 랜딩페이지 문구(헤드라인, 서브헤드, 독자 고민 4개, 얻게 되는 것 5개, 저자 소개, FAQ 3개)와 "
            "2) 인스타그램/페이스북 광고 문구 3안(공감형, 결과형, 호기심형: 이미지 위 짧은 후킹 문구 15자 내외, 본문 3~5줄, 헤드라인, CTA)을 만들어줘. "
            "과장·허위 수익 보장 표현 금지."
        )
        return _call(prompt, COPY_SCHEMA)
    t = book["topic"]
    return {
        "landing": {
            "headline": toc["title"],
            "subhead": toc["subtitle"],
            "pains": [t.get("pain", "시작이 막막하다"), "정보는 많은데 무엇부터 할지 모르겠다", "혼자 하다 자꾸 포기한다", "시행착오에 시간과 돈을 쓰고 싶지 않다"],
            "benefits": [c["title"] for c in toc["chapters"][:5]],
            "author_intro": f"{book['profile'].get('persona', '')}. {book['profile'].get('experience', '')}",
            "faq": [
                {"q": "어떤 형식인가요?", "a": "스마트폰에서 읽기 좋은 PDF 전자책입니다."},
                {"q": "초보도 따라 할 수 있나요?", "a": "단계별 체크리스트와 실천표로 구성했습니다."},
                {"q": "환불되나요?", "a": "디지털 콘텐츠 특성상 판매처 정책을 따릅니다."},
            ],
        },
        "ads": [
            {"angle": "공감형", "hook": "혹시 나만 이런가요?", "primary_text": f"{t.get('pain', '')}\n저도 그랬습니다. 그래서 겪은 방법을 한 권에 정리했어요.", "headline": toc["title"], "cta": "자세히 보기"},
            {"angle": "결과형", "hook": "30일 뒤 달라지는 것", "primary_text": f"{t.get('target', '')}를 위한 단계별 실천 가이드.\n체크리스트대로 따라만 하세요.", "headline": toc["subtitle"], "cta": "지금 구매하기"},
            {"angle": "호기심형", "hook": "아무도 말 안 해준 한 가지", "primary_text": "많은 사람이 첫 단계에서 같은 실수를 합니다.\n그 실수가 무엇인지 책에서 확인하세요.", "headline": toc["title"], "cta": "더 알아보기"},
        ],
    }
