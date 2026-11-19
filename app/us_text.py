"""미국 소싱 텍스트 도구 - 키워드 확장, 한국어 상품명/태그/상세페이지, GPT 프롬프트,
주문용 영문 주소(로마자 변환), 개인통관고유부호 형식 검사.

번역은 외부 API 없이 자주 쓰는 커머스 단어 사전으로 1차 변환하고,
자연스러운 문장 다듬기는 "GPT 프롬프트" 버튼으로 만든 프롬프트를
ChatGPT/Claude에 붙여넣어 처리하도록 했다(비용 0원, 키 불필요).
"""

import html
import re
from urllib.parse import quote_plus

# ---------------------------------------------------------------------------
# 아이디어 → 키워드 확장 (영상: "사이버트럭보다 모델3/모델Y가 많으니 키워드를 넓혀준다")
# ---------------------------------------------------------------------------
IDEA_EXPANSION = {
    "테슬라": ["Tesla Model Y accessories", "Tesla Model 3 Highland accessories", "Tesla Model Y Juniper accessories",
             "Tesla Cybertruck accessories", "Tesla center console organizer", "Tesla screen protector", "Tesla floor mats"],
    "tesla": ["Tesla Model Y accessories", "Tesla Model 3 Highland accessories", "Tesla Cybertruck accessories"],
    "gmc": ["GMC Sierra 1500 accessories", "GMC Yukon accessories", "GMC Canyon accessories", "GMC Hummer EV accessories"],
    "포드": ["Ford F-150 accessories", "Ford Bronco accessories", "Ford Explorer accessories", "Ford Ranger accessories", "Ford Mustang accessories"],
    "쉐보레": ["Chevy Silverado accessories", "Chevy Tahoe accessories", "Chevy Colorado accessories", "Corvette C8 accessories"],
    "지프": ["Jeep Wrangler JL accessories", "Jeep Gladiator accessories", "Jeep Grand Cherokee accessories"],
    "캠핑": ["Yeti cooler accessories", "camping storage organizer", "Weber grill accessories", "Traeger accessories"],
    "반려동물": ["cat litter mat", "dog car seat cover", "cat water fountain filter", "dog harness no pull"],
    "고양이": ["cat litter mat", "cat water fountain filter", "cat scratcher refill", "cat window perch"],
    "강아지": ["dog car seat cover", "dog harness no pull", "dog paw cleaner", "dog crate cover"],
    "욕실": ["shower caddy adhesive", "bathroom organizer stainless", "shower head filter"],
    "주방": ["kitchen drawer organizer", "silicone stretch lids", "Instant Pot accessories", "Vitamix accessories"],
    "코스트코": ["Kirkland Signature", "Costco bulk pack"],
    "공구": ["Milwaukee M18 accessories", "DeWalt 20V accessories", "Ryobi accessories", "socket organizer"],
}


def expand_idea(idea):
    idea = (idea or "").strip()
    if not idea:
        return []
    key = idea.lower()
    out = []
    for k, vals in IDEA_EXPANSION.items():
        if k.lower() in key or key in k.lower():
            out.extend(vals)
    if not out:
        out = [idea, f"{idea} accessories", f"{idea} organizer", f"{idea} replacement parts", f"best {idea}"]
    seen, uniq = set(), []
    for v in out:
        if v.lower() not in seen:
            seen.add(v.lower())
            uniq.append(v)
    return uniq


def search_links(keyword):
    q = quote_plus(keyword)
    return {
        "amazon": f"https://www.amazon.com/s?k={q}",
        "amazon_bestsellers_hint": f"https://www.amazon.com/s?k={q}&s=review-rank",
        "walmart": f"https://www.walmart.com/search?q={q}",
        "naver": f"https://search.shopping.naver.com/search/all?query={q}",
        "coupang": f"https://www.coupang.com/np/search?q={q}",
        "1688_image_hint": "https://s.1688.com/  (이미지 검색에 대표 이미지를 올려 동일 제품 확인)",
    }


