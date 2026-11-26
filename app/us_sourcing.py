"""미국(아마존/월마트) 구매대행 소싱 파이프라인 - 핵심 계산 로직.

영상에서 소개된 흐름을 투명한 규칙으로 재구성했다.

  아이디어/키워드 → 후보 수집(CSV/엑셀/직접입력) → 판매 불가 자동 제외
  → 원가(달러·환율·배송·관부가세) → 채널 수수료 반영 판매가/마진
  → 점수(마진·수요·국내경쟁·배송조건·브랜드·내 판매이력 유사도)
  → 상품명/태그/상세 생성 → 6대 마켓 등록 양식으로 내보내기

여기 있는 숫자(수수료율, 면세 한도, 관세율)는 기본값일 뿐이다. 실제
수수료/통관 기준은 수시로 바뀌므로 설정 화면에서 반드시 직접 확인·수정한다.
"""

import csv
import io
import math
import re
from collections import Counter

# ---------------------------------------------------------------------------
# 기본 설정값 (설정 화면에서 수정 가능)
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "fx_rate": 1400.0,            # 원/달러 환율
    "fx_buffer_pct": 2.0,         # 카드 환전 수수료/환율 변동 버퍼(%)
    "duty_free_usd": 200.0,       # 미국발 목록통관 면세 기준(USD, 물품가격 기준) - 반드시 최신 기준 확인
    "default_duty_pct": 8.0,      # 면세 한도 초과 시 기본 관세율(%)
    "vat_pct": 10.0,              # 부가세(%)
    "intl_ship_krw": 0.0,         # 아마존 무료배송이 아닐 때 추가할 국제배송비(원)
    "domestic_cs_krw": 1000.0,    # 건당 기타 비용(포장/CS/반품 적립 등)
    "target_margin_pct": 30.0,    # 목표 마진율(%)
    "round_to": 100,              # 판매가 반올림 단위(원)
}

# 채널별 판매 수수료(%) 기본값. 카테고리별로 다르므로 대략값이다.
DEFAULT_CHANNEL_FEES = {
    "coupang": {"label": "쿠팡", "fee_pct": 10.8},
    "naver": {"label": "네이버 스마트스토어", "fee_pct": 5.5},
    "gmarket": {"label": "G마켓", "fee_pct": 13.0},
    "auction": {"label": "옥션", "fee_pct": 13.0},
    "st11": {"label": "11번가", "fee_pct": 13.0},
    "lotteon": {"label": "롯데온", "fee_pct": 12.0},
}

# 후보 CSV/엑셀 컬럼 (한글/영문 둘 다 허용)
COLUMN_ALIASES = {
    "title": ["상품명", "title", "name", "product", "영문상품명"],
    "url": ["url", "링크", "상품링크", "link"],
    "asin": ["asin"],
    "price_usd": ["가격(usd)", "price_usd", "price", "달러가격", "가격", "usd"],
    "brand": ["브랜드", "brand"],
    "category": ["카테고리", "category"],
    "rating": ["평점", "rating", "stars"],
    "reviews": ["리뷰수", "reviews", "review_count", "ratings"],
    "bsr": ["bsr", "판매순위", "rank", "best_sellers_rank"],
    "ships_to_kr": ["한국배송", "ships_to_kr", "kr_shipping"],
    "free_ship_kr": ["무료배송", "free_ship_kr", "free_shipping"],
    "import_fee_included": ["관부가세포함", "import_fee_included", "import_fees_deposit"],
    "delivery_days": ["배송일", "delivery_days", "배송소요일"],
    "returns_30d": ["30일반품", "returns_30d", "returns"],
    "kr_competitors": ["국내판매자수", "kr_competitors", "경쟁판매자수"],
    "kr_min_price": ["국내최저가", "kr_min_price"],
    "cn_price_krw": ["중국가(원)", "cn_price_krw"],
    "keyword": ["키워드", "keyword", "seed"],
}

