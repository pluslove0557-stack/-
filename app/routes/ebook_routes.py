import json
import os
import re
import shutil
import time
import uuid

from flask import (Blueprint, abort, current_app, jsonify, redirect, render_template, request, Response, send_file, url_for)

from app import ebook_ai as ai
from app import ebook_design as design

ebook_bp = Blueprint("ebook", __name__)
ID_RE = re.compile(r"^[a-f0-9]{12}$")
STEP_COUNT = 11

DEFAULTS = {
    "pages": 30, "length": "light", "tone": "manual", "research_level": "medium", "topics": [], "topic": None,
    "validation": None, "research": "", "toc": None, "chapters": {}, "my_story": "", "voice_sample": "",
    "price": "15000", "buy_url": "", "copy": None, "ladder": None, "cards": None, "plan": None, "adapt": None, "stats": [],
}
DESIGN_DEFAULTS = {"palette": "midnight", "style": None, "body": "comfort", "font": None, "card_style": "note"}
PROFILE_DEFAULTS = {"persona": "", "experience": "", "interest": "", "author_name": "", "category": "", "subcategory": "",
                    "level": "beginner", "situation": ""}


# ------------------------------------------------------------------ 저장소

def _root():
    d = current_app.config["EBOOK_DIR"]
    os.makedirs(d, exist_ok=True)
    return d


def _dir(bid):
    if not ID_RE.match(bid):
        abort(404)
    d = os.path.join(_root(), bid)
    if not os.path.isdir(d):
        abort(404)
    return d


def load(bid):
    with open(os.path.join(_dir(bid), "book.json"), encoding="utf-8") as f:
        book = json.load(f)
    for k, v in DEFAULTS.items():  # 이전 버전에서 만든 프로젝트도 열리도록 기본값 채우기
        book.setdefault(k, json.loads(json.dumps(v)))
    book.setdefault("design", {})
    book.setdefault("profile", {})
    for k, v in DESIGN_DEFAULTS.items():
        book["design"].setdefault(k, v)
    for k, v in PROFILE_DEFAULTS.items():
        book["profile"].setdefault(k, v)
    return book


