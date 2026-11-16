import json
import os
import re
import time
import uuid

from flask import (Blueprint, abort, current_app, jsonify, redirect, render_template, request, Response, send_file, url_for)
from PIL import Image

from app import ebook_ai as ai
from app import ebook_design as design

ebook_bp = Blueprint("ebook", __name__)
ID_RE = re.compile(r"^[a-f0-9]{12}$")


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
        return json.load(f)


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


def _require(book, *keys):
    names = {"topic": "1단계 주제 선택", "toc": "4단계 목차"}
    for k in keys:
        if not book.get(k):
            raise ValueError(f"먼저 {names.get(k, k)}을(를) 완료하세요.")


# ------------------------------------------------------------------ 페이지

@ebook_bp.route("/")
def index():
    books = []
    for bid in sorted(os.listdir(_root())):
        p = os.path.join(_root(), bid, "book.json")
        if ID_RE.match(bid) and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                b = json.load(f)
            books.append({"id": bid, "title": (b.get("toc") or {}).get("title") or (b.get("topic") or {}).get("title") or b.get("name"),
                          "updated": b.get("updated", 0), "progress": _progress(b)})
    books.sort(key=lambda b: -b["updated"])
    return render_template("ebook_list.html", books=books, mode=ai.mode_label(), ai_on=ai.ai_available())


@ebook_bp.route("/new", methods=["POST"])
def new():
    bid = uuid.uuid4().hex[:12]
    os.makedirs(os.path.join(_root(), bid))
    book = {
        "id": bid, "created": time.time(), "name": request.form.get("name") or "새 전자책",
        "profile": {
            "persona": request.form.get("persona", ""), "experience": request.form.get("experience", ""),
            "interest": request.form.get("interest", ""), "author_name": request.form.get("author_name", ""),
        },
        "pages": 30, "topics": [], "topic": None, "validation": None, "research": "", "toc": None,
        "chapters": {}, "design": {"palette": "midnight", "style": None, "body": "comfort"},
        "price": "15000", "buy_url": "", "copy": None,
    }
    save(book)
    return redirect(url_for("ebook.studio", bid=bid))


@ebook_bp.route("/<bid>")
def studio(bid):
    return render_template("ebook_studio.html", book=load(bid), mode=ai.mode_label(), ai_on=ai.ai_available(),
                           palettes=design.PALETTES, styles=design.STYLES, font=design.font_status())


@ebook_bp.route("/<bid>/data")
def data(bid):
    return jsonify(load(bid))


@ebook_bp.route("/<bid>/delete", methods=["POST"])
def delete(bid):
    import shutil
    shutil.rmtree(_dir(bid))
    return redirect(url_for("ebook.index"))


def _progress(b):
    steps = [bool(b.get("topics")), bool(b.get("validation")), bool(b.get("research")), bool(b.get("toc")),
             bool(b.get("toc")) and len(b.get("chapters", {})) >= len(b["toc"]["chapters"]),
             bool(b.get("polished")), bool(b["design"].get("style")), bool(b.get("pdf_built")),
             bool(b.get("copy")), bool(b.get("copy"))]
    return sum(steps)


@ebook_bp.route("/<bid>/save", methods=["POST"])
def save_fields(bid):
    book = load(bid)
    d = request.get_json(silent=True) or {}
    for k in ("research", "price", "buy_url", "pages"):
        if k in d:
            book[k] = d[k]
    if "profile" in d:
        book["profile"].update({k: str(v) for k, v in d["profile"].items()})
    if "topic" in d and isinstance(d["topic"], dict):
        book["topic"] = d["topic"]
    if "toc" in d and isinstance(d["toc"], dict):
        book["toc"] = d["toc"]
    if "chapter" in d:
        book["chapters"][str(int(d["chapter"]["index"]))] = d["chapter"]["body"]
    if "design" in d:
        book["design"].update(d["design"])
    save(book)
    return jsonify({"ok": True, "progress": _progress(book)})


# ------------------------------------------------------------------ 1~6 글쓰기 단계

