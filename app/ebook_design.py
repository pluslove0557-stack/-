"""전자책 디자인/출력: 표지 3종, 3D 목업, 본문 PDF, 판매 랜딩페이지, 광고 이미지, 최종 zip."""
import base64
import html
import io
import json
import os
import re
import zipfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ------------------------------------------------------------------ 폰트

FONT_CANDIDATES = [
    os.environ.get("EBOOK_FONT", ""),
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
BOLD_CANDIDATES = [
    os.environ.get("EBOOK_FONT_BOLD", ""),
    "C:/Windows/Fonts/malgunbd.ttf",
    "/Library/Fonts/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def _first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


FONT_PATH = _first_existing(FONT_CANDIDATES)
BOLD_PATH = _first_existing(BOLD_CANDIDATES) or FONT_PATH


def font_status():
    return FONT_PATH or "한글 폰트를 찾지 못함 (EBOOK_FONT 환경변수로 .ttf 경로 지정)"


def pil_font(size, bold=False):
    path = BOLD_PATH if bold else FONT_PATH
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
STYLES = {"bold": "임팩트형", "minimal": "미니멀형", "classic": "클래식형"}


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
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    if "EbookRegular" in pdfmetrics.getRegisteredFontNames():
        return "EbookRegular", "EbookBold"
    for name, path in (("EbookRegular", FONT_PATH), ("EbookBold", BOLD_PATH)):
        if not path:
            break
        try:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0) if path.endswith(".ttc") else TTFont(name, path))
        except Exception:
            break
    else:
        return "EbookRegular", "EbookBold"
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
    for i, c in enumerate(toc["chapters"]):
        story.append(Paragraph(f"{i + 1}장 &nbsp; {html.escape(c['title'])}", st["toc"]))
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


def _md_to_flowables(md, st, ac, fw, Paragraph, Spacer, Table, TableStyle, HexColor):
    out, para = [], []

    def flush():
        if para:
            out.append(Paragraph(_inline(" ".join(para)), st["body"]))
            para.clear()

    for raw in (md or "").splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            flush(); continue
        if s.startswith("### "):
            flush(); out.append(Paragraph(_inline(s[4:]), st["h3"]))
        elif s.startswith("## ") or s.startswith("# "):
            flush(); out.append(Paragraph(_inline(s.lstrip("#").strip()), st["h2"]))
        elif re.match(r"^[-*] \[[ xX]\] ", s):
            flush(); out.append(Paragraph(_inline(s[6:]), st["li"], bulletText="□"))
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
    return out


def manuscript_markdown(book):
    toc = book["toc"]
    parts = [f"# {toc['title']}", f"_{toc['subtitle']}_", ""]
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


# ------------------------------------------------------------------ 최종 결과물

def bundle_zip(book, files):
    """files: {zip 내부 경로: bytes}"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr("project.json", json.dumps(book, ensure_ascii=False, indent=2))
    return buf.getvalue()