def save(book):
    book["updated"] = time.time()
    path = os.path.join(_dir(book["id"]), "book.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _err(msg, code=400):
    return jsonify({"error": msg}), code


def _ai_guard(fn):
    try:
        return fn()
    except ai.AIError as e:
        return _err(str(e), 502)


def _font(book):
    return design.use_font(book["design"].get("font"))


def _palette(book):
    return design.PALETTES.get(book["design"].get("palette"), design.PALETTES["midnight"])


def _progress(b):
    n = len(b["toc"]["chapters"]) if b.get("toc") else 0
    steps = [bool(b.get("topic")), bool(b.get("validation")), bool(b.get("research")), bool(b.get("toc")),
             n > 0 and all(b["chapters"].get(str(i)) for i in range(n)), bool(b.get("polished")),
             bool(b.get("design", {}).get("style")), bool(b.get("pdf_built")), bool(b.get("copy")),
             bool(b.get("copy")), bool(b.get("ladder") or b.get("cards") or b.get("plan"))]
    return sum(steps)


# ------------------------------------------------------------------ 페이지

@ebook_bp.route("/")
def index():
    books = []
    for bid in os.listdir(_root()):
        if ID_RE.match(bid) and os.path.exists(os.path.join(_root(), bid, "book.json")):
            b = load(bid)
            books.append({"id": bid, "title": (b.get("toc") or {}).get("title") or (b.get("topic") or {}).get("title") or b.get("name"),
                          "updated": b.get("updated", 0), "progress": _progress(b)})
    books.sort(key=lambda b: -b["updated"])
    return render_template("ebook_list.html", books=books, mode=ai.mode_label(), ai_on=ai.ai_available(),
                           categories=ai.CATEGORIES, levels=ai.LEVELS, steps=STEP_COUNT)


@ebook_bp.route("/new", methods=["POST"])
def new():
    bid = uuid.uuid4().hex[:12]
    os.makedirs(os.path.join(_root(), bid))
    book = json.loads(json.dumps(DEFAULTS))
    book.update({"id": bid, "created": time.time(), "name": request.form.get("name") or "새 전자책",
                 "profile": {k: request.form.get(k, v) for k, v in PROFILE_DEFAULTS.items()},
                 "design": dict(DESIGN_DEFAULTS)})
    save(book)
    return redirect(url_for("ebook.studio", bid=bid))


@ebook_bp.route("/<bid>")
def studio(bid):
    return render_template("ebook_studio.html", book=load(bid), mode=ai.mode_label(), ai_on=ai.ai_available(),
                           palettes=design.PALETTES, styles=design.STYLES, fonts=design.available_fonts(),
                           categories=ai.CATEGORIES, levels=ai.LEVELS, tones=ai.TONES, lengths=ai.LENGTHS,
                           research_levels=ai.RESEARCH_LEVELS, channels=ai.CHANNELS, ad_angles=ai.AD_ANGLES)


@ebook_bp.route("/<bid>/data")
def data(bid):
    return jsonify(load(bid))


@ebook_bp.route("/<bid>/delete", methods=["POST"])
def delete(bid):
    shutil.rmtree(_dir(bid))
    return redirect(url_for("ebook.index"))


@ebook_bp.route("/<bid>/save", methods=["POST"])
def save_fields(bid):
    book = load(bid)
    d = request.get_json(silent=True) or {}
    for k in ("research", "price", "buy_url", "tone", "research_level", "my_story", "voice_sample"):
        if k in d:
            book[k] = str(d[k])
    if d.get("length") in ai.LENGTHS:
        book["length"] = d["length"]
        book["pages"] = ai.LENGTHS[d["length"]][1]
    if "pages" in d:
        try:
            book["pages"] = max(5, min(200, int(d["pages"])))
        except (TypeError, ValueError):
            pass
    if "profile" in d:
        book["profile"].update({k: str(v) for k, v in d["profile"].items() if k in PROFILE_DEFAULTS})
    if isinstance(d.get("topic"), dict):
        book["topic"] = d["topic"]
    if isinstance(d.get("toc"), dict):
        book["toc"] = d["toc"]
    if "chapter" in d:
        key = d["chapter"]["index"]
        key = "prologue" if key == "prologue" else str(int(key))
        book["chapters"][key] = d["chapter"]["body"]
    if isinstance(d.get("design"), dict):
        book["design"].update({k: v for k, v in d["design"].items() if k in DESIGN_DEFAULTS})
    if isinstance(d.get("stats"), list):
        book["stats"] = d["stats"][:500]
    save(book)
    return jsonify({"ok": True, "progress": _progress(book)})


# ------------------------------------------------------------------ 1~6 글쓰기 단계

@ebook_bp.route("/<bid>/topics", methods=["POST"])
def topics(bid):
    book = load(bid)
    more = bool((request.get_json(silent=True) or {}).get("more"))

    def run():
        exclude = [t["title"] for t in book["topics"]] if more else []
        new_topics = ai.suggest_topics(book["profile"], exclude)
        book["topics"] = (book["topics"] + new_topics) if more else new_topics
        save(book)
        return jsonify({"topics": book["topics"]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/select_topic", methods=["POST"])
def select_topic(bid):
    book = load(bid)
    d = request.get_json(silent=True) or {}
    if (d.get("custom") or "").strip():
        t = d["custom"].strip()
        book["topic"] = {"title": t, "subtitle": d.get("subtitle", ""), "target": d.get("target", ""), "pain": d.get("pain", ""),
                         "why_sells": "", "differentiation": "", "keywords": [t], "score": 0}
    else:
        try:
            book["topic"] = book["topics"][int(d.get("index", -1))]
        except (ValueError, IndexError):
            return _err("주제를 선택하세요.")
    save(book)
    return jsonify({"topic": book["topic"]})


def _need_topic(book):
    return None if book.get("topic") else _err("먼저 1단계에서 주제를 선택하세요.")


def _need_toc(book):
    return None if book.get("toc") else _err("먼저 4단계에서 목차를 확정하세요.")


@ebook_bp.route("/<bid>/validate", methods=["POST"])
def validate(bid):
    book = load(bid)
    if (e := _need_topic(book)):
        return e

    def run():
        book["validation"] = ai.validate_topic(book["topic"])
        save(book)
        return jsonify(book["validation"])
    return _ai_guard(run)


@ebook_bp.route("/<bid>/research", methods=["POST"])
def research(bid):
    book = load(bid)
    if (e := _need_topic(book)):
        return e
    level = (request.get_json(silent=True) or {}).get("level") or book["research_level"]
    book["research_level"] = level if level in ai.RESEARCH_LEVELS else "medium"

    def run():
        notes = ai.research(book["topic"], book["research_level"])
        book["research"] = (book["research"] + "\n\n" + notes).strip() if book.get("research") else notes
        save(book)
        return jsonify({"research": book["research"]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/toc", methods=["POST"])
def toc(bid):
    book = load(bid)
    if (e := _need_topic(book)):
        return e
    d = request.get_json(silent=True) or {}
    if d.get("length") in ai.LENGTHS:
        book["length"], book["pages"] = d["length"], ai.LENGTHS[d["length"]][1]
    if d.get("tone") in ai.TONES:
        book["tone"] = d["tone"]

    def run():
        book["toc"] = ai.make_toc(book, d.get("revise", ""))
        save(book)
        return jsonify({"toc": book["toc"]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/prologue", methods=["POST"])
def prologue(bid):
    book = load(bid)
    if (e := _need_toc(book)):
        return e

    def run():
        book["chapters"]["prologue"] = ai.write_prologue(book)
        save(book)
        return jsonify({"index": "prologue", "body": book["chapters"]["prologue"]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/chapter/<int:idx>", methods=["POST"])
def chapter(bid, idx):
    book = load(bid)
    if (e := _need_toc(book)):
        return e
    if idx >= len(book["toc"]["chapters"]):
        return _err("없는 장입니다.")

    def run():
        book["chapters"][str(idx)] = ai.write_chapter(book, idx)
        save(book)
        return jsonify({"index": idx, "body": book["chapters"][str(idx)]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/humanize/<key>", methods=["POST"])
def humanize(bid, key):
    book = load(bid)
    if key != "prologue" and not key.isdigit():
        abort(404)
    body = book["chapters"].get(key)
    if not body:
        return _err("이 장의 원고가 아직 없습니다.")
    d = request.get_json(silent=True) or {}

    def run():
        book["chapters"][key] = ai.humanize(body, d.get("instructions", ""))
        if book.get("toc") and all(book["chapters"].get(str(i)) for i in range(len(book["toc"]["chapters"]))):
            book["polished"] = True
        save(book)
        return jsonify({"index": key, "body": book["chapters"][key]})
    return _ai_guard(run)


# ------------------------------------------------------------------ 7~8 디자인

def _cover(book, style=None):
    toc = book["toc"]
    style = style or book["design"].get("style") or "bold"
    author = book["profile"].get("author_name") or book["profile"].get("persona") or ""
    return design.render_cover(toc["title"], toc["subtitle"], author, style, book["design"].get("palette", "midnight"))


@ebook_bp.route("/<bid>/covers", methods=["POST"])
def covers(bid):
    book = load(bid)
    if (e := _need_toc(book)):
        return e
    d = request.get_json(silent=True) or {}
    if d.get("palette") in design.PALETTES:
        book["design"]["palette"] = d["palette"]
    if d.get("font") in design.available_fonts():
        book["design"]["font"] = d["font"]
    folder = _dir(bid)
    v = int(time.time())
    out = []
    with _font(book):
        for style in design.STYLES:
            img = _cover(book, style)
            img.thumbnail((600, 850))
            img.save(os.path.join(folder, f"cover_{style}.png"))
            out.append({"style": style, "name": design.STYLES[style], "url": url_for("ebook.img", bid=bid, name=f"cover_{style}.png", v=v)})
    save(book)
    return jsonify({"covers": out})


@ebook_bp.route("/<bid>/choose_cover", methods=["POST"])
def choose_cover(bid):
    book = load(bid)
    style = (request.get_json(silent=True) or {}).get("style")
    if style not in design.STYLES:
        return _err("표지 스타일을 선택하세요.")
    book["design"]["style"] = style
    folder = _dir(bid)
    with _font(book):
        cover = _cover(book, style)
    cover.save(os.path.join(folder, "cover.png"))
    design.render_mockup(cover).save(os.path.join(folder, "mockup.png"))
    save(book)
    v = int(time.time())
    return jsonify({"cover": url_for("ebook.img", bid=bid, name="cover.png", v=v), "mockup": url_for("ebook.img", bid=bid, name="mockup.png", v=v)})


@ebook_bp.route("/<bid>/img/<name>")
def img(bid, name):
    if not re.match(r"^[a-z0-9_]+\.png$", name):
        abort(404)
    path = os.path.join(_dir(bid), name)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="image/png", max_age=0)


def _pdf_bytes(book):
    if not book.get("toc"):
        raise ValueError("먼저 4단계에서 목차를 확정하세요.")
    missing = [i + 1 for i in range(len(book["toc"]["chapters"])) if not book["chapters"].get(str(i))]
    if missing:
        raise ValueError(f"원고가 없는 장이 있습니다: {', '.join(map(str, missing))}장")
    with _font(book):
        return design.build_pdf(book, _cover(book), book["design"].get("body", "comfort"), _palette(book)["ink"])


@ebook_bp.route("/<bid>/pdf")
def pdf(bid):
    book = load(bid)
    try:
        data = _pdf_bytes(book)
    except ValueError as e:
        return _err(str(e))
    book["pdf_built"] = True
    save(book)
    dl = request.args.get("download") == "1"
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f"{'attachment' if dl else 'inline'}; filename=ebook_{bid}.pdf"})


# ------------------------------------------------------------------ 9~10 판매/광고

@ebook_bp.route("/<bid>/marketing", methods=["POST"])
def marketing(bid):
    book = load(bid)
    if (e := _need_toc(book)):
        return e
    count = (request.get_json(silent=True) or {}).get("ad_count", 3)

    def run():
        book["copy"] = ai.marketing_copy(book, count)
        save(book)
        return jsonify({"copy": book["copy"]})
    return _ai_guard(run)


def _landing(book):
    with _font(book):
        cover_png = design.png_bytes(_cover(book).resize((600, 850)))
    return design.landing_html(book, book["copy"], cover_png, book.get("buy_url", ""), book.get("price", ""), _palette(book)["ink"])


@ebook_bp.route("/<bid>/landing")
def landing(bid):
    book = load(bid)
    if not book.get("copy"):
        return _err("먼저 판매 문구를 생성하세요.")
    headers = {"Content-Disposition": f"attachment; filename=landing_{bid}.html"} if request.args.get("download") == "1" else {}
    return Response(_landing(book), mimetype="text/html", headers=headers)


def _ad_png(book, n, size=(1080, 1080)):
    a = book["copy"]["ads"][n]
    with _font(book):
        return design.png_bytes(design.render_ad(_cover(book), a["hook"], a["headline"], book["design"].get("palette", "midnight"), size))


@ebook_bp.route("/<bid>/ad/<int:n>.png")
def ad(bid, n):
    book = load(bid)
    if not book.get("copy") or n >= len(book["copy"]["ads"]):
        abort(404)
    size = (1080, 1350) if request.args.get("ratio") == "4x5" else (1080, 1080)
    return Response(_ad_png(book, n, size), mimetype="image/png")


# ------------------------------------------------------------------ 11 수익화·콘텐츠

@ebook_bp.route("/<bid>/ladder", methods=["POST"])
def ladder(bid):
    book = load(bid)
    if (e := _need_toc(book)):
        return e

    def run():
        book["ladder"] = ai.product_ladder(book)
        save(book)
        return jsonify({"ladder": book["ladder"]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/cards", methods=["POST"])
def cards(bid):
    book = load(bid)
    if (e := _need_toc(book)):
        return e
    d = request.get_json(silent=True) or {}
    if d.get("style") in ("note", "clean"):
        book["design"]["card_style"] = d["style"]

    def run():
        book["cards"] = ai.card_news(book, d.get("angle", ""), d.get("source", ""))
        save(book)
        return jsonify({"cards": book["cards"]})
    return _ai_guard(run)


def _card_png(book, n):
    slides = book["cards"]["slides"]
    s = slides[n]
    with _font(book):
        return design.png_bytes(design.render_card(s["title"], s["body"], n + 1, len(slides),
                                                   book["design"].get("palette", "paper"), book["design"].get("card_style", "note")))


@ebook_bp.route("/<bid>/card/<int:n>.png")
def card_img(bid, n):
    book = load(bid)
    if not book.get("cards") or n >= len(book["cards"]["slides"]):
        abort(404)
    return Response(_card_png(book, n), mimetype="image/png")


@ebook_bp.route("/<bid>/plan", methods=["POST"])
def plan(bid):
    book = load(bid)
    if (e := _need_toc(book)):
        return e
    channel = (request.get_json(silent=True) or {}).get("channel", "instagram")

    def run():
        book["plan"] = ai.content_plan(book, channel if channel in ai.CHANNELS else "instagram")
        book["plan"]["channel"] = channel
        save(book)
        return jsonify({"plan": book["plan"]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/adapt", methods=["POST"])
def adapt(bid):
    book = load(bid)
    d = request.get_json(silent=True) or {}
    script = (d.get("script") or "").strip()
    if not script:
        return _err("해외 게시물/영상의 스크립트(자막)를 붙여 넣으세요.")

    def run():
        book["adapt"] = ai.adapt_foreign(book, script, d.get("note", ""))
        save(book)
        return jsonify({"adapt": book["adapt"]})
    return _ai_guard(run)


# ------------------------------------------------------------------ 최종 결과물

@ebook_bp.route("/<bid>/bundle.zip")
def bundle(bid):
    book = load(bid)
    try:
        files = {"ebook.pdf": _pdf_bytes(book)}
    except ValueError as e:
        return _err(str(e))
    with _font(book):
        cover = _cover(book)
        mock = design.render_mockup(cover)
    files["manuscript.md"] = design.manuscript_markdown(book).encode("utf-8")
    files["cover.png"] = design.png_bytes(cover)
    files["mockup_3d.png"] = design.png_bytes(mock)
    if book.get("copy"):
        files["landing.html"] = _landing(book).encode("utf-8")
        lines = []
        for i, a in enumerate(book["copy"]["ads"]):
            files[f"ads/ad_{i + 1}_1x1.png"] = _ad_png(book, i)
            files[f"ads/ad_{i + 1}_4x5.png"] = _ad_png(book, i, (1080, 1350))
            lines += [f"## 광고 {i + 1} ({a['angle']})", f"후킹: {a['hook']}", f"본문:\n{a['primary_text']}", f"헤드라인: {a['headline']}", f"CTA: {a['cta']}", ""]
        files["ads/ad_copy.md"] = "\n".join(lines).encode("utf-8")
    if book.get("cards"):
        for i in range(len(book["cards"]["slides"])):
            files[f"cardnews/card_{i + 1}.png"] = _card_png(book, i)
        c = book["cards"]
        files["cardnews/caption.txt"] = (c["caption"] + "\n\n" + " ".join(c["hashtags"])).encode("utf-8")
    if book.get("ladder"):
        lines = ["# 계단형 상품 구조", ""]
        for t in book["ladder"]["tiers"]:
            lines += [f"## {t['stage']}: {t['name']}", f"- 형식: {t['format']}", f"- 가격: {t['price']}", f"- 구성: {t['contents']}",
                      f"- 목적: {t['goal']}", f"- 다음 단계로: {t['next_step']}", ""]
        lines.append(book["ladder"]["funnel_tip"])
        files["marketing/product_ladder.md"] = "\n".join(lines).encode("utf-8")
    if book.get("plan"):
        lines = [f"# {len(book['plan']['days'])}일 콘텐츠 플랜", "", book["plan"]["strategy"], "", "| 일 | 형식 | 후킹 | 내용 | CTA |", "|---|---|---|---|---|"]
        lines += [f"| {x['day']} | {x['format']} | {x['hook']} | {x['outline']} | {x['cta']} |" for x in book["plan"]["days"]]
        files["marketing/content_plan.md"] = "\n".join(lines).encode("utf-8")
    data = design.bundle_zip(book, files)
    return Response(data, mimetype="application/zip", headers={"Content-Disposition": f"attachment; filename=ebook_{bid}.zip"})
