"""수요 먼저 → 자체 브랜드 소싱 (인스타 릴스 'grounded. 필라테스 양말' 사례 분석 반영).

흐름
  1) 수요 검증   : 구글 트렌드 / 네이버 데이터랩 CSV를 넣으면 상승·유지·하락을 계산
  2) 상품 발굴   : 니치 크리에이터(브이로그) 자막 여러 개 → 여러 사람이 반복해서 말하는 단어 순위
  3) 원가 계산   : 알리바바/1688 단가·MOQ → 사입(재고) 기준 개당 원가, 마진, 초기 자금, 회수 수량, 최대 광고비
  4) 브랜드·숏폼 : 브랜드명 후보 + 상표 검색 링크, '문제 → 해결' 숏폼 대본

외부 API 없이 동작한다. 데이터는 사용자가 사이트에서 내려받아 붙여넣는다.
"""

import csv
import io
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from urllib.parse import quote, quote_plus

# ---------------------------------------------------------------------------
# 1) 수요 검증
# ---------------------------------------------------------------------------
_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m", "%Y.%m.%d", "%Y.%m", "%Y/%m/%d", "%Y%m%d")


def _parse_date(s):
    s = (s or "").strip().strip(".")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _num(s):
    s = (s or "").strip().replace(",", "")
    if s.startswith("<"):        # 구글 트렌드의 "<1"
        return 0.5
    try:
        return float(s)
    except ValueError:
        return None


