"""매일 전자책 1권 제작 파이프라인.

원고(spec JSON)를 받아 판매에 필요한 파일을 한 폴더에 만든다.
  - ebook.pdf, manuscript.md          : 구매자에게 줄 전자책과 수정용 원고
  - cover.png, mockup_3d.png          : 표지와 3D 목업
  - thumb_4x3.png, thumb_1x1.png      : 플랫폼 썸네일 (크몽·래피드·그로블 공용)
  - detail_*.png                      : 상세페이지용 이미지 (목차·이런 분께 추천)
  - groble.json                       : 그로블 save_product_draft 에 넣을 값
  - kmong.md, latpeed.md              : 크몽·래피드에 복사해 붙여 넣을 등록 문구
  - upload_package.zip                : 위 파일 전체

사용법:
  python -m app.daily_ebook daily/2026-11-21-ai-blog/spec.json
  python -m app.daily_ebook --next          # 다음 주제 확인 (daily/queue.json)

spec.json 형식은 daily/README.md 참고.
"""
import argparse
import html
import io
import json
import os
import re
import sys
import zipfile
from datetime import date

# 그림·PDF 라이브러리는 만들 때만 필요하다. 내보내기(--export)는 파이썬 기본 기능만으로 동작한다.
Image = ImageDraw = design = None


def _load_render_libs():
    global Image, ImageDraw, design
    if design is None:
        from PIL import Image as _Image, ImageDraw as _ImageDraw
        from app import ebook_design as _design
        Image, ImageDraw, design = _Image, _ImageDraw, _design

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_DIR = os.path.join(ROOT, "daily")
QUEUE_PATH = os.path.join(DAILY_DIR, "queue.json")

REQUIRED = ["title", "subtitle", "target", "pain", "price", "chapters", "prologue", "sales"]


def load_spec(path):
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    missing = [k for k in REQUIRED if not spec.get(k)]
    if missing:
        raise SystemExit(f"spec.json 에 빠진 항목: {', '.join(missing)}")
    for i, ch in enumerate(spec["chapters"]):
        for k in ("title", "body"):
            if not ch.get(k):
                raise SystemExit(f"{i + 1}장에 '{k}'가 없습니다.")
    if len(spec["title"]) > 30:
        raise SystemExit(f"제목이 {len(spec['title'])}자입니다. 그로블 제목은 30자 이하여야 합니다.")
    return spec


def to_book(spec):
    """ebook_design 이 쓰는 book 구조로 바꾼다."""
    chapters = {"prologue": spec["prologue"]}
    for i, ch in enumerate(spec["chapters"]):
        chapters[str(i)] = ch["body"]
    return {
        "toc": {
            "title": spec["title"], "subtitle": spec["subtitle"], "hook": spec["pain"],
            "chapters": [{"title": c["title"], "claim": c.get("claim", ""), "points": c.get("points", [])} for c in spec["chapters"]],
        },
        "chapters": chapters,
        "topic": {"title": spec["title"], "target": spec["target"], "pain": spec["pain"], "keywords": spec.get("keywords", [])},
        "profile": {"persona": spec.get("author_intro", ""), "experience": "", "author_name": spec.get("author", "")},
        "design": {"palette": spec.get("palette", "midnight"), "style": spec.get("cover_style", "bold"),
                   "font": spec.get("font"), "body": "comfort"},
    }


# ------------------------------------------------------------------ 이미지

