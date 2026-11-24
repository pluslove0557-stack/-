"""전자책 디자인/출력: 표지 3종, 3D 목업, 본문 PDF, 판매 랜딩페이지, 광고 이미지, 최종 zip."""
import base64
import html
import io
import json
import os
import re
import threading
import zipfile
from contextlib import contextmanager

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ------------------------------------------------------------------ 폰트

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_FONT_DIR = os.path.join(BASE_DIR, "data", "fonts")  # 여기에 .ttf를 넣으면 글꼴 목록에 추가된다

# (표시 이름, 일반 후보 경로들, 굵게 후보 경로들)
FONT_CATALOG = {
    "nanum_gothic": ("나눔고딕", ["C:/Windows/Fonts/NanumGothic.ttf", "/Library/Fonts/NanumGothic.ttf", "~/Library/Fonts/NanumGothic.ttf",
                                 "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"],
                     ["C:/Windows/Fonts/NanumGothicBold.ttf", "/Library/Fonts/NanumGothicBold.ttf", "~/Library/Fonts/NanumGothicBold.ttf",
                      "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]),
    "nanum_myeongjo": ("나눔명조", ["C:/Windows/Fonts/NanumMyeongjo.ttf", "/Library/Fonts/NanumMyeongjo.ttf", "~/Library/Fonts/NanumMyeongjo.ttf",
                                   "/usr/share/fonts/truetype/nanum/NanumMyeongjo.ttf"],
                       ["C:/Windows/Fonts/NanumMyeongjoBold.ttf", "/Library/Fonts/NanumMyeongjoBold.ttf", "~/Library/Fonts/NanumMyeongjoBold.ttf",
                        "/usr/share/fonts/truetype/nanum/NanumMyeongjoBold.ttf"]),
    "nanum_pen": ("나눔손글씨 펜", ["C:/Windows/Fonts/NanumPen.ttf", "/Library/Fonts/NanumPen.ttf", "/usr/share/fonts/truetype/nanum/NanumPen.ttf"], []),
    "malgun": ("맑은 고딕", ["C:/Windows/Fonts/malgun.ttf"], ["C:/Windows/Fonts/malgunbd.ttf"]),
    "apple_sd": ("Apple SD 산돌고딕 Neo", ["/System/Library/Fonts/AppleSDGothicNeo.ttc"], []),
    "noto_sans": ("Noto Sans CJK", ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"],
                  ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc"]),
    "wqy": ("WenQuanYi 정흑(기본 한글)", ["/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"], []),
}


def _first_existing(paths):
    for p in paths:
        p = os.path.expanduser(p or "")
        if p and os.path.exists(p):
            return p
    return None


def available_fonts():
    """{키: {"name", "regular", "bold"}} — 이 컴퓨터에 실제로 있는 한글 글꼴만."""
    out = {}
    env = os.environ.get("EBOOK_FONT")
    if env and os.path.exists(env):
        out["env"] = {"name": f"지정 글꼴 ({os.path.basename(env)})", "regular": env,
                      "bold": _first_existing([os.environ.get("EBOOK_FONT_BOLD", "")]) or env}
    for key, (name, regs, bolds) in FONT_CATALOG.items():
        r = _first_existing(regs)
        if r:
            out[key] = {"name": name, "regular": r, "bold": _first_existing(bolds) or r}
    if os.path.isdir(USER_FONT_DIR):
        for f in sorted(os.listdir(USER_FONT_DIR)):
            if f.lower().endswith((".ttf", ".otf", ".ttc")) and "bold" not in f.lower():
                path = os.path.join(USER_FONT_DIR, f)
                stem = os.path.splitext(f)[0]
                bold = _first_existing([os.path.join(USER_FONT_DIR, stem + suf) for suf in ("Bold.ttf", "-Bold.ttf", "_Bold.ttf", "B.ttf")])
                out["user_" + re.sub(r"[^a-z0-9]", "_", stem.lower())] = {"name": f"내 글꼴: {stem}", "regular": path, "bold": bold or path}
    return out


def fontset(key=None):
    fonts = available_fonts()
    if key in fonts:
        return fonts[key]
    return next(iter(fonts.values()), {"name": "기본", "regular": None, "bold": None})


def font_status():
    fonts = available_fonts()
    return ", ".join(f["name"] for f in fonts.values()) or "한글 폰트를 찾지 못함 (data/fonts/에 .ttf를 넣거나 EBOOK_FONT 지정)"


_local = threading.local()


@contextmanager
def use_font(key):
    """이 블록 안의 모든 이미지/PDF 렌더링에 선택한 글꼴을 쓴다 (요청 스레드별)."""
    prev = getattr(_local, "fs", None)
    _local.fs = fontset(key)
    try:
        yield _local.fs
    finally:
        _local.fs = prev


def pil_font(size, bold=False, fs=None):
    fs = fs or getattr(_local, "fs", None) or fontset()
    path = fs.get("bold" if bold else "regular")
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


# ------------------------------------------------------------------ 팔레트/스타일

PALETTES = {
    "midnight": {"ink": "#3a2f7a", "name": "미드나잇", "bg": "#1b1f3b", "bg2": "#3a2f7a", "fg": "#ffffff", "accent": "#ffd166"},
    "sunrise": {"ink": "#d9480f", "name": "선라이즈", "bg": "#ff7e5f", "bg2": "#feb47b", "fg": "#2b1b17", "accent": "#ffffff"},
    "forest": {"ink": "#1f4037", "name": "포레스트", "bg": "#1f4037", "bg2": "#99f2c8", "fg": "#ffffff", "accent": "#fff3b0"},
    "paper": {"ink": "#c8553d", "name": "페이퍼", "bg": "#f4efe6", "bg2": "#e6dccb", "fg": "#2d2a26", "accent": "#c8553d"},
    "ocean": {"ink": "#2c5364", "name": "오션", "bg": "#0f2027", "bg2": "#2c5364", "fg": "#ffffff", "accent": "#7fdbff"},
}
STYLES = {"bold": "임팩트형", "poster": "포스터형", "minimal": "미니멀형", "classic": "클래식형"}


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _gradient(w, h, c1, c2):
    a, b = _hex(c1), _hex(c2)
    img = Image.new("RGB", (w, h), a)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    return img


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.replace("\n", " \n ").split(" "):
        if word == "\n":
            lines.append(cur.strip()); cur = ""; continue
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in word:  # 공백 없는 긴 한글 단어는 글자 단위로 줄바꿈
            if draw.textlength(cur + ch, font=font) > max_w and cur:
                lines.append(cur); cur = ch
            else:
                cur += ch
    if cur.strip():
        lines.append(cur.strip())
    return [l for l in lines if l]


def _fit_text(draw, text, max_w, max_h, start, minimum, bold=True, spacing=1.25):
    size = start
    while size >= minimum:
        f = pil_font(size, bold)
        lines = _wrap(draw, text, f, max_w)
        if len(lines) * size * spacing <= max_h:
            return f, lines, size
        size -= 4
    f = pil_font(minimum, bold)
    return f, _wrap(draw, text, f, max_w), minimum


def _draw_lines(draw, lines, font, size, x, y, fill, align="left", width=0, spacing=1.25):
    for line in lines:
        lx = x
        if align == "center":
            lx = x + (width - draw.textlength(line, font=font)) / 2
        draw.text((lx, y), line, font=font, fill=fill)
        y += int(size * spacing)
    return y


def render_cover(title, subtitle, author, style="bold", palette="midnight", w=1200, h=1700):
    p = PALETTES.get(palette, PALETTES["midnight"])
    fg, accent = _hex(p["fg"]), _hex(p["accent"])
    margin = 110
    if style == "minimal":
        img = Image.new("RGB", (w, h), _hex(p["bg"]))
        d = ImageDraw.Draw(img)
        d.rectangle([margin, 260, margin + 120, 272], fill=accent)
        f, lines, size = _fit_text(d, title, w - 2 * margin, 620, 120, 56)
        y = _draw_lines(d, lines, f, size, margin, 330, fg)
        sf, slines, ss = _fit_text(d, subtitle, w - 2 * margin, 260, 52, 30, bold=False, spacing=1.45)
        _draw_lines(d, slines, sf, ss, margin, y + 50, fg, spacing=1.45)
        af = pil_font(44)
        d.text((margin, h - 190), author, font=af, fill=accent)
    elif style == "classic":
        img = Image.new("RGB", (w, h), _hex(p["bg"]))
        d = ImageDraw.Draw(img)
        d.rectangle([60, 60, w - 60, h - 60], outline=accent, width=6)
        d.rectangle([84, 84, w - 84, h - 84], outline=accent, width=2)
        sf, slines, ss = _fit_text(d, subtitle, w - 2 * 160, 220, 46, 28, bold=False, spacing=1.4)
        _draw_lines(d, slines, sf, ss, 160, 300, fg, "center", w - 320, 1.4)
        f, lines, size = _fit_text(d, title, w - 2 * 160, 640, 112, 54)
        block = len(lines) * int(size * 1.25)
        _draw_lines(d, lines, f, size, 160, (h - block) // 2 + 40, fg, "center", w - 320)
        d.line([(w / 2 - 80, h - 300), (w / 2 + 80, h - 300)], fill=accent, width=4)
        af = pil_font(46)
        d.text(((w - d.textlength(author, font=af)) / 2, h - 250), author, font=af, fill=fg)
    elif style == "poster":
        img = Image.new("RGB", (w, h), _hex(p["bg"]))
        d = ImageDraw.Draw(img, "RGBA")
        for i in range(-h, w, 90):  # 사선 줄무늬 배경
            d.line([(i, h), (i + h, 0)], fill=_hex(p["bg2"]) + (90,), width=34)
        band_top = int(h * 0.50)
        d.rectangle([0, band_top, w, h], fill=_hex(p["bg2"]) + (235,))
        sf, slines, ss = _fit_text(d, subtitle, w - 2 * margin, 200, 48, 28, bold=False, spacing=1.4)
        _draw_lines(d, slines, sf, ss, margin, 150, fg, spacing=1.4)
        f, lines, size = _fit_text(d, title, w - 2 * margin, int(h * 0.30), 150, 64)
        r, g, b = _hex(p["bg2"])[:3]
        band_dark = (0.299 * r + 0.587 * g + 0.114 * b) < 140  # 띠가 어두우면 글자를 밝게
        title_fill = _hex("#ffffff") if band_dark else (_hex(p["bg"]) if p["fg"] == "#ffffff" else fg)
        _draw_lines(d, lines, f, size, margin, band_top + 70, title_fill, spacing=1.18)
        d.rectangle([margin, h - 230, margin + 160, h - 220], fill=accent)
        af = pil_font(46, True)
        d.text((margin, h - 190), author, font=af, fill=title_fill)
    else:  # bold
        img = _gradient(w, h, p["bg"], p["bg2"])
        d = ImageDraw.Draw(img, "RGBA")
        d.ellipse([w - 520, -260, w + 260, 520], fill=accent + (70,))
        d.ellipse([-300, h - 520, 420, h + 200], fill=accent + (45,))
        badge = pil_font(40, True)
        d.rounded_rectangle([margin, 200, margin + 300, 272], 36, fill=accent)
        d.text((margin + 34, 212), "실전 전자책", font=badge, fill=_hex(p["bg"]))
        f, lines, size = _fit_text(d, title, w - 2 * margin, 760, 132, 60)
        y = _draw_lines(d, lines, f, size, margin, 340, fg)
        sf, slines, ss = _fit_text(d, subtitle, w - 2 * margin, 260, 50, 30, bold=False, spacing=1.4)
        _draw_lines(d, slines, sf, ss, margin, y + 40, fg, spacing=1.4)
        af = pil_font(46, True)
        d.text((margin, h - 200), author, font=af, fill=fg)
    return img


def render_mockup(cover, size=(1400, 1400), bg="#eef0f4"):
    """표지로 간단한 3D 책 목업 이미지를 만든다 (책등 + 그림자 + 원근)."""
    W, H = size
    canvas = Image.new("RGB", (W, H), _hex(bg))
    ch = int(H * 0.72)
    cw = int(cover.width * ch / cover.height)
    front = cover.resize((cw, ch), Image.LANCZOS)
    spine_w = int(cw * 0.07)
    x0, y0 = (W - cw) // 2 + spine_w // 2, (H - ch) // 2

    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rectangle([x0 + 30, y0 + 40, x0 + cw + 40, y0 + ch + 30], fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(35))
    canvas.paste(Image.new("RGB", (W, H), (40, 44, 52)), (0, 0), shadow)

    spine = front.crop((0, 0, max(1, spine_w), ch)).resize((spine_w, ch))
    spine = Image.blend(spine, Image.new("RGB", spine.size, (0, 0, 0)), 0.45)
    spine = spine.transform(spine.size, Image.QUAD, (0, -ch * 0.03, 0, ch * 1.03, spine_w, ch, spine_w, 0), Image.BICUBIC)
    canvas.paste(spine, (x0 - spine_w, y0))
    canvas.paste(front, (x0, y0))
    gloss = Image.new("L", (cw, ch), 0)
    gd = ImageDraw.Draw(gloss)
    for i in range(cw // 3):
        gd.line([(i, 0), (i, ch)], fill=int(40 * (1 - i / (cw / 3))))
    canvas.paste(Image.new("RGB", (cw, ch), (255, 255, 255)), (x0, y0), gloss)
    return canvas


def png_bytes(img, fmt="PNG"):
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


# ------------------------------------------------------------------ PDF 본문

def _pdf_fonts():
    """현재 선택된 글꼴을 reportlab에 등록. TrueType이 아니면 내장 CID 한글 글꼴로 대체."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    fs = getattr(_local, "fs", None) or fontset()
    names = []
    for kind in ("regular", "bold"):
        path = fs.get(kind)
        if not path:
            break
        name = "EB_" + re.sub(r"[^A-Za-z0-9]", "_", os.path.basename(path))
        if name not in pdfmetrics.getRegisteredFontNames():
            try:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0) if path.lower().endswith(".ttc") else TTFont(name, path))
            except Exception:
                break
        names.append(name)
    if len(names) == 2:
        return names[0], names[1]
    if "HYGothic-Medium" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
    return "HYGothic-Medium", "HYGothic-Medium"


def _inline(md_text):
    t = html.escape(md_text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<link href="\2" color="#3a5bd9">\1</link>', t)
    return t


def build_pdf(book, cover_img, body_style="comfort", accent="#7c5cff"):
    """스마트폰 가독성 기준 A5 PDF. body_style: comfort(넉넉한 줄간격) / compact."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

    reg, bold = _pdf_fonts()
    big = body_style == "comfort"
    base = 11.5 if big else 10.5
    lead = base * (1.85 if big else 1.6)
    ac = HexColor(accent)
    st = {
        "body": ParagraphStyle("body", fontName=reg, fontSize=base, leading=lead, spaceAfter=base * 0.8, wordWrap="CJK"),
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=20, leading=28, spaceAfter=14, textColor=ac, wordWrap="CJK"),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=14.5, leading=21, spaceBefore=12, spaceAfter=8, wordWrap="CJK"),
        "h3": ParagraphStyle("h3", fontName=bold, fontSize=12.5, leading=18, spaceBefore=8, spaceAfter=6, textColor=ac, wordWrap="CJK"),
        "li": ParagraphStyle("li", fontName=reg, fontSize=base, leading=lead, leftIndent=12, bulletIndent=2, spaceAfter=2, wordWrap="CJK"),
        "quote": ParagraphStyle("quote", fontName=bold, fontSize=base, leading=lead, textColor=HexColor("#333333"), wordWrap="CJK"),
        "toc": ParagraphStyle("toc", fontName=reg, fontSize=12, leading=22, wordWrap="CJK"),
        "cell": ParagraphStyle("cell", fontName=reg, fontSize=base - 1.5, leading=(base - 1.5) * 1.45, wordWrap="CJK"),
        "small": ParagraphStyle("small", fontName=reg, fontSize=9, leading=14, textColor=HexColor("#777777"), wordWrap="CJK"),
    }
    toc = book["toc"]
    buf = io.BytesIO()
    margin = 16 * mm
    doc = SimpleDocTemplate(buf, pagesize=A5, leftMargin=margin, rightMargin=margin, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=toc["title"], author=book["profile"].get("author_name", ""))
    fw, fh = A5[0] - 2 * margin, A5[1] - 36 * mm

    def on_page(canvas, d):
        if d.page > 1:
            canvas.setFont(reg, 8.5)
            canvas.setFillColor(HexColor("#999999"))
            canvas.drawCentredString(A5[0] / 2, 10 * mm, str(d.page - 1))

    story = []
    cimg = io.BytesIO(png_bytes(cover_img.convert("RGB"), "JPEG"))
    ratio = min(fw / cover_img.width, fh / cover_img.height)
    story += [RLImage(cimg, cover_img.width * ratio, cover_img.height * ratio), PageBreak()]

    story += [Paragraph("목차", st["h1"])]
    prologue = (book.get("chapters") or {}).get("prologue")
    if prologue:
        story.append(Paragraph("프롤로그", st["toc"]))
    for i, c in enumerate(toc["chapters"]):
        story.append(Paragraph(f"{i + 1}장 &nbsp; {html.escape(c['title'])}", st["toc"]))
    story.append(PageBreak())
    if prologue:
        story.append(Paragraph("프롤로그", st["h1"]))
        story += _md_to_flowables(prologue, st, ac, fw, Paragraph, Spacer, Table, TableStyle, HexColor)
        story.append(PageBreak())

    for i, c in enumerate(toc["chapters"]):
        story.append(Paragraph(f"{i + 1}장", st["h3"]))
        story.append(Paragraph(html.escape(c["title"]), st["h1"]))
        body = (book.get("chapters") or {}).get(str(i), "")
        story += _md_to_flowables(body, st, ac, fw, Paragraph, Spacer, Table, TableStyle, HexColor)
        story.append(PageBreak())

    story.append(Paragraph("저자 소개", st["h2"]))
    story.append(Paragraph(_inline(book["profile"].get("persona", "") + " " + book["profile"].get("experience", "")), st["body"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph("이 전자책의 저작권은 저자에게 있으며 무단 복제·배포를 금합니다.", st["small"]))
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _check_item(text, st, fw, Paragraph, Table, TableStyle, HexColor):
    """글꼴 글리프에 의존하지 않도록 체크박스를 벡터 사각형으로 그린다."""
    from reportlab.graphics.shapes import Drawing, Rect
    size = st["body"].fontSize * 0.85
    box = Drawing(size + 2, size + 2)
    box.add(Rect(1, 1, size, size, strokeColor=HexColor("#555555"), fillColor=None, strokeWidth=0.9))
    t = Table([[box, Paragraph(text, st["body"])]], colWidths=[size + 8, fw - size - 8])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (0, 0), st["body"].leading * 0.22), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (1, 0), (1, 0), 0)]))
    return t


