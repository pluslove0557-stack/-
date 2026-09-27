"""이미지 변환 프롬프터 - 상품 이미지를 AI 이미지 도구(미드저니/달리/포토룸 등)로
보정/합성할 때 쓸 프롬프트를 조합해서 생성한다.
"""

BACKGROUNDS = {
    "white_studio": {"label": "화이트 스튜디오", "ko": "깔끔한 순백색 스튜디오 배경", "en": "clean pure white seamless studio background"},
    "gradient": {"label": "그라데이션", "ko": "은은한 파스텨톤 그라데이션 배경", "en": "soft pastel gradient background"},
    "lifestyle": {"label": "라이프스타일 연출", "ko": "실제 생활공간(거실/주방/테이블) 속 자연스러운 연출", "en": "natural lifestyle setting such as a living room or kitchen table"},
    "outdoor": {"label": "야외/자연광", "ko": "자연광이 드는 야외 배경", "en": "outdoor scene with natural daylight"},
    "marble": {"label": "대리석/프리미엄", "ko": "대리석 질감의 프리미엄 배경", "en": "premium marble surface background"},
    "seasonal": {"label": "시즌/이벤트 테마", "ko": "계절감이 느껴지는 시즌 테마 소품 배경", "en": "seasonal themed props in the background"},
}

LIGHTINGS = {
    "softbox": {"label": "소프트박스 조명", "en": "soft diffused studio softbox lighting, no harsh shadows"},
    "natural": {"label": "자연광", "en": "natural window light, soft shadows"},
    "dramatic": {"label": "드라마틱 조명", "en": "dramatic side lighting with strong contrast"},
    "backlit": {"label": "역광/실루엣", "en": "subtle backlight creating a soft rim light"},
}

ANGLES = {
    "front": {"label": "정면컷", "en": "straight-on front view"},
    "45deg": {"label": "45도 앵글", "en": "45-degree angle view"},
    "top": {"label": "탑뷰(플랫레이)", "en": "top-down flat lay view"},
    "closeup": {"label": "클로즈업/디테일컷", "en": "close-up macro detail shot"},
}

TONES = {
    "minimal": {"label": "미니멀", "en": "minimal, clean, uncluttered composition"},
    "luxury": {"label": "럭셔리", "en": "premium, luxurious, high-end commercial photography look"},
    "pop": {"label": "팝컬러", "en": "vibrant pop-color, energetic commercial style"},
    "natural": {"label": "내추럴", "en": "warm, natural, cozy everyday feeling"},
}


def options():
    return {
        "backgrounds": {k: v["label"] for k, v in BACKGROUNDS.items()},
        "lightings": {k: v["label"] for k, v in LIGHTINGS.items()},
        "angles": {k: v["label"] for k, v in ANGLES.items()},
        "tones": {k: v["label"] for k, v in TONES.items()},
    }


def generate_prompts(product_name, bg_key, light_key, angle_key, tone_key, count=3):
    bg = BACKGROUNDS.get(bg_key, list(BACKGROUNDS.values())[0])
    light = LIGHTINGS.get(light_key, list(LIGHTINGS.values())[0])
    angle = ANGLES.get(angle_key, list(ANGLES.values())[0])
    tone = TONES.get(tone_key, list(TONES.values())[0])

    product_name = (product_name or "상품").strip()

    base_ko = (
        f"{product_name} 제품 사진을 {bg['ko']}으로 합성하고, "
        f"{angle['label']}, {light['label']}을 적용해서 {tone['label']} 느낌으로 "
        f"상세페이지/썸네일용 컷으로 보정해줘. 제품 본연의 색상과 형태는 최대한 유지해줘."
    )
    base_en = (
        f"professional product photography of {product_name}, "
        f"{bg['en']}, {angle['en']}, {light['en']}, {tone['en']}, "
        f"high resolution commercial e-commerce photo, keep product shape and color accurate"
    )

    variants = []
    variant_pool = [
        (base_ko, base_en),
        (
            f"{base_ko} 그림자는 은은하게 살려서 입체감을 줘.",
            f"{base_en}, subtle soft shadow for depth, no distortion",
        ),
        (
            f"{base_ko} 배경에 어울리는 작은 소품을 1~2개만 자연스럽게 추가해줘.",
            f"{base_en}, add 1-2 small complementary props naturally placed",
        ),
        (
            f"{base_ko} 정사각형 1:1 비율, 상세페이지 상단 배너용으로 만들어줘.",
            f"{base_en}, square 1:1 aspect ratio, suitable for detail page top banner",
        ),
        (
            f"{base_ko} 인스타그램 카드뉴스 스타일로 여백을 넉넉히 남겨줘.",
            f"{base_en}, generous negative space, Instagram carousel card style",
        ),
    ]
    for ko, en in variant_pool[: max(1, min(count, len(variant_pool)))]:
        variants.append({"ko": ko, "en": en})

    return variants
