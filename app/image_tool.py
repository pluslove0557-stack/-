"""이미지 변환 프로그램 - 상품 이미지 일괄 리사이즈 / 배경제거 / 워터마크 / 포맷변환.

'AI 배경제거'는 두 단계로 동작한다.
1) rembg가 설치되어 있으면 실제 AI 세그멘테이션 모델(u2net)로 배경을 제거한다.
2) 설치되어 있지 않으면, 상품사진에 흔한 흰색/단색 배경을 감지해 제거하는
   경량 규칙 기반(색상 임계값) 방식으로 대체 동작한다. 이 경우 UI에 방식이
   무엇인지 명확히 표시한다.
"""

import io
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    from rembg import remove as _rembg_remove
    AI_BG_REMOVAL_AVAILABLE = True
except ImportError:
    AI_BG_REMOVAL_AVAILABLE = False


def load_image(file_bytes):
    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img)
    return img.convert("RGBA")


def remove_background_ai(img: Image.Image) -> Image.Image:
    """rembg(u2net)를 이용한 실제 AI 배경 제거. 미설치 시 None 반환."""
    if not AI_BG_REMOVAL_AVAILABLE:
        return None
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    out_bytes = _rembg_remove(buf.getvalue())
    return Image.open(io.BytesIO(out_bytes)).convert("RGBA")


def remove_near_solid_background(img: Image.Image, threshold: int = 235, tolerance: int = 18) -> Image.Image:
    """흰색/단색 배경을 감지해 투명화하는 경량 대체 방식.

    threshold: 이 값보다 밝은(흰색에 가까운) 픽셀을 배경 후보로 본다 (0-255).
    tolerance: 좌상단 모서리 색상 기준 허용 오차.
    """
    arr = np.array(img.convert("RGBA")).astype(np.int16)
    h, w = arr.shape[0], arr.shape[1]
    corner_color = arr[0, 0, :3]

    rgb = arr[:, :, :3]
    diff = np.abs(rgb - corner_color).max(axis=2)
    is_bright = rgb.min(axis=2) >= threshold
    is_near_corner = diff <= tolerance
    bg_mask = is_bright | is_near_corner

    out = arr.copy()
    out[:, :, 3] = np.where(bg_mask, 0, out[:, :, 3])
    return Image.fromarray(out.astype(np.uint8), mode="RGBA")


def pad_to_square(img: Image.Image, size: int = 1000, bg_color=(255, 255, 255, 255)) -> Image.Image:
    img = img.copy()
    img.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), bg_color)
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    canvas.paste(img, (x, y), img)
    return canvas


def resize_keep_ratio(img: Image.Image, max_size: int = 1000) -> Image.Image:
    img = img.copy()
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    return img


def add_watermark(img: Image.Image, text: str, opacity: int = 110, position: str = "bottom-right") -> Image.Image:
    if not text:
        return img
    base = img.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(14, base.width // 22)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except IOError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = base.width // 40

    positions = {
        "bottom-right": (base.width - tw - margin, base.height - th - margin),
        "bottom-left": (margin, base.height - th - margin),
        "top-right": (base.width - tw - margin, margin),
        "top-left": (margin, margin),
        "center": ((base.width - tw) // 2, (base.height - th) // 2),
    }
    xy = positions.get(position, positions["bottom-right"])

    draw.text(xy, text, font=font, fill=(255, 255, 255, opacity))
    combined = Image.alpha_composite(base, overlay)
    return combined


def process_image(file_bytes, opts):
    """옵션에 따라 파이프라인을 적용하고 (Image, 사용된 배경제거 방식) 을 반환."""
    img = load_image(file_bytes)
    bg_method = None

    if opts.get("remove_bg"):
        if opts.get("bg_method", "auto") in ("auto", "ai"):
            ai_result = remove_background_ai(img)
            if ai_result is not None:
                img = ai_result
                bg_method = "ai"
        if bg_method is None and opts.get("bg_method", "auto") in ("auto", "simple"):
            img = remove_near_solid_background(
                img,
                threshold=int(opts.get("bg_threshold", 235)),
                tolerance=int(opts.get("bg_tolerance", 18)),
            )
            bg_method = "simple"

    if opts.get("pad_square"):
        img = pad_to_square(img, size=int(opts.get("size", 1000)))
    elif opts.get("resize"):
        img = resize_keep_ratio(img, max_size=int(opts.get("size", 1000)))

    if opts.get("watermark_text"):
        img = add_watermark(
            img,
            opts.get("watermark_text"),
            opacity=int(opts.get("watermark_opacity", 110)),
            position=opts.get("watermark_position", "bottom-right"),
        )

    return img, bg_method


def image_to_bytes(img: Image.Image, fmt: str = "PNG"):
    buf = io.BytesIO()
    fmt = fmt.upper()
    if fmt in ("JPG", "JPEG"):
        img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=92)
    else:
        img.save(buf, format="PNG")
    buf.seek(0)
    return buf