def _md_to_flowables(md, st, ac, fw, Paragraph, Spacer, Table, TableStyle, HexColor):
    out, para = [], []

    def flush():
        if para:
            out.append(Paragraph(_inline(" ".join(para)), st["body"]))
            para.clear()

    rows = []

    def flush_table():
        if not rows:
            return
        ncol = max(len(r) for r in rows)
        data = [[Paragraph(_inline(c), st["cell"]) for c in r + [""] * (ncol - len(r))] for r in rows]
        t = Table(data, colWidths=[fw / ncol] * ncol, repeatRows=1)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")), ("BACKGROUND", (0, 0), (-1, 0), HexColor("#f1f1f5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        out.extend([Spacer(1, 4), t, Spacer(1, 8)])
        rows.clear()

    for raw in (md or "").splitlines():
        line = raw.rstrip()
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            flush()
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                rows.append(cells)
            continue
        flush_table()
        if not s:
            flush(); continue
        if s.startswith("### "):
            flush(); out.append(Paragraph(_inline(s[4:]), st["h3"]))
        elif s.startswith("## ") or s.startswith("# "):
            flush(); out.append(Paragraph(_inline(s.lstrip("#").strip()), st["h2"]))
        elif re.match(r"^[-*] \[[ xX]\] ", s):
            flush(); out.append(_check_item(_inline(s[6:]), st, fw, Paragraph, Table, TableStyle, HexColor))
        elif re.match(r"^[-*] ", s):
            flush(); out.append(Paragraph(_inline(s[2:]), st["li"], bulletText="•"))
        elif re.match(r"^\d+[.)] ", s):
            flush(); num, rest = s.split(" ", 1); out.append(Paragraph(_inline(rest), st["li"], bulletText=num))
        elif s.startswith(">"):
            flush()
            t = Table([[Paragraph(_inline(s.lstrip("> ").strip()), st["quote"])]], colWidths=[fw])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f3f1ff")),
                ("LINEBEFORE", (0, 0), (0, -1), 3, ac),
                ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            out += [Spacer(1, 4), t, Spacer(1, 8)]
        elif s in ("---", "***"):
            flush(); out.append(Spacer(1, 12))
        else:
            para.append(s)
    flush()
    flush_table()
    return out