REQUIRED_FIELDS = ["title", "price_usd"]

# ---------------------------------------------------------------------------
# 판매 불가/주의 자동 필터 (영상의 "수집 제외" 기능을 규칙으로 구현)
# level: block = 자동 제외, warn = 인증/확인 필요
# ---------------------------------------------------------------------------
RISK_RULES = [
    ("block", "의약품/의료기기", r"\b(medicine|drug|rx|prescription|supplement pill|melatonin|cbd|thc|hemp extract|hearing aid|contact lens|syringe|blood pressure monitor)\b|의약품|의료기기|콘택트렌즈"),
    ("block", "무기/도검/위험물", r"\b(gun|pistol|rifle|ammo|ammunition|knife|blade|machete|taser|stun gun|pepper spray|crossbow|airsoft|bb gun|fireworks?|lighter fluid|butane|propane|aerosol|gasoline)\b|도검|총포|화약"),
    ("block", "성인/담배", r"\b(adult toy|sex toy|vape|e-cig|nicotine|tobacco|cigarette|hookah)\b|성인용품|전자담배"),
    ("block", "동식물/종자", r"\b(seeds?|live plant|bulbs? for planting|soil|live animal|fish food live)\b|씨앗|종자"),
    ("block", "위조 위험 명품", r"\b(louis vuitton|gucci|chanel|hermes|prada|rolex|cartier|dior|balenciaga)\b"),
    ("warn", "전기/전자(KC 전기안전·전파인증 확인)", r"\b(charger|adapter|power bank|battery|lithium|bluetooth|wireless|wifi|wi-fi|led|lamp|heater|fan|speaker|headphones?|earbuds?|usb|electric|dash ?cam|camera|drone|router|smart)\b|충전기|배터리|블루투스|무선"),
    ("warn", "어린이제품(KC 어린이제품 인증 확인)", r"\b(baby|infant|toddler|kids?|children'?s|toy|crib|stroller|teether|pacifier)\b|유아|아동|어린이|장난감"),
    ("warn", "식품/건강식품(수입식품 요건 확인)", r"\b(food|snack|candy|coffee|tea|protein|vitamin|gummies|sauce|spice|seasoning|jerky|honey)\b|식품|영양제|비타민"),
    ("warn", "화장품(통관 수량·성분 확인)", r"\b(cosmetic|serum|cream|lotion|sunscreen|shampoo|perfume|fragrance|makeup|lipstick)\b|화장품|향수"),
    ("warn", "자동차 안전부품(호환·인증 확인)", r"\b(brake|airbag|tire|tyre|seat belt|headlight bulb|hid)\b|브레이크|타이어|에어백"),
]
_RISK_COMPILED = [(lvl, label, re.compile(pat, re.I)) for lvl, label, pat in RISK_RULES]

# 국내에서 구하기 어려운 "미국 전용" 수요 키워드 (영상: 테슬라/GMC/포드 등 미국차 부품)
US_ONLY_KEYWORDS = [
    "tesla", "model 3", "model y", "model s", "model x", "cybertruck",
    "gmc", "sierra", "yukon", "chevrolet", "chevy", "silverado", "tahoe", "corvette", "camaro",
    "ford", "f-150", "f150", "bronco", "mustang", "explorer", "ranger",
    "jeep", "wrangler", "gladiator", "dodge", "ram 1500", "cadillac", "lincoln", "rivian",
    "costco", "kirkland", "trader joe", "yeti", "stanley", "weber", "traeger",
]


# ---------------------------------------------------------------------------
# 파싱 유틸
# ---------------------------------------------------------------------------
def to_float(v, default=None):
    if v is None:
        return default
    s = str(v).strip().replace(",", "").replace("$", "").replace("₩", "").replace("원", "")
    if s == "":
        return default
    try:
        return float(s)
    except ValueError:
        return default