def sourcing_prompt(keyword, sold_titles=None, count=30):
    """영상의 '내 판매 데이터를 학습시킨 GPT' 대신 쓰는 프롬프트. 판매이력을 예시로 넣는다."""
    sold = "\n".join(f"- {t}" for t in (sold_titles or [])[:40]) or "- (아직 판매 이력 없음)"
    return f"""너는 미국 아마존 → 한국 해외구매대행 셀러의 소싱 분석가다.

[내가 실제로 판매한 상품들 - 이 패턴과 비슷한 것을 우선해라]
{sold}

[요청]
키워드 "{keyword}" 로 아마존 미국(amazon.com)에서 한국 고객에게 잘 팔릴 상품 후보 {count}개를 뽑아줘.

[선정 기준]
1. 상품 페이지에 'Ships to Republic of Korea' 와 'Import Fees Deposit / FREE Shipping to Korea' 가 뜨는 상품 우선
2. 국내(쿠팡/네이버)에서 구하기 어렵거나 판매자가 적은 미국 전용 상품 (미국차 부품, 미국 브랜드 소모품 등)
3. 리뷰 500개 이상, 평점 4.2 이상
4. 상세페이지 설득이 필요 없는 '브랜드/호환 모델이 명확한' 상품
5. 제외: 의약품·건강기능식품·식품, 배터리 단독, 도검·무기, 성인용품, 명품 브랜드, 씨앗/동식물
6. 전기/전자·어린이 제품은 'KC 인증 확인 필요' 라고 표시

[출력 형식 - CSV 코드블록 하나만]
상품명,url,가격(usd),브랜드,카테고리,평점,리뷰수,한국배송,무료배송,배송일,30일반품,선정이유
(url은 반드시 https://www.amazon.com/dp/ASIN 형식. 모르는 값은 비워둘 것. 지어내지 말 것.)
"""


# ---------------------------------------------------------------------------
# 영어 → 한국어 1차 변환 사전 (자주 나오는 커머스 단어)
# ---------------------------------------------------------------------------
EN_KO = {
    "center console": "센터콘솔", "console": "콘솔", "organizer": "정리함", "tray": "트레이",
    "storage": "수납", "bin": "수납함", "divider": "칸막이", "hidden": "히든", "rear": "후면",
    "front": "전면", "trunk": "트렁크", "frunk": "프렁크", "floor mats": "바닥매트", "floor mat": "바닥매트",
    "all weather": "올웨더", "mat": "매트", "mats": "매트", "cover": "커버", "guard": "가드",
    "bumper": "범퍼", "protector": "보호대", "screen protector": "액정보호필름", "sunshade": "선쉐이드",
    "roof": "루프", "door sill": "도어스커프", "grab handles": "손잡이", "handle": "손잡이",
    "wireless charging pad": "무선충전패드", "wireless charger": "무선충전기", "charging": "충전",
    "seal kit": "실링키트", "tailgate": "테일게이트", "mud flaps": "머드가드", "seat cover": "시트커버",
    "accessories": "액세서리", "replacement": "교체용", "parts": "부품", "kit": "키트",
    "stainless steel": "스테인리스", "stainless": "스테인리스", "silicone": "실리콘", "aluminum": "알루미늄",
    "leather": "가죽", "waterproof": "방수", "adhesive": "접착식", "rust proof": "녹방지",
    "shower caddy": "샤워선반", "caddy": "선반", "bathroom": "욕실", "kitchen": "주방", "drawer": "서랍",
    "lotion": "로션", "intensive care": "인텐시브케어", "pack": "팩", "set of": "세트", "set": "세트",
    "dog": "강아지", "cat": "고양이", "pet": "반려동물", "litter": "모래", "fountain": "급수기",
    "filter": "필터", "harness": "하네스", "camping": "캠핑", "cooler": "쿨러", "grill": "그릴",
    "light": "조명", "lamp": "램프", "bulb": "전구", "black": "블랙", "white": "화이트", "gray": "그레이",
}