@ebook_bp.route("/<bid>/topics", methods=["POST"])
def topics(bid):
    book = load(bid)

    def run():
        book["topics"] = ai.suggest_topics(book["profile"])
        save(book)
        return jsonify({"topics": book["topics"]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/select_topic", methods=["POST"])
def select_topic(bid):
    book = load(bid)
    d = request.get_json(silent=True) or {}
    if "custom" in d and d["custom"].strip():
        t = d["custom"].strip()
        book["topic"] = {"title": t, "target": d.get("target", ""), "pain": d.get("pain", ""), "why_sells": "", "keywords": [t], "score": 0}
    else:
        try:
            book["topic"] = book["topics"][int(d.get("index", -1))]
        except (ValueError, IndexError):
            return _err("주제를 선택하세요.")
    save(book)
    return jsonify({"topic": book["topic"]})


@ebook_bp.route("/<bid>/validate", methods=["POST"])
def validate(bid):
    book = load(bid)
    if not book.get("topic"):
        return _err("먼저 1단계에서 주제를 선택하세요.")

    def run():
        book["validation"] = ai.validate_topic(book["topic"])
        save(book)
        return jsonify(book["validation"])
    return _ai_guard(run)


@ebook_bp.route("/<bid>/research", methods=["POST"])
def research(bid):
    book = load(bid)
    if not book.get("topic"):
        return _err("먼저 1단계에서 주제를 선택하세요.")

    def run():
        notes = ai.research(book["topic"])
        book["research"] = (book.get("research", "") + "\n\n" + notes).strip() if book.get("research") else notes
        save(book)
        return jsonify({"research": book["research"]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/toc", methods=["POST"])
def toc(bid):
    book = load(bid)
    if not book.get("topic"):
        return _err("먼저 1단계에서 주제를 선택하세요.")
    d = request.get_json(silent=True) or {}
    book["pages"] = int(d.get("pages") or book.get("pages") or 30)

    def run():
        book["toc"] = ai.make_toc(book["topic"], book.get("research", ""), book["pages"], d.get("revise", ""), book.get("toc"))
        save(book)
        return jsonify({"toc": book["toc"]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/chapter/<int:idx>", methods=["POST"])
def chapter(bid, idx):
    book = load(bid)
    if not book.get("toc") or idx >= len(book["toc"]["chapters"]):
        return _err("먼저 4단계에서 목차를 확정하세요.")
    d = request.get_json(silent=True) or {}

    def run():
        book["chapters"][str(idx)] = ai.write_chapter(book, idx, d.get("voice", ""))
        save(book)
        return jsonify({"index": idx, "body": book["chapters"][str(idx)]})
    return _ai_guard(run)


@ebook_bp.route("/<bid>/humanize/<int:idx>", methods=["POST"])
def humanize(bid, idx):
    book = load(bid)
    body = book["chapters"].get(str(idx))
    if not body:
        return _err("이 장의 원고가 아직 없습니다.")
    d = request.get_json(silent=True) or {}

    def run():
        book["chapters"][str(idx)] = ai.humanize(body, d.get("instructions", ""))
        if book.get("toc") and all(book["chapters"].get(str(i)) for i in range(len(book["toc"]["chapters"]))):
            book["polished"] = True
        save(book)
        return jsonify({"index": idx, "body": book["chapters"][str(idx)]})
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
    if not book.get("toc"):
        return _err("먼저 4단계에서 목차(제목)를 확정하세요.")
    d = request.get_json(silent=True) or {}
    if d.get("palette") in design.PALETTES:
        book["design"]["palette"] = d["palette"]
    folder = _dir(bid)
    v = int(time.time())
    out = []
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
    cover = _cover(book, style)
    folder = _dir(bid)
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
    _require(book, "toc")
    missing = [i + 1 for i in range(len(book["toc"]["chapters"])) if not book["chapters"].get(str(i))]
    if missing:
        raise ValueError(f"원고가 없는 장이 있습니다: {', '.join(map(str, missing))}장")
    accent = design.PALETTES[book["design"].get("palette", "midnight")]["ink"]
    return design.build_pdf(book, _cover(book), book["design"].get("body", "comfort"), accent)


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
    if not book.get("toc"):
        return _err("먼저 4단계에서 목차를 확정하세요.")

    def run():
        book["copy"] = ai.marketing_copy(book)
        save(book)
        return jsonify({"copy": book["copy"]})
    return _ai_guard(run)


def _landing(book):
    return design.landing_html(book, book["copy"], design.png_bytes(_cover(book).resize((600, 850))),
                               book.get("buy_url", ""), book.get("price", ""),
                               design.PALETTES[book["design"].get("palette", "midnight")]["ink"])


@ebook_bp.route("/<bid>/landing")
def landing(bid):
    book = load(bid)
    if not book.get("copy"):
        return _err("먼저 판매 문구를 생성하세요.")
    headers = {"Content-Disposition": f"attachment; filename=landing_{bid}.html"} if request.args.get("download") == "1" else {}
    return Response(_landing(book), mimetype="text/html", headers=headers)


@ebook_bp.route("/<bid>/ad/<int:n>.png")
def ad(bid, n):
    book = load(bid)
    if not book.get("copy") or n >= len(book["copy"]["ads"]):
        abort(404)
    a = book["copy"]["ads"][n]
    size = (1080, 1350) if request.args.get("ratio") == "4x5" else (1080, 1080)
    im = design.render_ad(_cover(book), a["hook"], a["headline"], book["design"].get("palette", "midnight"), size)
    return Response(design.png_bytes(im), mimetype="image/png")


@ebook_bp.route("/<bid>/bundle.zip")
def bundle(bid):
    book = load(bid)
    try:
        files = {"ebook.pdf": _pdf_bytes(book)}
    except ValueError as e:
        return _err(str(e))
    cover = _cover(book)
    files["manuscript.md"] = design.manuscript_markdown(book).encode("utf-8")
    files["cover.png"] = design.png_bytes(cover)
    files["mockup_3d.png"] = design.png_bytes(design.render_mockup(cover))
    if book.get("copy"):
        files["landing.html"] = _landing(book).encode("utf-8")
        pal = book["design"].get("palette", "midnight")
        lines = []
        for i, a in enumerate(book["copy"]["ads"]):
            files[f"ads/ad_{i + 1}_1x1.png"] = design.png_bytes(design.render_ad(cover, a["hook"], a["headline"], pal))
            files[f"ads/ad_{i + 1}_4x5.png"] = design.png_bytes(design.render_ad(cover, a["hook"], a["headline"], pal, (1080, 1350)))
            lines += [f"## 광고 {i + 1} ({a['angle']})", f"후킹: {a['hook']}", f"본문:\n{a['primary_text']}", f"헤드라인: {a['headline']}", f"CTA: {a['cta']}", ""]
        files["ads/ad_copy.md"] = "\n".join(lines).encode("utf-8")
    data = design.bundle_zip(book, files)
    return Response(data, mimetype="application/zip", headers={"Content-Disposition": f"attachment; filename=ebook_{bid}.zip"})