def to_bool(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("y", "yes", "true", "1", "o", "예", "가능", "있음", "포함", "free"):
        return True
    if s in ("n", "no", "false", "0", "x", "아니오", "불가", "없음", "미포함"):
        return False
    return None


ASIN_RE = re.compile(r"(?:/dp/|/gp/product/|/product/)([A-Z0-9]{10})", re.I)


def extract_asin(url_or_asin):
    if not url_or_asin:
        return ""
    s = str(url_or_asin).strip()
    if re.fullmatch(r"[A-Z0-9]{10}", s, re.I):
        return s.upper()
    m = ASIN_RE.search(s)
    return m.group(1).upper() if m else ""


def normalize_row(raw):
    """임의 컬럼명의 dict → 표준 키 dict."""
    lower = {str(k).strip().lower(): v for k, v in raw.items() if k is not None}
    out = {}
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a.lower() in lower and lower[a.lower()] not in (None, ""):
                out[field] = lower[a.lower()]
                break
    item = {
        "title": str(out.get("title", "")).strip(),
        "url": str(out.get("url", "")).strip(),
        "asin": extract_asin(out.get("asin") or out.get("url")),
        "price_usd": to_float(out.get("price_usd")),
        "brand": str(out.get("brand", "")).strip(),
        "category": str(out.get("category", "")).strip(),
        "rating": to_float(out.get("rating")),
        "reviews": to_float(out.get("reviews")),
        "bsr": to_float(out.get("bsr")),
        "ships_to_kr": to_bool(out.get("ships_to_kr")),
        "free_ship_kr": to_bool(out.get("free_ship_kr")),
        "import_fee_included": to_bool(out.get("import_fee_included")),
        "delivery_days": to_float(out.get("delivery_days")),
        "returns_30d": to_bool(out.get("returns_30d")),
        "kr_competitors": to_float(out.get("kr_competitors")),
        "kr_min_price": to_float(out.get("kr_min_price")),
        "cn_price_krw": to_float(out.get("cn_price_krw")),
        "keyword": str(out.get("keyword", "")).strip(),
    }
    if item["asin"] and not item["url"]:
        item["url"] = f"https://www.amazon.com/dp/{item['asin']}"
    return item


def read_table(filename, file_bytes):
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        headers = [str(h) if h is not None else "" for h in next(it)]
        rows = []
        for r in it:
            if r is None or all(v is None for v in r):
                continue
            rows.append({headers[i]: r[i] for i in range(min(len(headers), len(r)))})
        return rows
    text = file_bytes.decode("utf-8-sig", errors="replace")
    return [dict(r) for r in csv.DictReader(io.StringIO(text))]


# ---------------------------------------------------------------------------
# 리스크 필터
# ---------------------------------------------------------------------------
def check_risks(item):
    text = " ".join([item.get("title", ""), item.get("category", ""), item.get("brand", "")])
    flags = []
    for lvl, label, rx in _RISK_COMPILED:
        if rx.search(text):
            flags.append({"level": lvl, "label": label})
    if item.get("ships_to_kr") is False:
        flags.append({"level": "block", "label": "한국 배송 불가 상품"})
    return flags


def is_blocked(flags):
    return any(f["level"] == "block" for f in flags)


# ---------------------------------------------------------------------------
# 원가/가격 계산
# ---------------------------------------------------------------------------
def landed_cost(item, settings):
    """상품 1개를 고객에게 보내기까지 드는 원가(원)를 항목별로 계산."""
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    usd = item.get("price_usd") or 0.0
    fx = s["fx_rate"] * (1 + s["fx_buffer_pct"] / 100)
    goods_krw = usd * fx

    ship_krw = 0.0 if item.get("free_ship_kr") else s["intl_ship_krw"]

    duty_krw = 0.0
    tax_note = "면세 한도 이내"
    if item.get("import_fee_included"):
        tax_note = "아마존 관부가세 예치금(Import Fees Deposit) 포함가로 입력됨"
    elif usd > s["duty_free_usd"]:
        # 과세가격 ≈ 물품가 + 운임. 관세 → (과세가격+관세)×부가세
        taxable = goods_krw + ship_krw
        duty = taxable * s["default_duty_pct"] / 100
        vat = (taxable + duty) * s["vat_pct"] / 100
        duty_krw = duty + vat
        tax_note = f"면세 한도(${s['duty_free_usd']:.0f}) 초과 → 관세 {s['default_duty_pct']}% + 부가세 {s['vat_pct']}% 추정"

    other = s["domestic_cs_krw"]
    total = goods_krw + ship_krw + duty_krw + other
    return {
        "goods_krw": round(goods_krw),
        "ship_krw": round(ship_krw),
        "duty_krw": round(duty_krw),
        "other_krw": round(other),
        "total_krw": round(total),
        "tax_note": tax_note,
    }


def _round_up(x, unit):
    unit = max(1, int(unit))
    return int(math.ceil(x / unit) * unit)


def price_for_margin(cost_krw, fee_pct, margin_pct, round_to=100):
    """판매가 P: P - P*fee - cost = P*margin  →  P = cost / (1 - fee - margin)."""
    denom = 1 - fee_pct / 100 - margin_pct / 100
    if denom <= 0.01:
        return None
    return _round_up(cost_krw / denom, round_to)


def margin_at_price(price_krw, cost_krw, fee_pct):
    if not price_krw:
        return None, None
    profit = price_krw - price_krw * fee_pct / 100 - cost_krw
    return round(profit), round(profit / price_krw * 100, 1)


def channel_pricing(cost_krw, settings, channel_fees, kr_min_price=None):
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    rows = []
    for key, ch in channel_fees.items():
        rec = price_for_margin(cost_krw, ch["fee_pct"], s["target_margin_pct"], s["round_to"])
        row = {"key": key, "label": ch["label"], "fee_pct": ch["fee_pct"], "recommended_price": rec}
        if kr_min_price:
            p, m = margin_at_price(kr_min_price, cost_krw, ch["fee_pct"])
            row["profit_at_kr_min"] = p
            row["margin_at_kr_min"] = m
        rows.append(row)
    return rows


def china_alternative(item, cost_us_krw, settings, fee_pct):
    """같은 무브랜드 제품을 중국(1688/타오바오)에서 조달할 때의 마진 비교."""
    cn = item.get("cn_price_krw")
    if not cn:
        return None
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    cn_total = cn + s["domestic_cs_krw"]
    sell = item.get("kr_min_price") or price_for_margin(cost_us_krw, fee_pct, s["target_margin_pct"], s["round_to"])
    p_us, m_us = margin_at_price(sell, cost_us_krw, fee_pct)
    p_cn, m_cn = margin_at_price(sell, cn_total, fee_pct)
    return {
        "sell_price": sell, "us_profit": p_us, "us_margin": m_us,
        "cn_cost": round(cn_total), "cn_profit": p_cn, "cn_margin": m_cn,
        "branded": bool(item.get("brand")),
    }


# ---------------------------------------------------------------------------
# 내 판매이력 학습 (영상의 "내 판매 데이터로 학습시킨 GPT"를 투명하게 구현)
# ---------------------------------------------------------------------------
_STOP = set("""a an the and or for with of to in on by from at as is are be this that
new set pack pcs piece compatible fits fit premium upgraded quality 2024 2025 2026""".split())


def tokenize(text):
    toks = re.findall(r"[a-z0-9가-힣][a-z0-9가-힣\-]+", (text or "").lower())
    return [t for t in toks if t not in _STOP and not t.isdigit()]


def build_affinity_model(sold_titles):
    """판매된 상품명 목록 → 토큰 가중치(판매 빈도 기반, 로그 스케일)."""
    c = Counter()
    for t in sold_titles:
        c.update(set(tokenize(t)))
    if not c:
        return {}
    top = max(c.values())
    return {tok: math.log1p(n) / math.log1p(top) for tok, n in c.items()}


def affinity_score(title, model):
    """0~100. 내가 실제로 판 상품들과 겹치는 단어가 많을수록 높다."""
    if not model:
        return None
    toks = set(tokenize(title))
    if not toks:
        return 0.0
    hits = sorted((model.get(t, 0.0) for t in toks), reverse=True)[:5]
    return round(min(100.0, sum(hits) / 3 * 100), 1)


# ---------------------------------------------------------------------------
# 종합 점수
# ---------------------------------------------------------------------------
def score_item(item, cost, best_margin, affinity):
    """각 항목 0~100, 가중 평균. 근거를 함께 돌려준다."""
    parts = {}

    # 1) 마진 (국내 최저가 기준 마진이 있으면 그것, 없으면 목표가 달성 가능성만 보통 점수)
    if best_margin is not None:
        parts["margin"] = max(0.0, min(100.0, best_margin * 2))   # 50% 이상이면 만점
    else:
        parts["margin"] = 60.0

    # 2) 수요 (리뷰수 로그 + BSR 역수)
    demand = []
    if item.get("reviews") is not None:
        demand.append(min(100.0, 100 * math.log1p(item["reviews"]) / math.log1p(20000)))
    if item.get("bsr"):
        demand.append(max(0.0, 100 - 100 * math.log10(max(1.0, item["bsr"])) / 6))
    parts["demand"] = sum(demand) / len(demand) if demand else 50.0

    # 3) 국내 경쟁 (판매자 적을수록 좋음)
    kc = item.get("kr_competitors")
    parts["competition"] = 50.0 if kc is None else max(0.0, 100 - 100 * math.log1p(kc) / math.log1p(200))

    # 4) 배송/반품 조건 (영상 핵심: 한국 무료배송 + 관부가세 포함 + 빠른 배송 + 30일 반품)
    ship = 40.0
    if item.get("free_ship_kr"):
        ship += 25
    if item.get("import_fee_included"):
        ship += 10
    if item.get("returns_30d"):
        ship += 10
    d = item.get("delivery_days")
    if d is not None:
        ship += 15 if d <= 5 else (8 if d <= 8 else -10)
    parts["shipping"] = max(0.0, min(100.0, ship))

    # 5) 미국 전용/브랜드 (상세페이지 없이도 팔리는 브랜드, 국내 구하기 어려운 미국차 부품)
    t = (item.get("title", "") + " " + item.get("brand", "")).lower()
    usonly = any(k in t for k in US_ONLY_KEYWORDS)
    parts["uniqueness"] = (60.0 if item.get("brand") else 35.0) + (40.0 if usonly else 0.0)

    weights = {"margin": 0.30, "demand": 0.20, "competition": 0.15, "shipping": 0.15, "uniqueness": 0.10}
    if affinity is not None:
        parts["affinity"] = affinity
        weights["affinity"] = 0.10
    else:
        weights["margin"] += 0.10

    total = sum(parts[k] * w for k, w in weights.items())
    return round(total, 1), {k: round(v, 1) for k, v in parts.items()}, usonly


def evaluate(item, settings, channel_fees, affinity_model=None):
    """후보 1개를 평가해서 화면/DB에 쓸 결과 dict를 만든다."""
    flags = check_risks(item)
    cost = landed_cost(item, settings)
    pricing = channel_pricing(cost["total_krw"], settings, channel_fees, item.get("kr_min_price"))
    margins = [r.get("margin_at_kr_min") for r in pricing if r.get("margin_at_kr_min") is not None]
    best_margin = max(margins) if margins else None
    aff = affinity_score(item.get("title", ""), affinity_model)
    score, parts, usonly = score_item(item, cost, best_margin, aff)
    if is_blocked(flags):
        score = 0.0
    main_fee = channel_fees.get("coupang", next(iter(channel_fees.values())))["fee_pct"]
    return {
        "flags": flags,
        "blocked": is_blocked(flags),
        "cost": cost,
        "pricing": pricing,
        "best_margin_at_kr_min": best_margin,
        "affinity": aff,
        "score": score,
        "score_parts": parts,
        "us_only": usonly,
        "china": china_alternative(item, cost["total_krw"], settings, main_fee),
    }


# ---------------------------------------------------------------------------
# 롱테일 플래너 (영상: "30일에 1개 팔리는 상품 30개 = 매일 1건")
# ---------------------------------------------------------------------------
def longtail_plan(target_orders_per_day, sell_through_pct, avg_price, avg_margin_pct):
    """
    sell_through_pct: 등록 상품 중 '한 달에 1개 이상 팔리는' 상품 비율(%)
    """
    st = max(0.01, sell_through_pct / 100)
    monthly_orders = target_orders_per_day * 30
    active_needed = monthly_orders               # 월 1개씩 팔리는 상품 수
    listings_needed = math.ceil(active_needed / st)
    revenue = monthly_orders * avg_price
    profit = revenue * avg_margin_pct / 100
    return {
        "monthly_orders": monthly_orders,
        "active_needed": active_needed,
        "listings_needed": listings_needed,
        "monthly_revenue": round(revenue),
        "monthly_profit": round(profit),
    }


SAMPLE_CSV = """상품명,url,가격(usd),브랜드,카테고리,평점,리뷰수,bsr,한국배송,무료배송,관부가세포함,배송일,30일반품,국내판매자수,국내최저가,중국가(원)
Tesla Model Y Center Console Organizer Tray with Hidden Storage,https://www.amazon.com/dp/B0EXAMPLE1,23.99,TESMAG,Automotive,4.5,5200,1800,Y,Y,N,5,Y,12,45000,8000
GMC Sierra 1500 Front Bumper Guard Cover,https://www.amazon.com/dp/B0EXAMPLE2,30.00,Generic,Automotive,4.3,880,22000,Y,Y,N,6,Y,2,58000,
Vaseline Intensive Care Lotion 20.3oz 3 Pack,https://www.amazon.com/dp/B0EXAMPLE3,18.50,Vaseline,Beauty,4.8,41000,120,Y,Y,N,5,Y,40,32000,
Cybertruck Rear Trunk Storage Bin Divider,https://www.amazon.com/dp/B0EXAMPLE4,39.99,BASENOR,Automotive,4.4,650,9500,Y,Y,N,7,Y,1,,15000
Wireless Charging Pad for Model 3 Highland,https://www.amazon.com/dp/B0EXAMPLE5,45.99,Jowua,Automotive,4.2,1200,15000,Y,Y,N,5,Y,8,89000,
Hunting Knife with Sheath Stainless,https://www.amazon.com/dp/B0EXAMPLE6,25.00,Gerber,Sports,4.7,9000,3000,Y,Y,N,6,Y,5,50000,
Ford Bronco Grab Handles Set of 4,https://www.amazon.com/dp/B0EXAMPLE7,34.95,Rugged Ridge,Automotive,4.6,2100,7000,Y,Y,N,8,Y,3,72000,
Bathroom Shower Caddy Adhesive Stainless 2 Pack,https://www.amazon.com/dp/B0EXAMPLE8,19.99,KESOL,Home,4.4,15000,900,Y,Y,N,5,Y,150,15900,4000
"""

SALES_SAMPLE_CSV = """상품명
Tesla Model Y Sunshade Roof Cover
Tesla Model 3 Floor Mats All Weather
GMC Yukon Door Sill Protector
Ford F-150 Tailgate Seal Kit
Shower Caddy Rust Proof Stainless
"""