BRAND_KO = {
    "tesla": "테슬라", "model y": "모델Y", "model 3": "모델3", "model s": "모델S", "model x": "모델X",
    "highland": "하이랜드", "juniper": "주니퍼", "cybertruck": "사이버트럭", "gmc": "GMC",
    "sierra": "시에라", "yukon": "유콘", "ford": "포드", "bronco": "브롱코", "f-150": "F-150",
    "chevy": "쉐보레", "chevrolet": "쉐보레", "silverado": "실버라도", "tahoe": "타호",
    "jeep": "지프", "wrangler": "랭글러", "vaseline": "바세린",
}

# 오픈마켓 상품명/태그에 넣으면 안 되는 단어(검색 어뷰징/허위과장)
BANNED_WORDS = ["최저가", "최고급", "무료배송", "정품보장", "100%", "1위", "특가", "할인", "사은품", "best", "#1",
                "free shipping", "genuine", "official", "fda approved", "cure"]


def _apply_dict(text, mapping):
    out = text
    for en in sorted(mapping, key=len, reverse=True):
        out = re.sub(rf"(?i)\b{re.escape(en)}\b", mapping[en], out)
    return out


def clean_banned(text):
    out = text
    for w in BANNED_WORDS:
        out = re.sub(re.escape(w), "", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip(" -,/")


def korean_title(item, max_len=50):
    """[미국] 브랜드 + 호환모델 + 핵심명사 형태. 50자 이내(쿠팡/네이버 권장 범위)."""
    raw = item.get("title", "")
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", raw)
    t = re.sub(r"\b(for|with|and|the|compatible with|fits?)\b", " ", t, flags=re.I)
    t = _apply_dict(t, BRAND_KO)
    t = _apply_dict(t, EN_KO)
    t = re.sub(r"[,|/]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    brand = item.get("brand") or ""
    if brand and brand.lower() not in ("generic", "unbranded") and brand.lower() not in t.lower():
        t = f"{brand} {t}"
    t = clean_banned(f"[미국] {t}")
    if len(t) > max_len:
        t = t[:max_len].rsplit(" ", 1)[0]
    return t


def make_tags(item, limit=10):
    """네이버 태그 10개 제한 기준. 호환모델/핵심명사/용도 위주."""
    base = (item.get("title", "") + " " + item.get("category", "")).lower()
    tags = []
    for en, ko in list(BRAND_KO.items()) + list(EN_KO.items()):
        if re.search(rf"\b{re.escape(en)}\b", base) and ko not in tags:
            tags.append(ko)
    models = [x for x in tags if x in ("모델Y", "모델3", "모델S", "모델X", "사이버트럭")]
    nouns = [x for x in tags if x not in models and x not in BRAND_KO.values()]
    combos = [f"{m}{n}" for m in models for n in nouns[:3]]
    final = []
    for x in combos + tags + ["해외구매대행", "미국직구"]:
        x = clean_banned(x.replace(" ", ""))
        if x and x not in final:
            final.append(x)
    return final[:limit]


def detail_page_html(item, evaluation, title_ko):
    """구매대행 필수 고지 + 호환/구성 안내가 들어간 간단한 상세페이지 HTML."""
    e = html.escape
    flags = evaluation.get("flags", []) if evaluation else []
    warn = "".join(f"<li>{e(f['label'])}</li>" for f in flags if f["level"] == "warn")
    days = item.get("delivery_days")
    days_txt = f"평균 {int(days)}일" if days else "약 5~10일(영업일)"
    return f"""<div style="max-width:860px;margin:0 auto;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;line-height:1.7;color:#222">
  <h2 style="border-bottom:2px solid #222;padding-bottom:8px">{e(title_ko)}</h2>
  <p><b>원문 상품명</b>: {e(item.get('title',''))}</p>
  <p><b>브랜드</b>: {e(item.get('brand','') or '-')} &nbsp;|&nbsp; <b>카테고리</b>: {e(item.get('category','') or '-')}</p>
  <h3>✔ 호환/사양 확인</h3>
  <p>차량 연식·트림(예: 모델Y 구형/주니퍼, 모델3 하이랜드) 및 사이즈를 주문 전 반드시 확인해 주세요. 원문 상품명의 호환 정보를 기준으로 합니다.</p>
  {f'<h3>⚠ 확인이 필요한 항목</h3><ul>{warn}</ul>' if warn else ''}
  <h3>📦 해외구매대행 안내</h3>
  <ul>
    <li>본 상품은 <b>미국 현지 판매처에서 구매하여 해외 배송</b>되는 해외구매대행 상품입니다.</li>
    <li>배송기간: {e(days_txt)} (통관·현지 사정에 따라 지연될 수 있습니다)</li>
    <li>통관을 위해 <b>개인통관고유부호</b>가 반드시 필요합니다.</li>
    <li>주문 후 현지 발주가 진행되면 단순변심 취소 시 왕복 국제배송비가 발생할 수 있습니다.</li>
    <li>전기용품·어린이제품 등은 관련 법령에 따라 구매대행 요건을 확인한 상품만 판매합니다.</li>
  </ul>
</div>"""


def rewrite_prompt(items):
    """여러 상품의 상품명/태그를 GPT로 한 번에 다듬을 때 쓰는 프롬프트."""
    lines = "\n".join(f"{i+1}. {it.get('title','')} | 브랜드:{it.get('brand','')}" for i, it in enumerate(items[:50]))
    return f"""아래 미국 아마존 상품명을 한국 오픈마켓(쿠팡/네이버) 등록용으로 바꿔줘.

규칙:
- 형식: [미국] 브랜드 + 호환차종/모델 + 핵심명사 + 주요속성, 공백 포함 50자 이내
- 과장/금지어 금지: 최저가, 최고, 1위, 정품보장, 무료배송, 할인
- 다른 회사 상표를 내 브랜드처럼 쓰지 말 것 (호환 표기는 '모델Y용', '호환' 으로)
- 태그 10개: 고객이 실제로 검색할 단어, 띄어쓰기 없이
- 출력: CSV 코드블록 (번호,한국어상품명,태그(|로 구분))

상품 목록:
{lines}
"""


# ---------------------------------------------------------------------------
# 주문 처리: 한글 주소 → 로마자(국어의 로마자 표기법 기본 규칙), 통관부호 검사
# ---------------------------------------------------------------------------
_CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]


def romanize(text):
    out = []
    chars = list(text or "")
    for i, ch in enumerate(chars):
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            idx = code - 0xAC00
            cho, jung, jong = idx // 588, (idx % 588) // 28, idx % 28
            c = _CHO[cho]
            # 'ㄹ' 초성은 단어 첫머리에서 r, 그 외에도 r (기본 규칙). 앞 받침 ㄹ + ㄹ → l
            if cho == 5 and out and out[-1].endswith("l"):
                c = "l"
            syl = c + _JUNG[jung]
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            nxt_is_vowel_start = bool(nxt) and 0xAC00 <= ord(nxt) <= 0xD7A3 and (ord(nxt) - 0xAC00) // 588 == 11
            if jong:
                if nxt_is_vowel_start and jong == 8:   # ㄹ 받침 + 모음 → r
                    syl += "r"
                elif nxt_is_vowel_start and jong in (1, 7, 17):  # ㄱ,ㄷ,ㅂ + 모음 → g,d,b 연음
                    syl += {1: "g", 7: "d", 17: "b"}[jong]
                else:
                    syl += _JONG[jong]
            out.append(syl)
        else:
            out.append(ch)
    return "".join(out)


_ADDR_SUFFIX = [("특별시", "-si"), ("광역시", "-si"), ("특별자치시", "-si"), ("특별자치도", "-do"),
                ("도", "-do"), ("시", "-si"), ("군", "-gun"), ("구", "-gu"), ("읍", "-eup"), ("면", "-myeon"),
                ("동", "-dong"), ("대로", "-daero"), ("로", "-ro"), ("길", "-gil")]

_CITY_EN = {"서울": "Seoul", "부산": "Busan", "대구": "Daegu", "인천": "Incheon", "광주": "Gwangju",
            "대전": "Daejeon", "울산": "Ulsan", "세종": "Sejong", "경기": "Gyeonggi", "강원": "Gangwon",
            "충북": "Chungcheongbuk", "충남": "Chungcheongnam", "전북": "Jeonbuk", "전남": "Jeollanam",
            "경북": "Gyeongsangbuk", "경남": "Gyeongsangnam", "제주": "Jeju"}


def _romanize_token(tok):
    if re.fullmatch(r"[0-9\-]+(번길|번지)?", tok):
        return tok.replace("번길", "beon-gil").replace("번지", "")
    for city, en in _CITY_EN.items():
        if tok.startswith(city) and len(tok) <= len(city) + 4:
            rest = tok[len(city):]
            suffix = next((s for k, s in _ADDR_SUFFIX if rest == k), "")
            return en + suffix if rest else en
    for k, s in _ADDR_SUFFIX:
        if tok.endswith(k) and len(tok) > len(k):
            stem = tok[: -len(k)]
            m = re.match(r"^(.*?)(\d+)$", stem)
            if m and k == "길":
                return f"{romanize(m.group(1)).capitalize()}{m.group(2)}-gil"
            return romanize(stem).capitalize() + s
    return romanize(tok).capitalize()


def address_to_english(addr_ko, detail_ko="", zipcode=""):
    """도로명 주소 → 영문(미국 쇼핑몰 배송지 입력용). 결과는 반드시 눈으로 확인할 것."""
    tokens = [t for t in re.split(r"\s+", (addr_ko or "").strip()) if t]
    en = [_romanize_token(t) for t in tokens]
    # 영문 주소는 작은 단위 → 큰 단위 순서
    road_idx = next((i for i, t in enumerate(tokens) if re.search(r"(로|길|대로)$", t)), None)
    if road_idx is not None:
        street = " ".join(en[road_idx:])
        region = list(reversed(en[:road_idx]))
        line1 = street
        city_line = ", ".join(region)
    else:
        line1 = " ".join(reversed(en))
        city_line = ""
    line2 = romanize(detail_ko).replace("dong ", "-dong ").strip() if detail_ko else ""
    line2 = re.sub(r"(\d+)\s*dong", r"\1-dong", line2)
    line2 = re.sub(r"(\d+)\s*ho", r"\1-ho", line2)
    return {
        "address_line1": line1,
        "address_line2": line2,
        "city_region": city_line,
        "zipcode": zipcode,
        "country": "Republic of Korea",
    }


def romanize_name(name_ko):
    """한글 이름 → 'Hong Gildong' (성 1글자 + 이름). 영문이면 그대로."""
    n = (name_ko or "").strip().replace(" ", "")
    if not n or not re.search(r"[가-힣]", n):
        return (name_ko or "").strip()
    if len(n) <= 1:
        return romanize(n).capitalize()
    return f"{romanize(n[0]).capitalize()} {romanize(n[1:]).capitalize()}"


def validate_customs_code(code):
    """개인통관고유부호: P + 숫자 12자리. (형식 검사만 함. 실제 명의 일치는 관세청 조회로 확인)"""
    c = (code or "").strip().upper()
    return bool(re.fullmatch(r"P\d{12}", c)), c