def manuscript_markdown(book):
    toc = book["toc"]
    parts = [f"# {toc['title']}", f"_{toc['subtitle']}_", ""]
    if (book.get("chapters") or {}).get("prologue"):
        parts += ["# 프롤로그", "", book["chapters"]["prologue"], ""]
    for i, c in enumerate(toc["chapters"]):
        parts += [f"# {i + 1}장. {c['title']}", "", (book.get("chapters") or {}).get(str(i), ""), ""]
    return "\n".join(parts)


# ------------------------------------------------------------------ 판매 랜딩페이지

def landing_html(book, copy, cover_png, buy_url="", price="", theme="#7c5cff"):
    L = copy["landing"]
    toc = book["toc"]
    e = html.escape
    img64 = base64.b64encode(cover_png).decode()
    price_txt = f"{int(price):,}원" if str(price).isdigit() else e(str(price or ""))
    buy = e(buy_url or "#")
    pains = "".join(f"<li>{e(x)}</li>" for x in L["pains"])
    bens = "".join(f"<li>{e(x)}</li>" for x in L["benefits"])
    chs = "".join(f"<li><b>{i + 1}장</b> {e(c['title'])}</li>" for i, c in enumerate(toc["chapters"]))
    faq = "".join(f"<details><summary>{e(f['q'])}</summary><p>{e(f['a'])}</p></details>" for f in L["faq"])
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(toc['title'])}</title>
<meta property="og:title" content="{e(toc['title'])}"><meta property="og:description" content="{e(L['subhead'])}">
<style>
:root{{--c:{e(theme)};--bg:#ffffff;--tx:#1d1d1f;--mu:#6b6b72;--pn:#f6f6f9}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111216;--tx:#ececf1;--mu:#a1a1aa;--pn:#1b1c22}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,"Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif;line-height:1.7}}
.wrap{{max-width:720px;margin:0 auto;padding:0 16px}}
.hero{{text-align:center;padding:48px 0 32px}}.hero img{{width:min(280px,70%);border-radius:6px;box-shadow:0 20px 40px rgba(0,0,0,.25)}}
h1{{font-size:clamp(1.6rem,5vw,2.3rem);line-height:1.3;margin:24px 0 8px}}.sub{{color:var(--mu)}}
.cta{{display:block;text-align:center;background:var(--c);color:#fff;text-decoration:none;font-weight:700;padding:16px;border-radius:12px;font-size:1.1rem;margin:20px 0}}
section{{background:var(--pn);border-radius:16px;padding:22px 20px;margin:16px 0}}h2{{font-size:1.25rem;margin-top:0}}
ul{{padding-left:20px}}li{{margin:6px 0}}details{{border-bottom:1px solid rgba(127,127,127,.25);padding:10px 0}}summary{{cursor:pointer;font-weight:600}}
.price{{text-align:center;font-size:1.6rem;font-weight:800}}.sticky{{position:sticky;bottom:0;background:var(--bg);padding:8px 0}}
footer{{color:var(--mu);font-size:.8rem;text-align:center;padding:30px 0}}
</style></head><body><div class="wrap">
<div class="hero"><img src="data:image/png;base64,{img64}" alt="{e(toc['title'])} 표지">
<h1>{e(L['headline'])}</h1><p class="sub">{e(L['subhead'])}</p></div>
<section><h2>이런 고민, 있으신가요?</h2><ul>{pains}</ul></section>
<section><h2>이 책에서 얻게 되는 것</h2><ul>{bens}</ul></section>
<section><h2>목차</h2><ul>{chs}</ul></section>
<section><h2>저자 소개</h2><p>{e(L['author_intro'])}</p></section>
<section><h2>자주 묻는 질문</h2>{faq}</section>
<p class="price">{price_txt}</p>
<div class="sticky"><a class="cta" href="{buy}">지금 바로 받아보기</a></div>
<footer>PDF 전자책 · 결제 후 다운로드 링크가 제공됩니다</footer>
</div></body></html>"""


# ------------------------------------------------------------------ 광고 이미지

def render_ad(cover, hook, headline, palette="midnight", size=(1080, 1080)):
    p = PALETTES.get(palette, PALETTES["midnight"])
    W, H = size
    img = _gradient(W, H, p["bg"], p["bg2"])
    d = ImageDraw.Draw(img)
    fg, accent = _hex(p["fg"]), _hex(p["accent"])
    f, lines, s = _fit_text(d, hook, W - 140, int(H * 0.22), 86, 44)
    y = _draw_lines(d, lines, f, s, 70, 70, accent)
    mock = render_mockup(cover, (int(H * 0.62), int(H * 0.62)), bg=p["bg2"])
    mask = Image.new("L", mock.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, mock.width, mock.height], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(40))
    img.paste(mock, ((W - mock.width) // 2, max(y + 10, H - mock.height - 130)), mask)
    hf, hl, hs = _fit_text(d, headline, W - 140, 110, 44, 28, spacing=1.3)
    _draw_lines(d, hl, hf, hs, 70, H - 40 - len(hl) * int(hs * 1.3), fg, "center", W - 140, 1.3)
    return img


# ------------------------------------------------------------------ 카드뉴스

def render_card(title, body, page, total, palette="paper", style="note", size=(1080, 1350)):
    """카드뉴스 한 장. style: note(노트에 손으로 쓴 느낌) / clean(단색 깔끔)."""
    p = PALETTES.get(palette, PALETTES["paper"])
    W, H = size
    accent, ink = _hex(p["accent"]), _hex(p["ink"])
    if style == "note":
        img = Image.new("RGB", (W, H), (252, 250, 243))
        d = ImageDraw.Draw(img, "RGBA")
        for y in range(220, H - 80, 64):
            d.line([(80, y), (W - 60, y)], fill=(170, 190, 220, 120), width=2)
        d.line([(130, 0), (130, H)], fill=(230, 120, 120, 150), width=3)
        for y in range(120, H, 230):  # 스프링 구멍
            d.ellipse([28, y, 62, y + 34], fill=(220, 216, 205))
        text_col, x0 = (40, 40, 48), 170
        hl = accent if p["accent"] != "#ffffff" else _hex(p["bg2"])
    else:
        img = _gradient(W, H, p["bg"], p["bg2"])
        d = ImageDraw.Draw(img, "RGBA")
        text_col, x0, hl = _hex(p["fg"]), 90, accent
    tf, tl, ts = _fit_text(d, title, W - x0 - 90, int(H * 0.30), 92, 48)
    y = 230 if page == 1 else 170
    if page == 1:
        y = int(H * 0.30)
    for line in tl:
        tw = d.textlength(line, font=tf)
        d.rectangle([x0 - 6, y + int(ts * 0.55), x0 + tw + 6, y + int(ts * 1.05)], fill=hl + (110,))  # 형광펜
        d.text((x0, y), line, font=tf, fill=text_col)
        y += int(ts * 1.3)
    if body:
        bf, bl, bs = _fit_text(d, body, W - x0 - 90, H - y - 200, 50, 30, bold=False, spacing=1.6)
        _draw_lines(d, bl, bf, bs, x0, y + 50, text_col, spacing=1.6)
    nf = pil_font(32)
    d.text((W - 150, H - 90), f"{page}/{total}", font=nf, fill=text_col)
    if page < total:
        d.text((x0, H - 90), "넘겨보세요 →", font=nf, fill=ink if style == "note" else text_col)
    return img


# ------------------------------------------------------------------ 최종 결과물

def bundle_zip(book, files):
    """files: {zip 내부 경로: bytes}"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr("project.json", json.dumps(book, ensure_ascii=False, indent=2))
    return buf.getvalue()