def parse_trend_csv(text):
    """구글 트렌드 multiTimeline.csv / 네이버 데이터랩 / '날짜,값' 형식 모두 읽는다.

    반환: {"dates": [...], "series": {키워드: [값...]}}
    """
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    header, dates, cols = None, [], None
    for i, row in enumerate(rows):
        if not row or not row[0].strip():
            continue
        d = _parse_date(row[0])
        if d is None:
            header = row
            continue
        if cols is None:
            n = len(row) - 1
            names = []
            for j in range(n):
                h = header[j + 1] if header and j + 1 < len(header) else f"키워드{j + 1}"
                names.append(re.sub(r":\s*\(.*\)$", "", h).strip() or f"키워드{j + 1}")
            cols = {name: [] for name in names}
        dates.append(d)
        for j, name in enumerate(cols):
            v = _num(row[j + 1]) if j + 1 < len(row) else None
            cols[name].append(v if v is not None else 0.0)
    if not dates:
        raise ValueError("날짜로 시작하는 행을 찾지 못했습니다. 구글 트렌드에서 '다운로드(CSV)'한 파일을 그대로 붙여넣어 주세요.")
    return {"dates": dates, "series": cols}


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def trend_metrics(dates, values):
    """상승/유지/하락 판정과 근거 숫자."""
    n = len(values)
    if n < 4:
        return {"verdict": "데이터 부족", "points": n}
    # 데이터 간격으로 1년이 몇 포인트인지 추정 (주간≈52, 월간≈12)
    span_days = max(1, (dates[-1] - dates[0]).days)
    per_year = max(1, round((n - 1) * 365 / span_days))
    w = max(2, n // 5)
    first, last = _mean(values[:w]), _mean(values[-w:])
    growth = (last / first - 1) * 100 if first > 0 else (100.0 if last > 0 else 0.0)

    yoy = None
    if n >= per_year * 2:
        this_year = _mean(values[-per_year:])
        prev_year = _mean(values[-2 * per_year:-per_year])
        if prev_year > 0:
            yoy = (this_year / prev_year - 1) * 100

    recent = values[-per_year:] if n >= per_year else values
    m = _mean(recent)
    sd = math.sqrt(_mean([(x - m) ** 2 for x in recent])) if recent else 0.0
    seasonality = (sd / m * 100) if m > 0 else 0.0

    # 최소제곱 기울기 (최근 1년, 1년 동안 평균 대비 몇 % 변하는지)
    ys = recent
    xs = list(range(len(ys)))
    mx, my = _mean(xs), _mean(ys)
    den = sum((x - mx) ** 2 for x in xs) or 1
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    slope_pct_year = (slope * len(ys) / my * 100) if my > 0 else 0.0

    key = yoy if yoy is not None else growth
    if key >= 15 and slope_pct_year > -10:
        verdict = "상승"
    elif key <= -15:
        verdict = "하락"
    else:
        verdict = "유지"
    peak_i = max(range(n), key=lambda i: values[i])
    return {
        "verdict": verdict,
        "points": n,
        "per_year": per_year,
        "growth_pct": round(growth, 1),
        "yoy_pct": round(yoy, 1) if yoy is not None else None,
        "slope_pct_year": round(slope_pct_year, 1),
        "seasonality_pct": round(seasonality, 1),
        "latest": round(values[-1], 1),
        "peak": round(values[peak_i], 1),
        "peak_date": dates[peak_i].strftime("%Y-%m-%d"),
        "first_date": dates[0].strftime("%Y-%m-%d"),
        "last_date": dates[-1].strftime("%Y-%m-%d"),
    }


def analyze_trend_text(text):
    data = parse_trend_csv(text)
    out = []
    for name, vals in data["series"].items():
        m = trend_metrics(data["dates"], vals)
        m["keyword"] = name
        # 작은 스파크라인용 (최대 60포인트로 줄임)
        step = max(1, len(vals) // 60)
        m["spark"] = [round(v, 1) for v in vals[::step]]
        out.append(m)
    return out


def demand_links(keyword):
    k = quote(keyword)
    return {
        "google_trends_kr": f"https://trends.google.com/trends/explore?date=today%205-y&geo=KR&q={k}",
        "google_trends_world": f"https://trends.google.com/trends/explore?date=today%205-y&q={k}",
        "naver_datalab": "https://datalab.naver.com/keyword/trendSearch.naver",
        "naver_shopping_insight": "https://datalab.naver.com/shoppingInsight/sCategory.naver",
        "youtube_vlog_en": f"https://www.youtube.com/results?search_query={quote_plus('day in the life ' + keyword)}",
        "youtube_vlog_ko": f"https://www.youtube.com/results?search_query={quote_plus(keyword + ' 브이로그')}",
        "youtube_bag": f"https://www.youtube.com/results?search_query={quote_plus(keyword + ' what is in my bag')}",
        "youtube_essentials": f"https://www.youtube.com/results?search_query={quote_plus(keyword + ' essentials')}",
    }


# ---------------------------------------------------------------------------
# 2) 크리에이터 자막 → 반복 언급 단어
# ---------------------------------------------------------------------------
_EN_STOP = set("""
a about above after again all also am an and any are as at be because been before being below between both but by can
could did do does doing down during each few for from further get got gonna had has have having he her here hers him
his how i if in into is it its itself just know like me more most my myself no nor not now of off on once only or other
our ours out over own really right same she should so some such than that the their them then there these they this
those through to too um uh under until up very was we were what when where which while who whom why will with would yeah
you your yours okay ok oh so-so thing things going go goes went today day time something actually literally basically kind
lot little bit want make made let's lets see look one two three first also back still well much many every always
morning night week class guys hey hi welcome video watch subscribe channel vlog life minutes hour hours
""".split())

_KO_STOP = set("""
그리고 그래서 그런데 근데 진짜 정말 너무 이제 오늘 저는 제가 저희 우리 이거 그거 저거 여기 거기 이렇게 그렇게 그냥 약간 완전
되게 좀 많이 다시 지금 아까 하는 하고 해서 했어요 합니다 있어요 없어요 같아요 같은 이런 그런 저런 때문에 그럼 네 아 어 음
정도 하나 두 세 먼저 다음 계속 거의 바로 일단 오늘은 영상 구독 좋아요 브이로그 하루 아침 저녁 시간
""".split())

_KO_PARTICLES = ("에서는", "으로는", "에서", "으로", "에게", "한테", "까지", "부터", "처럼", "보다", "이랑", "랑",
                 "은", "는", "이", "가", "을", "를", "에", "도", "로", "와", "과", "의", "만")

# 상품일 가능성이 높은 단어 (표시용 가점)
PRODUCT_CUES = set("""
sock socks mat mats bottle tumbler band bands strap straps ring rings ball balls block blocks towel towels bag bags
legging leggings bra shoes shoe sneakers gloves glove cream serum lotion oil mask brush roller foam headband scrunchie
bottle cup case cover stand holder organizer tray lamp light pillow blanket spray tape wrap belt grip grips weights
dumbbell kettlebell rope tracker watch earbuds charger cable clip hook
양말 매트 텀블러 밴드 스트랩 링 볼 블록 수건 타월 가방 레깅스 브라 신발 운동화 장갑 크림 세럼 로션 오일 마스크 브러시 롤러
폼롤러 헤어밴드 머리끈 컵 케이스 커버 거치대 정리함 조명 베개 담요 스프레이 테이프 벨트 그립 아령 덤벨 줄넘기 충전기
""".split())


def _tokens(text):
    out = []
    for raw in re.findall(r"[A-Za-z][A-Za-z'\-]*|[가-힣]+", text or ""):
        t = raw.lower().strip("'-")
        if re.match(r"[가-힣]", t):
            for p in _KO_PARTICLES:
                if t.endswith(p) and len(t) > len(p) + 1:
                    t = t[: -len(p)]
                    break
            if len(t) < 2 or t in _KO_STOP:
                out.append(None)
                continue
        else:
            if t.endswith("'s"):
                t = t[:-2]
            if len(t) < 3 or t in _EN_STOP:
                out.append(None)
                continue
        out.append(t)
    return out


def _ngrams(tokens, n):
    for i in range(len(tokens) - n + 1):
        chunk = tokens[i:i + n]
        if all(chunk):
            yield " ".join(chunk)


def split_transcripts(text):
    """'---' 줄 또는 빈 줄 두 개로 자막을 나눈다."""
    parts = re.split(r"\n\s*-{3,}\s*\n|\n\s*\n\s*\n", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def repeated_terms(transcripts, top=40):
    """여러 크리에이터가 공통으로 말하는 단어/구문 순위.

    점수 = 등장한 자막 수(몇 명이 말했나) 우선, 다음은 전체 언급 수.
    한 사람이 50번 말한 단어보다 5명이 한 번씩 말한 단어가 위로 온다.
    """
    df = Counter()
    tf = Counter()
    for t in transcripts:
        toks = _tokens(t)
        seen = set()
        for n in (1, 2, 3):
            for g in _ngrams(toks, n):
                tf[g] += 1
                seen.add(g)
        df.update(seen)
    min_df = 2 if len(transcripts) >= 2 else 1
    items = [(g, df[g], tf[g]) for g in df if df[g] >= min_df and tf[g] >= 2]
    # 더 긴 구문이 같은 사람 수로 나오면 짧은 단어는 뺀다 (예: 'grip' < 'grip socks')
    longer = defaultdict(int)
    for g, d, _ in items:
        if " " in g:
            for part in g.split():
                longer[part] = max(longer[part], d)
    items = [x for x in items if not (" " not in x[0] and longer.get(x[0], 0) >= x[1])]
    items.sort(key=lambda x: (x[1], " " in x[0], x[2]), reverse=True)
    out = []
    for g, d, c in items[:top]:
        out.append({
            "term": g, "creators": d, "mentions": c,
            "product_like": any(w in PRODUCT_CUES or w.rstrip("s") in PRODUCT_CUES for w in g.split()),
        })
    return out


def transcript_prompt(niche, transcripts):
    body = "\n\n---\n\n".join(t[:6000] for t in transcripts[:8])
    return f"""아래는 '{niche}' 분야 소규모 크리에이터들의 영상 자막이다.

[할 일]
1. 여러 영상에서 반복해서 나오거나 화면에 등장한다고 말하는 '물건(제품)'을 전부 뽑아라.
2. 각 제품마다: 몇 개의 영상에서 나왔는지, 어떤 불편/문제를 해결하는지, 크리에이터가 브랜드명을 말했는지.
3. 그중 '브랜드가 약하고(누가 만들었는지 신경 안 씀), 단가가 낮고, 문제-해결을 영상으로 보여주기 쉬운' 제품 TOP 5를 골라 이유와 함께 적어라.
4. 지어내지 말고 자막에 근거가 있는 것만.

[출력] 표: 제품 | 등장 영상 수 | 해결하는 문제 | 브랜드 언급 | 자체브랜드 적합도(상/중/하)

[자막]
{body}
"""


# ---------------------------------------------------------------------------
# 3) 사입(자체 브랜드) 원가 · 마진 · 초기 자금
# ---------------------------------------------------------------------------
DEFAULT_PL = {
    "unit_cost": 1.0,          # 공장 단가
    "currency": "USD",         # USD / CNY
    "fx_usd": 1400.0,
    "fx_cny": 195.0,
    "moq": 500,                # 최소 주문 수량
    "freight_per_unit": 800,   # 국제 운송비(개당, 원)
    "duty_pct": 13.0,          # 관세율(%) - 품목(HS코드)마다 다름
    "packaging": 500,          # 포장/라벨/택(개당)
    "fixed_cost": 300000,      # 샘플, 로고, 촬영 등 1회성 비용
    "sale_price": 19900,
    "channel_fee_pct": 10.8,
    "ad_per_sale": 3000,       # 판매 1건당 광고비(CPA)
    "return_pct": 3.0,         # 반품/불량 비율(%)
    "shipping_per_order": 3000,  # 국내 택배비(판매자 부담분)
}


def private_label(p):
    p = {**DEFAULT_PL, **{k: v for k, v in (p or {}).items() if v not in (None, "")}}
    fx = p["fx_cny"] if str(p["currency"]).upper() == "CNY" else p["fx_usd"]
    factory = float(p["unit_cost"]) * float(fx)
    cif = factory + float(p["freight_per_unit"])
    duty = cif * float(p["duty_pct"]) / 100
    landed = cif + duty + float(p["packaging"])

    price = float(p["sale_price"])
    fee = price * float(p["channel_fee_pct"]) / 100
    returns = price * float(p["return_pct"]) / 100
    ship = float(p["shipping_per_order"])
    before_ads = price - fee - returns - ship - landed
    profit = before_ads - float(p["ad_per_sale"])
    margin = profit / price * 100 if price else 0.0

    moq = int(float(p["moq"]))
    inventory_capital = landed * moq
    upfront = inventory_capital + float(p["fixed_cost"])
    # 한 개 팔 때 회수되는 현금 = 판매가 - 수수료 - 반품 - 택배 - 광고 (재고 원가는 이미 냈으므로 회수분에 포함)
    cash_back_per_sale = price - fee - returns - ship - float(p["ad_per_sale"])
    payback_units = math.ceil(upfront / cash_back_per_sale) if cash_back_per_sale > 0 else None
    return {
        "inputs": p,
        "factory_krw": round(factory),
        "freight_krw": round(float(p["freight_per_unit"])),
        "duty_krw": round(duty),
        "packaging_krw": round(float(p["packaging"])),
        "landed_krw": round(landed),
        "fee_krw": round(fee),
        "returns_krw": round(returns),
        "ship_krw": round(ship),
        "max_ad_per_sale": round(before_ads),     # 이 이상 광고비를 쓰면 적자
        "profit_krw": round(profit),
        "margin_pct": round(margin, 1),
        "markup_x": round(price / landed, 1) if landed else None,
        "inventory_capital": round(inventory_capital),
        "upfront": round(upfront),
        "payback_units": payback_units,
        "payback_within_moq": payback_units is not None and payback_units <= moq,
        "moq_total_profit": round(profit * moq - float(p["fixed_cost"])),
    }


def sourcing_links(product_en, product_ko=""):
    en = quote_plus(product_en or product_ko)
    ko = quote_plus(product_ko or product_en)
    return {
        "alibaba": f"https://www.alibaba.com/trade/search?SearchText={en}",
        "aliexpress": f"https://www.aliexpress.com/wholesale?SearchText={en}",
        "1688": "https://s.1688.com/  (중국어 검색어 또는 이미지 검색)",
        "amazon": f"https://www.amazon.com/s?k={en}",
        "coupang": f"https://www.coupang.com/np/search?q={ko}",
        "naver": f"https://search.shopping.naver.com/search/all?query={ko}",
    }


# ---------------------------------------------------------------------------
# 4) 브랜드명 · 숏폼 대본
# ---------------------------------------------------------------------------
_BRAND_WORDS = {
    "grip": ["grounded", "anchor", "steady", "planted", "footing", "stay"],
    "calm": ["still", "hush", "soft", "slow", "ease", "breathe"],
    "strong": ["core", "form", "rise", "lift", "solid", "bold"],
    "clean": ["clear", "pure", "fresh", "plain", "bare", "neat"],
    "warm": ["cozy", "nest", "hearth", "ember", "snug", "home"],
}


def brand_ideas(product_en, feeling="grip"):
    words = _BRAND_WORDS.get(feeling, _BRAND_WORDS["grip"])
    base = (product_en or "").split()[0].lower() if product_en else ""
    names = []
    for w in words:
        names.append(f"{w}.")
        if base:
            names.append(f"{w} {base}")
    names += [f"the {words[0]} co.", f"{words[1]}ly", f"{words[2]} lab"]
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append({
                "name": n,
                "kipris": "https://www.kipris.or.kr/khome/main.do",   # 특허정보검색서비스 - 상표 검색
                "domain": f"https://www.whois.com/whois/{quote(re.sub(r'[^a-z0-9]', '', n.lower()))}.com",
                "insta": f"https://www.instagram.com/{quote(re.sub(r'[^a-z0-9_.]', '', n.lower().replace(' ', '')))}/",
            })
    return out[:12]


def shortform_scripts(product, problem, solution, target="", brand=""):
    product = product or "제품"
    problem = problem or "자꾸 불편한 순간"
    solution = solution or "한 번에 해결"
    brand = brand or "우리 브랜드"
    who = f"{target} " if target else ""
    hooks = [
        f"{who}이거 때문에 {problem} 겪는 사람?",
        f"{problem}… 저만 그런 거 아니죠?",
        f"{who}이거 하나 바꿨더니 {solution}",
    ]
    scripts = []
    for h in hooks:
        scripts.append([
            ("0~2초 · 훅(문제)", h, f"{problem} 장면을 과장 없이 그대로 (클로즈업)"),
            ("2~5초 · 문제 강조", f"매번 {problem}", "실패/불편 반복 컷 2~3개, 빠르게"),
            ("5~9초 · 해결", f"{product}로 바꾸고 나서 → {solution}", "같은 동작을 다시, 이번엔 성공 (비포·애프터 같은 각도)"),
            ("9~13초 · 디테일", f"{product} 핵심 포인트 1~2개", "질감·구조 클로즈업, 사용 장면"),
            ("13~15초 · 마무리", f"{brand} — 프로필 링크", "로고 + 제품 컷"),
        ])
    return scripts


def brand_prompt(niche, product, problem, target):
    return f"""'{niche}' 분야에서 '{product}'를 자체 브랜드로 만들려고 한다.
타깃: {target or '(미정)'} / 해결하는 문제: {problem or '(미정)'}

1. 브랜드명 15개: 1~2단어, 발음 쉬움, 제품 기능보다 '느낌'(예: grounded., stay grounded.) 위주. 한글·영문 각각.
2. 각 이름에 슬로건 한 줄.
3. 이미 유명한 브랜드와 비슷한 이름은 빼라. (최종 확인은 내가 KIPRIS에서 할 것)
4. 숏폼 훅 10개: '문제 장면 → 해결 장면' 구조, 첫 2초 자막 15자 이내.
"""