def thumbnail(cover, size, palette, badge="", title="", subtitle=""):
    """표지 목업을 넣은 가로형/정사각 썸네일."""
    p = design.PALETTES.get(palette, design.PALETTES["midnight"])
    W, H = size
    img = design._gradient(W, H, p["bg"], p["bg2"])
    mock = design.render_mockup(cover, (int(H * 0.92), int(H * 0.92)), bg=p["bg2"])
    mask = Image.new("L", mock.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, mock.width, mock.height], fill=255)
    from PIL import ImageFilter
    mask = mask.filter(ImageFilter.GaussianBlur(50))
    if W > H:  # 가로형: 왼쪽 문구, 오른쪽 책
        img.paste(mock, (int(W * 0.75 - mock.width / 2), (H - mock.height) // 2), mask)
    else:
        img.paste(mock, ((W - mock.width) // 2, H - mock.height + int(H * 0.06)), mask)
    d = ImageDraw.Draw(img)
    if W > H and title:  # 가로형 왼쪽 빈 공간에 제목
        fg = design._hex(p["fg"])
        left_w = int(W * 0.46)
        tf, tl, ts = design._fit_text(d, title, left_w, int(H * 0.45), 88, 44)
        y = design._draw_lines(d, tl, tf, ts, int(W * 0.05), int(H * 0.30), fg, spacing=1.2)
        if subtitle:
            sf, sl, ss = design._fit_text(d, subtitle, left_w, int(H * 0.22), 40, 26, bold=False, spacing=1.4)
            design._draw_lines(d, sl, sf, ss, int(W * 0.05), y + 24, fg, spacing=1.4)
    if badge:
        f = design.pil_font(int(H * 0.06), True)
        tw = d.textlength(badge, font=f)
        x, y = int(W * 0.05), int(H * 0.07)
        d.rounded_rectangle([x, y, x + tw + 60, y + int(H * 0.06) + 40], 30, fill=design._hex(p["accent"]))
        d.text((x + 30, y + 18), badge, font=f, fill=design._hex(p["bg"]))
    return img


def detail_image(title, items, palette, size=(1080, 1350), numbered=True):
    """상세페이지용 목록 이미지 (목차, 이런 분께 추천 등)."""
    p = design.PALETTES.get(palette, design.PALETTES["midnight"])
    W, H = size
    img = Image.new("RGB", (W, H), (250, 250, 252))
    d = ImageDraw.Draw(img)
    ink, accent = design._hex(p["ink"]), design._hex(p["bg2"])
    d.rectangle([0, 0, W, 210], fill=design._hex(p["bg"]))
    tf, tl, ts = design._fit_text(d, title, W - 160, 150, 64, 36)
    design._draw_lines(d, tl, tf, ts, 80, 60, design._hex(p["fg"]))
    y = 270
    avail = H - y - 80
    per = max(90, min(200, avail // max(1, len(items))))
    for i, it in enumerate(items):
        if numbered:
            mf = design.pil_font(int(per * 0.32), True)
            d.text((80, y + 6), f"{i + 1:02d}", font=mf, fill=accent)
        else:  # 체크 표시는 글꼴에 없을 수 있어 선으로 그린다
            c = int(per * 0.28)
            d.line([(84, y + 10 + c * 0.55), (84 + c * 0.38, y + 10 + c), (84 + c, y + 10)], fill=accent, width=max(6, c // 6), joint="curve")
        bf, bl, bs = design._fit_text(d, it, W - 260, per - 20, int(per * 0.30), 26, bold=False, spacing=1.35)
        design._draw_lines(d, bl, bf, bs, 200, y + 8, ink, spacing=1.35)
        y += per
        d.line([(80, y - 12), (W - 80, y - 12)], fill=(225, 225, 232), width=2)
    return img


# ------------------------------------------------------------------ 등록 문구

def groble_payload(spec, slug):
    s = spec["sales"]
    e = html.escape
    lis = lambda xs: "<ul>" + "".join(f"<li>{e(x)}</li>" for x in xs) + "</ul>"
    toc = "<ol>" + "".join(f"<li>{e(c['title'])}</li>" for c in spec["chapters"]) + "</ol>"
    intro = (
        f"<h2>{e(s['headline'])}</h2><p>{e(s['subhead'])}</p>"
        f"<h3>이런 고민, 있으신가요?</h3>{lis(s['pains'])}"
        f"<h3>이 전자책에서 얻는 것</h3>{lis(s['benefits'])}"
        f"<h3>이런 분께 추천해요</h3>{lis(s['for_whom'])}"
        f"<h3>목차</h3>{toc}"
        f"<h3>구성</h3><p>PDF 전자책 · 약 {spec.get('pages', '')}쪽 · 스마트폰에서 읽기 좋은 판형</p>"
        + (f"<h3>저자 소개</h3><p>{e(spec['author_intro'])}</p>" if spec.get("author_intro") else "")
        + "<h3>안내</h3><p>결제 후 바로 PDF를 내려받을 수 있습니다. 디지털 콘텐츠 특성상 다운로드 후에는 환불이 제한될 수 있습니다.</p>"
    )
    return {
        "clientRequestId": f"daily-{slug}",
        "productType": "document",
        "title": spec["title"],
        "contentIntroduction": intro,
        "isReviewVisible": True, "isBuyerCountPublic": True, "isSearchExposed": True,
        "options": [{"name": "PDF 전자책", "price": int(spec["price"]), "description": spec["subtitle"][:60]}],
    }


def market_text(spec, platform):
    s = spec["sales"]
    name = {"kmong": "크몽", "latpeed": "래피드"}[platform]
    tags = spec.get("keywords", [])[:5]
    lines = [
        f"# {name} 등록 문구 — 복사해서 붙여 넣으세요",
        "",
        "## 제목",
        spec["title"],
        "",
        "## 한 줄 소개 / 부제",
        spec["subtitle"],
        "",
        "## 가격",
        f"{int(spec['price']):,}원",
        "",
        "## 카테고리 (추천)",
        "전자책 > " + spec.get("category", "부업·N잡 / IT·AI 활용"),
        "",
        "## 검색 태그",
        ", ".join(tags),
        "",
        "## 썸네일",
        "thumb_4x3.png (가로형) — 크몽은 4:3 가로형 이미지를 씁니다. 등록 화면의 최신 규격 안내와 크기를 한 번 확인하세요."
        if platform == "kmong" else "thumb_1x1.png 또는 thumb_4x3.png — 래피드 상품 등록 화면 규격에 맞는 쪽을 쓰세요.",
        "",
        "## 상세 설명",
        f"**{s['headline']}**",
        "",
        s["subhead"],
        "",
        "### 이런 고민, 있으신가요?",
        *[f"- {x}" for x in s["pains"]],
        "",
        "### 이 전자책에서 얻는 것",
        *[f"- {x}" for x in s["benefits"]],
        "",
        "### 이런 분께 추천해요",
        *[f"- {x}" for x in s["for_whom"]],
        "",
        "### 목차",
        *[f"{i + 1}. {c['title']}" for i, c in enumerate(spec["chapters"])],
        "",
        "### 구성",
        f"- PDF 전자책 약 {spec.get('pages', '')}쪽 (스마트폰 가독성 판형)",
        "- 장마다 바로 따라 하는 실천 체크리스트",
        "",
        "상세페이지 이미지: detail_1_toc.png, detail_2_for_whom.png",
    ]
    if platform == "kmong":
        lines += ["", "### 크몽 FAQ 예시",
                  "Q. 어떤 형식인가요? A. PDF 파일로 제공됩니다.",
                  "Q. 초보도 따라 할 수 있나요? A. 단계별 체크리스트로 구성했습니다.",
                  "", "※ 크몽 전자책은 등록 후 크몽 검수를 거쳐 판매가 시작됩니다."]
    else:
        lines += ["", "※ 래피드는 'PDF 자동 판매'를 켜면 결제 즉시 구매자에게 파일이 전송됩니다. ebook.pdf 를 그대로 올리세요."]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ 실행

def build(spec_path):
    _load_render_libs()
    spec = load_spec(spec_path)
    out = os.path.dirname(os.path.abspath(spec_path))
    slug = os.path.basename(out)
    book = to_book(spec)
    palette = book["design"]["palette"]
    files = {}
    with design.use_font(book["design"]["font"]):
        cover = design.render_cover(spec["title"], spec["subtitle"], spec.get("author", ""), book["design"]["style"], palette)
        files["cover.png"] = design.png_bytes(cover)
        files["mockup_3d.png"] = design.png_bytes(design.render_mockup(cover))
        files["thumb_4x3.png"] = design.png_bytes(thumbnail(cover, (1304, 976), palette, spec.get("badge", ""), spec["title"], spec["subtitle"]))
        files["thumb_1x1.png"] = design.png_bytes(thumbnail(cover, (1080, 1080), palette, spec.get("badge", "")))
        files["detail_1_toc.png"] = design.png_bytes(detail_image("이 책의 목차", [c["title"] for c in spec["chapters"]], palette))
        files["detail_2_for_whom.png"] = design.png_bytes(detail_image("이런 분께 추천해요", spec["sales"]["for_whom"], palette, numbered=False))
        pdf = design.build_pdf(book, cover, "comfort", design.PALETTES[palette]["ink"])
    files["ebook.pdf"] = pdf
    spec["pages"] = _pdf_pages(pdf) - 2  # 표지·목차를 뺀 본문 쪽수를 판매 문구에 쓴다
    files["manuscript.md"] = design.manuscript_markdown(book).encode("utf-8")
    files["groble.json"] = json.dumps(groble_payload(spec, slug), ensure_ascii=False, indent=2).encode("utf-8")
    files["kmong.md"] = market_text(spec, "kmong").encode("utf-8")
    files["latpeed.md"] = market_text(spec, "latpeed").encode("utf-8")

    for name, data in files.items():
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            if name != "groble.json":
                z.writestr(f"{slug}/{name}", data)
    with open(os.path.join(out, "upload_package.zip"), "wb") as f:
        f.write(buf.getvalue())

    pages = _pdf_pages(pdf)
    print(json.dumps({"dir": out, "pdf_pages": pages, "pdf_kb": len(pdf) // 1024,
                      "files": sorted(list(files) + ["upload_package.zip"])}, ensure_ascii=False, indent=2))
    return out


def _pdf_pages(pdf):
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def next_topic():
    with open(QUEUE_PATH, encoding="utf-8") as f:
        q = json.load(f)
    for t in q["topics"]:
        if t.get("status") != "done":
            return t
    return None


def mark_done(topic_id, folder, groble_product_id=""):
    with open(QUEUE_PATH, encoding="utf-8") as f:
        q = json.load(f)
    for t in q["topics"]:
        if t["id"] == topic_id:
            t.update({"status": "done", "date": date.today().isoformat(), "folder": folder, "groble_product_id": groble_product_id})
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ 내 컴퓨터 폴더로 내보내기

UNSAFE = re.compile(r'[\\/:*?"<>|\n\r\t]')


def safe_name(text, limit=60):
    """윈도우·맥에서 폴더/파일 이름으로 쓸 수 있게 다듬는다."""
    name = UNSAFE.sub(" ", text).strip().rstrip(".")
    return re.sub(r"\s+", " ", name)[:limit] or "전자책"


EXPORT_FILES = [  # (원본, 내보낼 이름 — {t}는 제목)
    ("ebook.pdf", "{t}.pdf"),
    ("thumb_4x3.png", "썸네일_가로4x3.png"),
    ("thumb_1x1.png", "썸네일_정사각1x1.png"),
    ("cover.png", "표지.png"),
    ("mockup_3d.png", "3D목업.png"),
    ("detail_1_toc.png", "상세이미지1_목차.png"),
    ("detail_2_for_whom.png", "상세이미지2_추천대상.png"),
    ("kmong.md", "크몽_등록문구.txt"),
    ("latpeed.md", "래피드_등록문구.txt"),
    ("manuscript.md", "원고_수정용.md"),
]


def export(dest):
    """daily/ 의 완성된 책을 dest/<날짜>_<제목>/ 으로 복사한다. 이미 있는 폴더는 건너뛴다."""
    import shutil
    os.makedirs(dest, exist_ok=True)
    made = []
    for folder in sorted(os.listdir(DAILY_DIR)):
        src = os.path.join(DAILY_DIR, folder)
        spec_path = os.path.join(src, "spec.json")
        if not (os.path.isdir(src) and os.path.exists(spec_path) and os.path.exists(os.path.join(src, "ebook.pdf"))):
            continue
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        title = safe_name(spec["title"])
        out = os.path.join(dest, f"{folder[:10]}_{title}")
        if os.path.exists(out):
            continue
        os.makedirs(out)
        for src_name, dst_name in EXPORT_FILES:
            if os.path.exists(os.path.join(src, src_name)):
                shutil.copy2(os.path.join(src, src_name), os.path.join(out, dst_name.format(t=title)))
        groble_id = ""
        if os.path.exists(QUEUE_PATH):
            with open(QUEUE_PATH, encoding="utf-8") as f:
                for t in json.load(f)["topics"]:
                    if t.get("folder", "").endswith(folder):
                        groble_id = t.get("groble_product_id", "")
        info = [
            f"제목: {spec['title']}",
            f"부제: {spec['subtitle']}",
            f"가격: {int(spec['price']):,}원",
            f"검색 태그: {', '.join(spec.get('keywords', []))}",
            f"대상 독자: {spec['target']}",
            "",
            "목차:",
            *[f"  {i + 1}. {c['title']}" for i, c in enumerate(spec["chapters"])],
            "",
            f"그로블: https://groble.im/products/{groble_id}" if groble_id else "그로블: (아직 올리지 않음)",
            "크몽: 크몽_등록문구.txt 를 복사해 붙여 넣고 썸네일_가로4x3.png, PDF 를 올리세요.",
            "래피드: 래피드_등록문구.txt 를 복사해 붙여 넣고 썸네일, PDF 를 올리세요 (PDF 자동 판매 켜기).",
            "",
            "업로드 체크:  [ ] 크몽   [ ] 래피드",
        ]
        with open(os.path.join(out, "00_제목과_등록정보.txt"), "w", encoding="utf-8-sig") as f:
            f.write("\n".join(info) + "\n")
        made.append(out)
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description="매일 전자책 1권 제작")
    ap.add_argument("spec", nargs="?", help="spec.json 경로")
    ap.add_argument("--next", action="store_true", help="다음 주제 출력")
    ap.add_argument("--done", nargs="+", metavar=("TOPIC_ID", "FOLDER"), help="주제를 완료로 표시: TOPIC_ID FOLDER [GROBLE_ID]")
    ap.add_argument("--export", metavar="폴더", help="완성된 책을 이 폴더 아래 <날짜>_<제목>/ 으로 복사")
    a = ap.parse_args(argv)
    if a.export:
        made = export(a.export)
        print(f"새로 만든 폴더 {len(made)}개")
        for m in made:
            print(" -", m)
    elif a.next:
        print(json.dumps(next_topic(), ensure_ascii=False, indent=2))
    elif a.done:
        mark_done(*a.done[:3])
        print("완료로 표시했습니다.")
    elif a.spec:
        build(a.spec)
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
