"""전자책 스튜디오의 글쓰기 엔진.

두 가지 모드로 동작한다.
- AI 모드: Anthropic API 자격증명(ANTHROPIC_API_KEY 등)이 있으면 Claude로 주제/리서치/목차/원고/마케팅을 생성.
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


# ---------------------------------------------------------------- 선택지

CATEGORIES = {
    "사랑과 인간관계": ["연애·이성 관계", "대화법·말하기", "결혼·부부", "친구·직장 인간관계", "자존감·성격"],
    "육아와 가족": ["임신·출산", "영유아 육아", "초등 자녀 교육", "사춘기 자녀", "부모와의 관계"],
    "인생의 목적": ["은퇴 후 삶", "자녀 독립 후 내 인생", "진로·전직", "마음 챙김", "끌어당김·마인드셋"],
    "시간 관리": ["아침 루틴", "직장인 시간 관리", "엄마의 시간 관리", "집중력·공부법"],
    "개인 성장": ["습관 만들기", "독서·글쓰기", "자기계발", "사회초년생 적응", "스피치·발표"],
    "돈 버는 법": ["부업·N잡", "재테크 기초", "블로그·SNS 수익화", "전자책·지식창업", "절약·가계부"],
    "건강과 몸": ["다이어트", "홈트레이닝", "식단·요리", "수면", "중년 건강"],
    "집과 생활": ["집 꾸미기", "정리 수납", "살림 노하우", "반려동물", "생존·안전"],
    "취미와 스포츠": ["골프", "러닝", "등산·캠핑", "그림·악기", "여행"],
    "일과 커리어": ["직장인 처세술", "취업·면접", "엑셀·업무 자동화", "AI 활용", "창업 준비"],
}
LEVELS = {"beginner": "처음 시작하는 완전 초보", "intermediate": "어느 정도 해 봤지만 정체된 중급자", "advanced": "더 깊이 파고 싶은 숙련자"}
TONES = {
    "manual": "정리된 실용 매뉴얼체: 단계·표·체크리스트 중심, 군더더기 없는 존댓말",
    "warm": "존댓말 다정체: 옆에서 말 걸듯 따뜻하고 공감하는 말투",
    "direct": "반말 직설체: 친한 선배가 핵심만 짚어주는 단호한 반말",
    "story": "스토리텔링 경험담체: 장면과 사례로 시작해 교훈으로 이어지는 이야기 중심",
}
LENGTHS = {"super_light": ("슈퍼라이트", 15), "light": ("라이트", 30), "standard": ("스탠다드", 60), "deep": ("딥", 100)}
RESEARCH_LEVELS = {"low": ("낮음(빠름)", 3, "medium"), "medium": ("보통", 6, "high"), "high": ("높음(논문 다수)", 12, "high")}
CHANNELS = {"instagram": "인스타그램(릴스·카드뉴스)", "threads": "스레드", "blog": "네이버 블로그", "youtube": "유튜브 쇼츠", "cafe": "카페·당근 모임"}

SYSTEM = (
    "너는 한국어 실용 전자책(PDF, 15~100쪽)을 기획하고 집필하는 베테랑 편집자이자 1인 지식창업 마케터다. "
    "독자는 스마트폰으로 읽는다. 문단은 짧게, 소제목과 체크리스트를 적극 쓰고, "
    "AI가 쓴 티가 나는 표현(예: '~에 대해 알아보겠습니다', '결론적으로', 과도한 이모지, 뻔한 일반론)을 피한다. "
    "독자가 다음에 할 생각을 예상해 문장을 잇고, 구체적 장면·숫자·실천 단계를 쓴다. "
    "근거 없는 수치나 출처, 저자가 겪지 않은 경험을 지어내지 않는다. 과장되거나 수익을 보장하는 표현을 쓰지 않는다."
)


def _client():
    if not ai_available():
        raise AIError("API 키가 없어 AI 모드를 쓸 수 없습니다.")
    return anthropic.Anthropic()


def _call(prompt, schema=None, effort="medium", max_tokens=16000, web_search=0):
    """Claude 호출. schema가 있으면 JSON(dict)을, 없으면 텍스트를 돌려준다. web_search>0이면 웹 검색 최대 횟수."""
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
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": int(web_search)}]

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
I = {"type": "integer"}
A_S = {"type": "array", "items": S}


def _seed(profile):
    return (profile.get("subcategory") or profile.get("interest") or profile.get("category")
            or profile.get("experience") or profile.get("persona") or "내 경험").strip()


# ---------------------------------------------------------------- 1. 주제 추천

TOPIC_SCHEMA = _obj({"topics": {"type": "array", "items": _obj({
    "title": S, "subtitle": S, "target": S, "pain": S, "why_sells": S, "differentiation": S, "keywords": A_S, "score": I,
})}})


def suggest_topics(profile, exclude=()):
    persona = profile.get("persona", "").strip() or "평범한 직장인"
    level = LEVELS.get(profile.get("level"), profile.get("level") or "초보")
    if ai_available():
        field = f"{profile.get('category') or '자유'} > {profile.get('subcategory') or profile.get('interest') or '자유'}"
        # 웹 검색 결과(인용 포함)와 JSON 출력 형식을 한 요청에 섞지 않도록 두 번에 나눠 호출한다.
        market = _call(
            f"분야 '{field}', 독자 수준 '{level}'. 한국에서 지금 수요가 보이는 세부 고민과 인기 콘텐츠·상품을 웹 검색으로 찾아 "
            "근거(조회수, 리뷰 수, 가격, 출처 URL)와 함께 글머리표 15개 이내로 정리해줘. 확인 못 한 수치는 쓰지 마.",
            effort="low", max_tokens=8000, web_search=5)
        prompt = (
            f"저자: {persona}\n저자 경험/노하우: {profile.get('experience') or '(없음 — 저자가 공부하며 정리하는 책도 좋다)'}\n"
            f"저자 상황/제약: {profile.get('situation') or '(없음)'}\n분야: {field}\n타깃 독자 수준: {level}\n\n"
            f"시장 조사 메모:\n{market[:6000]}\n\n"
            "위 조사를 근거로 지금 실제로 수요가 있는 전자책 주제 10개를 추천해줘. "
            "모두를 위한 책이 아니라 뾰족한 틈새 독자를 노려. 각 주제마다 판매형 제목(구체적 결과·기간·숫자), 부제, 핵심 독자, 독자의 고민, "
            "팔릴 근거(조사 메모에 있는 것만), 기존 상품과의 차별화 방법, 수요 확인용 키워드 3~5개, 시장성 점수(1~100)를 줘. 점수 높은 순."
        )
        if exclude:
            prompt += "\n이미 받은 주제와 겹치지 않게: " + " / ".join(exclude)
        return _call(prompt, TOPIC_SCHEMA)["topics"]
    return _offline_topics(persona, _seed(profile), level, start=len(exclude))


OFFLINE_TOPIC_TEMPLATES = [
    ("{s} 입문 3개월, {l}를 위한 12주 로드맵", "주차별로 따라 하는 실행표", "어디서부터 시작해야 할지 모른다"),
    ("{s}, 실패 없이 하는 7단계 체크리스트", "같은 실수를 반복하지 않는 법", "한 번 실패한 뒤 다시 시작이 두렵다"),
    ("{s} 시작 비용 얼마? 50만 원으로 끝내는 준비 가이드", "꼭 필요한 것만 사는 예산표", "돈이 얼마나 들지 몰라 망설인다"),
    ("{s} 때문에 우는 사람들, 2주 교정 플랜", "가장 흔한 문제 하나만 해결하기", "같은 문제에서 계속 막힌다"),
    ("하루 15분, {s} 습관 만들기", "바쁜 사람을 위한 최소 루틴", "작심삼일로 끝난다"),
    ("{p}의 {s} 실전 노하우 33가지", "현장에서 바로 쓰는 팁 모음", "이론만 있고 실전 정보가 없다"),
    ("50대부터 시작하는 {s}", "늦었다고 생각할 때 읽는 책", "나이 때문에 망설인다"),
    ("{s} 초보가 가장 많이 묻는 질문 50", "검색해도 안 나오는 답", "물어볼 곳이 없다"),
    ("돈 안 들이고 하는 {s}", "무료 도구와 자원만으로", "비싼 강의·장비가 부담된다"),
    ("100일 만에 바뀌는 {s} 프로젝트", "기록장이 포함된 실천 워크북", "동기부여가 오래가지 않는다"),
    ("첫 {s}, 에티켓과 준비물 총정리", "창피당하지 않는 첫날 가이드", "처음이라 실수할까 걱정된다"),
    ("{s}로 월 30만 원 더 버는 법", "작게 시작하는 부수입 설계", "본업 외 수입이 필요하다"),
]


LEVEL_SHORT = {"처음 시작하는 완전 초보": "왕초보", "어느 정도 해 봤지만 정체된 중급자": "중급자", "더 깊이 파고 싶은 숙련자": "숙련자"}


def _offline_topics(persona, seed, level, start=0):
    short = LEVEL_SHORT.get(level, "초보자")
    out = []
    n = len(OFFLINE_TOPIC_TEMPLATES)
    for k in range(10):
        t, sub, pain = OFFLINE_TOPIC_TEMPLATES[(start + k) % n]
        out.append({
            "title": t.format(p=persona, s=seed, l=short),
            "subtitle": sub,
            "target": f"{seed}에 관심 있는 {level}",
            "pain": pain,
            "why_sells": "구체적 대상·결과가 제목에 드러나는 틈새형 주제입니다. (템플릿 모드: 실제 수요는 2단계에서 직접 확인하세요)",
            "differentiation": "저자의 실제 경험·사진·체크리스트를 넣어 일반 정보글과 차별화하세요.",
            "keywords": [seed, f"{seed} 초보", f"{seed} 방법", f"{seed} 후기"],
            "score": 80 - k * 3,
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
            f"전자책 주제: {topic.get('title')} — {topic.get('subtitle', '')}\n핵심 독자: {topic.get('target')}\n"
            "이 주제가 실제로 팔릴지 웹 검색으로 확인해줘. 유튜브 인기 영상 조회수, 크몽/교보 등 유사 전자책·책의 리뷰 수와 가격, "
            "검색 관심도 등 확인 가능한 근거를 출처와 함께 정리하고, 확인하지 못한 수치는 지어내지 말고 '확인 불가'라고 써. "
            "경쟁 상품의 불만 리뷰에서 보이는 빈틈도 찾아줘. "
            "마지막에 '판정: 추천/보완 필요/비추천'과 차별화 포인트 3가지, 적정 가격대를 제시해. 마크다운으로."
        )
        report = _call(prompt, effort="medium", web_search=6)
    else:
        report = (
            "### 템플릿 모드: 직접 확인 체크리스트\n"
            "AI가 없어 수요를 자동 조사하지 못합니다. 아래 링크로 5분만 확인하세요.\n\n"
            "1. **유튜브**: 키워드 검색 → 최근 1년 내 조회수 10만+ 영상이 3개 이상이면 수요 있음\n"
            "2. **크몽 전자책**: 같은 주제 상품의 리뷰 수 × 5~10 ≈ 판매량 추정, 가격대 메모\n"
            "3. **교보/네이버 책**: 리뷰 많은 종이책이 있으면 전자책으로 '실전 요약판' 차별화 가능\n"
            "4. **판정 기준**: 수요(조회수/리뷰) 있음 + 경쟁 상품의 불만 리뷰가 보임 → 진행\n"
        )
    return {"report": report, "links": links}


# ---------------------------------------------------------------- 3. 리서치

def research(topic, level="medium"):
    label, uses, effort = RESEARCH_LEVELS.get(level, RESEARCH_LEVELS["medium"])
    if ai_available():
        depth = {"low": "핵심 자료 5개 내외", "medium": "자료 10개 내외", "high": "해외 논문을 포함해 자료 15개 이상"}[level if level in RESEARCH_LEVELS else "medium"]
        prompt = (
            f"전자책 '{topic.get('title')}' 집필용 자료조사를 해줘. 독자: {topic.get('target')}. 조사 수준: {depth}.\n"
            "웹 검색으로 국내 자료와 해외 연구/논문(가능하면 저자·연도·저널)을 찾아, 원고에 인용할 만한 핵심 사실, 통계, "
            "실천 기법, 독자가 자주 겪는 실패 사례를 정리해. 항목마다 출처 URL을 붙이고, 확인 안 된 내용은 넣지 마. 마크다운 글머리표로."
        )
        return _call(prompt, effort=effort, max_tokens=32000, web_search=uses)
    return (
        f"### 템플릿 모드: 리서치 메모 양식 (조사 수준: {label})\n"
        f"- 주제: {topic.get('title')}\n"
        "- [ ] 내 경험 중 가장 극적인 전/후 사례 1개 (숫자로)\n"
        "- [ ] 독자가 가장 많이 하는 실수 3가지\n"
        "- [ ] 참고할 책/논문 2~3개 (Google Scholar, RISS, DBpia에서 키워드 검색)\n"
        "- [ ] 해외 전문가 영상/글 2~3개 (유튜브·Perplexity로 영어 키워드 검색 후 요약)\n"
        "- [ ] 인용할 통계 1~2개 (통계청 KOSIS 등 공식 출처)\n"
        "- [ ] 바로 따라 할 수 있는 실천 도구(체크리스트/표/예산표/양식)\n\n"
        "여기에 찾은 내용을 적어두면 목차·원고 단계에서 반영됩니다."
    )


# ---------------------------------------------------------------- 4. 목차

TOC_SCHEMA = _obj({
    "title": S, "subtitle": S, "hook": S,
    "chapters": {"type": "array", "items": _obj({"title": S, "claim": S, "points": A_S})},
})


def make_toc(book, revise_request=""):
    topic, pages = book["topic"], int(book.get("pages") or 30)
    tone = TONES.get(book.get("tone"), TONES["manual"])
    current = book.get("toc")
    if ai_available():
        prompt = (
            f"주제: {topic.get('title')} — {topic.get('subtitle', '')}\n독자: {topic.get('target')}\n독자의 고민: {topic.get('pain')}\n"
            f"차별화: {topic.get('differentiation', '')}\n목표 분량: 약 {pages}쪽(스마트폰 기준). 문체: {tone}\n"
            f"리서치 메모:\n{book.get('research', '')[:6000]}\n\n"
            "사고 싶어지는 책 제목, 부제, 한 줄 후킹 문구, 그리고 장(chapter) 목차를 만들어줘. "
            "장 제목은 결과가 보이는 매력적인 문장으로. 장마다 '이 장이 주장하고 결론 내릴 한 문장(claim)'과 다룰 소주제 3~5개."
        )
        if current and revise_request:
            prompt += f"\n\n현재 목차(JSON): {json.dumps(current, ensure_ascii=False)}\n수정 요청: {revise_request}\n요청을 반영해 고쳐줘."
        return _call(prompt, TOC_SCHEMA)
    n = max(3, min(10, pages // 6 + 2))
    stages = [
        ("시작 전에 반드시 알아야 할 것", "제대로 시작하면 시행착오의 절반이 사라진다", ["흔한 오해 3가지", "준비물과 예산", "첫 주에 할 일"]),
        ("핵심 방법 1단계: 기초 다지기", "기초 하나만 확실하면 나머지는 따라온다", ["원리 이해", "따라 하기 예시", "체크리스트"]),
        ("핵심 방법 2단계: 실전 적용", "실전에서는 순서가 실력이다", ["실제 사례", "단계별 실행표", "막힐 때 해결법"]),
        ("가장 많이 하는 실수와 해결법", "실수는 패턴이고, 패턴은 고칠 수 있다", ["실수 TOP 5", "실수를 기회로 바꾼 사례", "점검표"]),
        ("꾸준히 이어가는 습관 설계", "의지가 아니라 구조가 지속을 만든다", ["작게 시작하기", "기록과 피드백", "슬럼프 대처"]),
        ("한 단계 더: 응용과 확장", "기본이 잡히면 응용은 선택이다", ["응용 아이디어", "추천 도구", "다음 목표 세우기"]),
        ("독자 Q&A", "가장 많이 묻는 질문에 답이 있다", ["자주 묻는 질문", "상황별 처방", "추가 자료"]),
        ("실천 워크북", "읽은 것을 해야 내 것이 된다", ["30일 실천 계획표", "회고 질문", "나만의 기록장"]),
        ("사례로 보는 변화", "나와 비슷한 사람이 해냈다면 나도 할 수 있다", ["사례 1", "사례 2", "공통점"]),
    ]
    chapters = [{"title": t, "claim": c, "points": p} for t, c, p in stages[: n - 1]]
    chapters.append({"title": "마치며: 당신의 다음 30일", "claim": "오늘 한 가지를 시작하는 것이 전부다", "points": ["핵심 요약", "응원의 말", "저자에게 연락하는 법"]})
    sub = topic.get("subtitle") or f"{topic.get('target', '독자')}를 위한 실전 가이드"
    toc = {"title": topic.get("title", "나의 전자책"), "subtitle": sub, "hook": topic.get("pain", ""), "chapters": chapters}
    if revise_request:
        toc["subtitle"] += f" (수정 요청 메모: {revise_request} — 템플릿 모드에서는 직접 편집하세요)"
    return toc


# ---------------------------------------------------------------- 5. 원고

def _writer_context(book):
    toc = book["toc"]
    outline = "\n".join(f"{i + 1}. {c['title']} — {c.get('claim', '')}" for i, c in enumerate(toc["chapters"]))
    p = book["profile"]
    ctx = (
        f"책 제목: {toc['title']} — {toc['subtitle']}\n독자: {book['topic'].get('target')}\n독자의 고민: {book['topic'].get('pain')}\n"
        f"저자: {p.get('persona')}\n문체: {TONES.get(book.get('tone'), TONES['manual'])}\n전체 목차:\n{outline}\n\n"
        f"리서치 메모(인용 시 출처 표기, 없는 사실은 쓰지 말 것):\n{book.get('research', '')[:5000]}\n"
    )
    if book.get("my_story"):
        ctx += f"\n저자의 실제 경험(적절한 곳에 1인칭으로 인용):\n{book['my_story'][:3000]}\n"
    else:
        ctx += "\n저자의 개인 경험담은 지어내지 말고, 사례는 '예를 들어 A씨는'처럼 가상 사례임이 드러나게 쓸 것.\n"
    if book.get("voice_sample"):
        ctx += f"\n저자의 말투 샘플(리듬·어휘를 흉내낼 것):\n{book['voice_sample'][:1500]}\n"
    return ctx


def write_prologue(book):
    if ai_available():
        prompt = _writer_context(book) + (
            "\n이 책의 프롤로그를 써줘. 독자의 고민 장면으로 시작해 '이 책을 끝까지 읽으면 무엇이 달라지는지'로 끝내. "
            "1~2쪽 분량(약 900자), 마크다운. 제목(# )은 쓰지 마."
        )
        return _call(prompt, effort="high", max_tokens=8000)
    t = book["topic"]
    return (
        f"[템플릿 모드 초안 — 직접 고쳐 쓰세요]\n\n"
        f"혹시 지금 이런 마음인가요? \"{t.get('pain', '')}\"\n\n"
        "저도 그랬습니다. 그때 제가 가장 답답했던 장면 하나를 여기에 적어 보세요. 독자는 그 장면에서 자신을 봅니다.\n\n"
        f"이 책은 {t.get('target', '당신')}를 위해 썼습니다. 끝까지 읽고 체크리스트를 하나씩 지워 가면, 30일 뒤에는 무엇부터 해야 할지 더 이상 묻지 않게 될 거예요.\n\n"
        "> 이 책의 약속: 읽기만 하는 책이 아니라 따라 하는 책."
    )


def write_chapter(book, idx):
    toc = book["toc"]
    ch = toc["chapters"][idx]
    pages = int(book.get("pages") or 30)
    per = max(1, pages // max(1, len(toc["chapters"])))
    if ai_available():
        prompt = _writer_context(book) + (
            f"\n이제 {idx + 1}장 '{ch['title']}'을 써줘. 이 장의 결론: {ch.get('claim', '')}. 소주제: {', '.join(ch['points'])}.\n"
            f"분량은 스마트폰 기준 약 {per}쪽(한 쪽 ≈ 600자). 마크다운으로, '## 소제목', 짧은 문단, "
            "필요하면 '- ' 목록, '| 표 |', '> ' 강조 인용을 써. 장 제목(# )은 쓰지 마. "
            "독자의 감정을 건드리는 한 문장과 따라 할 수 있는 구체적 행동을 반드시 넣고, 마지막에 '### 오늘의 실천' 체크리스트(- [ ] 형식)."
        )
        return _call(prompt, effort="high", max_tokens=32000)
    lines = [f"> 이 장의 결론: {ch.get('claim', '')}", ""]
    for p in ch["points"]:
        lines += [
            f"## {p}",
            f"[여기에 '{p}'에 대한 내용을 적으세요. 템플릿 모드 초안입니다.]",
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
            "추상적 문장을 구체적 장면/숫자로, 문단은 3~4줄 이내, 의미와 사실·출처는 그대로 유지, 없는 경험을 추가하지 말 것. "
            f"추가 요청: {instructions or '없음'}. 마크다운 구조 유지, 다듬은 원고만 출력.\n\n{text}"
        )
        return _call(prompt, effort="medium", max_tokens=32000)
    out = text
    for pat, rep in AI_TELLS:
        out = re.sub(pat, rep, out)
    return out


# ---------------------------------------------------------------- 9~10. 판매/광고 문구

def _copy_schema():
    return _obj({
        "landing": _obj({"headline": S, "subhead": S, "pains": A_S, "benefits": A_S, "author_intro": S,
                         "faq": {"type": "array", "items": _obj({"q": S, "a": S})}}),
        "ads": {"type": "array", "items": _obj({"angle": S, "hook": S, "primary_text": S, "headline": S, "cta": S})},
    })


AD_ANGLES = ["공감형", "결과형", "호기심형", "문제해결형", "후기·사례형", "가격·혜택형"]


def marketing_copy(book, ad_count=3):
    toc = book["toc"]
    angles = AD_ANGLES[:max(1, min(6, int(ad_count)))]
    if ai_available():
        prompt = (
            f"전자책: {toc['title']} — {toc['subtitle']}\n독자: {book['topic'].get('target')}\n고민: {book['topic'].get('pain')}\n"
            f"저자: {book['profile'].get('persona')} / {book['profile'].get('experience')}\n"
            f"목차: {', '.join(c['title'] for c in toc['chapters'])}\n가격: {book.get('price', '')}원\n\n"
            "1) 판매 랜딩페이지 문구(헤드라인, 서브헤드, 독자 고민 4개, 얻게 되는 것 5개, 저자 소개, FAQ 3개)와 "
            f"2) 인스타그램/페이스북 광고 문구 {len(angles)}안({', '.join(angles)}: 이미지 위 짧은 후킹 문구 15자 내외, 본문 3~5줄, 헤드라인, CTA)을 만들어줘. "
            "과장·허위 수익 보장·가짜 후기 금지(후기형은 '이런 분께 추천'처럼 써)."
        )
        return _call(prompt, _copy_schema())
    t = book["topic"]
    bank = {
        "공감형": ("혹시 나만 이런가요?", f"{t.get('pain', '')}\n저도 그랬습니다. 그래서 방법을 한 권에 정리했어요.", "자세히 보기"),
        "결과형": ("30일 뒤 달라지는 것", f"{t.get('target', '')}를 위한 단계별 실천 가이드.\n체크리스트대로 따라만 하세요.", "지금 구매하기"),
        "호기심형": ("아무도 말 안 해준 한 가지", "많은 사람이 첫 단계에서 같은 실수를 합니다.\n그 실수가 무엇인지 책에서 확인하세요.", "더 알아보기"),
        "문제해결형": ("이것 하나만 바꾸세요", f"'{t.get('pain', '')}'\n원인과 해결 순서를 정리했습니다.", "해결법 보기"),
        "후기·사례형": ("이런 분께 추천해요", f"✔ {t.get('target', '')}\n✔ 혼자 해보다 막힌 분\n✔ 순서대로 따라 하고 싶은 분", "자세히 보기"),
        "가격·혜택형": ("커피 몇 잔 값으로", f"{toc['title']}\n바로 쓰는 체크리스트·실행표 포함 PDF.", "지금 받기"),
    }
    return {
        "landing": {
            "headline": toc["title"], "subhead": toc["subtitle"],
            "pains": [t.get("pain", "시작이 막막하다"), "정보는 많은데 무엇부터 할지 모르겠다", "혼자 하다 자꾸 포기한다", "시행착오에 시간과 돈을 쓰고 싶지 않다"],
            "benefits": [c["title"] for c in toc["chapters"][:5]],
            "author_intro": f"{book['profile'].get('persona', '')}. {book['profile'].get('experience', '')}",
            "faq": [
                {"q": "어떤 형식인가요?", "a": "스마트폰에서 읽기 좋은 PDF 전자책입니다."},
                {"q": "초보도 따라 할 수 있나요?", "a": "단계별 체크리스트와 실천표로 구성했습니다."},
                {"q": "환불되나요?", "a": "디지털 콘텐츠 특성상 판매처 정책을 따릅니다."},
            ],
        },
        "ads": [{"angle": a, "hook": bank[a][0], "primary_text": bank[a][1], "headline": toc["title"], "cta": bank[a][2]} for a in angles],
    }


# ---------------------------------------------------------------- 11. 수익화·콘텐츠

LADDER_SCHEMA = _obj({"tiers": {"type": "array", "items": _obj({
    "stage": S, "name": S, "format": S, "price": S, "contents": S, "goal": S, "next_step": S,
})}, "funnel_tip": S})


def product_ladder(book):
    toc, t = book["toc"], book["topic"]
    if ai_available():
        prompt = (
            f"전자책: {toc['title']} (가격 {book.get('price', '')}원)\n독자: {t.get('target')}\n고민: {t.get('pain')}\n"
            f"저자: {book['profile'].get('persona')} / 상황: {book['profile'].get('situation', '')}\n"
            "이 전자책을 중심으로 '계단형 상품 구조'를 설계해줘: 0단계 무료 미끼(리드마그넷), 1단계 저가(5천~2만 원), "
            "2단계 중가(5~20만 원: 챌린지·워크숍·템플릿 묶음), 3단계 고가(50만 원 이상: 코칭·컨설팅). "
            "각 단계의 상품명, 형식, 가격, 구성, 목적, 다음 단계로 넘어가게 하는 장치를 줘. 저자가 감당 가능한 현실적인 범위로."
        )
        return _call(prompt, LADDER_SCHEMA)
    return {
        "tiers": [
            {"stage": "0단계 무료 미끼", "name": f"{toc['title']} 맛보기 + 체크리스트", "format": "PDF 5쪽 (1장 요약)", "price": "무료 (이메일·카톡 채널 추가와 교환)",
             "contents": "1장 핵심 + 바로 쓰는 체크리스트 1장", "goal": "연락처 모으기, 신뢰 쌓기", "next_step": "마지막 쪽에 본편 할인 쿠폰"},
            {"stage": "1단계 저가", "name": toc["title"], "format": "PDF 전자책", "price": f"{book.get('price', '15000')}원",
             "contents": "전체 원고 + 워크북", "goal": "첫 구매 경험(구매 장벽 낮추기)", "next_step": "구매자 전용 챌린지 초대"},
            {"stage": "2단계 중가", "name": "4주 실천 챌린지", "format": "단톡방 인증 + 주 1회 라이브", "price": "49,000~99,000원",
             "contents": "주차별 미션, 피드백, 템플릿 묶음", "goal": "결과 체험, 후기 확보", "next_step": "우수 참여자 1:1 코칭 제안"},
            {"stage": "3단계 고가", "name": "1:1 코칭 / 소그룹 컨설팅", "format": "4~8회 화상 코칭", "price": "50만 원~",
             "contents": "개인 상황 진단, 맞춤 계획, 점검", "goal": "깊은 변화, 핵심 수익원", "next_step": "수료자 사례를 콘텐츠로 → 다시 0단계 유입"},
        ],
        "funnel_tip": "치과의 무료 스케일링처럼 무료/저가 상품으로 들어오게 하고, 결과를 경험한 사람에게 다음 단계를 제안하세요. (템플릿 모드 예시)",
    }


CARD_SCHEMA = _obj({"slides": {"type": "array", "items": _obj({"title": S, "body": S})}, "caption": S, "hashtags": A_S})


def card_news(book, angle="", source_text=""):
    toc, t = book["toc"], book["topic"]
    if ai_available():
        base = f"원본 콘텐츠(해외 게시물 스크립트 등):\n{source_text[:4000]}\n" if source_text else ""
        prompt = (
            base + f"전자책: {toc['title']}\n독자: {t.get('target')}\n고민: {t.get('pain')}\n관점/주제: {angle or '책의 핵심 한 가지'}\n\n"
            "인스타그램·스레드용 카드뉴스 5장을 만들어줘. 1장은 스크롤을 멈추게 하는 후킹, 2~4장은 핵심 내용(장당 3줄 이내), "
            "5장은 저장/팔로우와 전자책으로 이어지는 CTA. 원본이 있으면 번역이 아니라 한국 독자 상황에 맞게 재구성. "
            "게시물 캡션과 해시태그 8개도."
        )
        return _call(prompt, CARD_SCHEMA)
    chs = toc["chapters"]
    pts = [p for c in chs[:2] for p in c["points"]][:3]
    return {
        "slides": [
            {"title": angle or f"{t.get('pain', '이런 고민')}?", "body": "저장해 두고 하나씩 해보세요 →"},
            *[{"title": f"{i + 1}. {p}", "body": "[여기에 핵심 내용 2~3줄을 적으세요]"} for i, p in enumerate(pts)],
            {"title": "더 자세한 방법은", "body": f"『{toc['title']}』에 정리했어요.\n프로필 링크에서 확인하세요."},
        ],
        "caption": f"{t.get('pain', '')}\n오늘부터 할 수 있는 것만 정리했어요. 저장해 두고 하나씩 해보세요.\n\n더 자세한 내용은 프로필 링크 『{toc['title']}』",
        "hashtags": [f"#{k.replace(' ', '')}" for k in (t.get("keywords") or [])][:5] + ["#전자책", "#꿀팁", "#저장필수"],
    }


PLAN_SCHEMA = _obj({"days": {"type": "array", "items": _obj({"day": I, "format": S, "hook": S, "outline": S, "cta": S})}, "strategy": S})


def content_plan(book, channel="instagram", days=30):
    toc, t = book["toc"], book["topic"]
    ch = CHANNELS.get(channel, channel)
    if ai_available():
        prompt = (
            f"전자책: {toc['title']}\n독자: {t.get('target')}\n고민: {t.get('pain')}\n목차: {', '.join(c['title'] for c in toc['chapters'])}\n"
            f"저자 상황: {book['profile'].get('situation', '')}\n채널: {ch}\n\n"
            f"이 전자책을 알리고 팔기 위한 {days}일 콘텐츠 플랜을 짜줘. 터질 때까지 이어가는 시리즈형 콘텐츠를 중심으로, "
            "정보형/공감형/비하인드/성장기록/판매형을 섞되 판매형은 5일에 1번 이하. 날짜별 형식, 후킹 첫 문장, 내용 개요, CTA. "
            "마지막에 이 채널 운영 전략 요약."
        )
        return _call(prompt, PLAN_SCHEMA)
    kinds = [("정보형", "{p} 핵심 3가지"), ("공감형", "{pain}, 저만 그런가요?"), ("성장기록", "책 쓰는 Day {d} 기록"),
             ("정보형", "초보가 많이 하는 실수: {p}"), ("판매형", "『{title}』 이런 분께 추천해요")]
    points = [p for c in toc["chapters"] for p in c["points"]] or ["핵심"]
    out = []
    for d in range(1, days + 1):
        kind, hook = kinds[(d - 1) % len(kinds)]
        p = points[(d - 1) % len(points)]
        out.append({"day": d, "format": f"{kind} · {ch}", "hook": hook.format(p=p, pain=t.get("pain", "이 고민"), d=d, title=toc["title"]),
                    "outline": f"'{p}' 내용을 3~5줄(또는 카드 5장)로 정리", "cta": "프로필 링크" if kind == "판매형" else "저장·팔로우"})
    return {"days": out, "strategy": "같은 형식을 시리즈로 이어가며 반응이 좋은 형식을 반복하세요. 판매 글은 5일에 1번만. (템플릿 모드 예시)"}


ADAPT_SCHEMA = _obj({"summary_ko": S, "why_it_works": A_S, "adapted_script": S, "product_idea": S})


def adapt_foreign(book, script, note=""):
    t = book.get("topic") or {}
    if ai_available():
        prompt = (
            f"아래는 반응이 좋은 해외 게시물/릴스/영상의 스크립트야.\n---\n{script[:6000]}\n---\n"
            f"내 독자: {t.get('target', '')} / 내 전자책: {(book.get('toc') or {}).get('title', '')}\n추가 메모: {note}\n\n"
            "1) 한국어 요약, 2) 반응이 좋은 이유(구조·후킹·판매 장치) 3~5개, "
            "3) 한국 독자 상황에 맞게 다시 쓴 내 콘텐츠 스크립트(베끼지 말고 구조만 차용), 4) 여기서 착안한 내 상품 아이디어."
        )
        return _call(prompt, ADAPT_SCHEMA)
    return {
        "summary_ko": "[템플릿 모드] 자동 번역·분석은 AI 모드에서 동작합니다. 번역기로 내용을 옮긴 뒤 아래 질문에 답해 보세요.",
        "why_it_works": ["첫 문장이 어떤 감정(불안·호기심·공감)을 건드리나?", "몇 단계/몇 가지로 구조화했나?",
                         "마지막에 무엇을 하라고(저장·댓글·링크) 했나?", "프로필 링크에서 무엇을 팔고 있나? (무료→저가→고가 구조)"],
        "adapted_script": "1) 후킹: 내 독자의 고민을 한 문장으로\n2) 본문: 같은 구조로 내 경험/책 내용 3가지\n3) CTA: 저장 + 프로필 링크의 전자책",
        "product_idea": "원본 계정이 파는 상품 형식을 내 독자에 맞게 바꿔 0~1단계 상품으로 만들어 보세요.",
    }
