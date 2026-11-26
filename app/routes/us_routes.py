"""미국 소싱 파이프라인 라우트 (/us)."""

import io

from flask import Blueprint, Response, flash, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook

from app import store, us_sourcing as us, us_text

us_bp = Blueprint("us", __name__)

EDITABLE_FIELDS = [
    ("title", "영문 상품명", "text"), ("url", "상품 URL", "text"), ("price_usd", "가격(USD)", "number"),
    ("brand", "브랜드", "text"), ("category", "카테고리", "text"), ("rating", "평점", "number"),
    ("reviews", "리뷰수", "number"), ("bsr", "BSR(판매순위)", "number"),
    ("ships_to_kr", "한국 배송 가능", "bool"), ("free_ship_kr", "한국 무료배송", "bool"),
    ("import_fee_included", "관부가세 예치금 포함가", "bool"), ("delivery_days", "배송 소요일", "number"),
    ("returns_30d", "30일 반품", "bool"), ("kr_competitors", "국내 판매자 수", "number"),
    ("kr_min_price", "국내 최저가(원)", "number"), ("cn_price_krw", "중국 동일제품 원가(원, 배송포함)", "number"),
    ("keyword", "소싱 키워드", "text"),
]


def _settings():
    s = store.get_settings({**us.DEFAULT_SETTINGS, "channel_fees": us.DEFAULT_CHANNEL_FEES})
    fees = s.pop("channel_fees")
    return s, fees


def _affinity_model():
    return us.build_affinity_model(store.sales_titles())


def _evaluated(status=None):
    s, fees = _settings()
    model = _affinity_model()
    out = []
    for c in store.list_candidates(status):
        ev = us.evaluate(c, s, fees, model)
        out.append({"item": c, "ev": ev})
    out.sort(key=lambda x: x["ev"]["score"], reverse=True)
    return out


@us_bp.route("/")
def dashboard():
    counts = {st: len(store.list_candidates(st)) for st in store.STATUSES}
    return render_template("us/dashboard.html", counts=counts, sales_count=len(store.sales_titles()))


# --- 1. 아이디어 → 키워드 ----------------------------------------------------
@us_bp.route("/ideas", methods=["GET", "POST"])
def ideas():
    idea = request.values.get("idea", "").strip()
    keywords = us_text.expand_idea(idea) if idea else []
    rows = [{"kw": k, "links": us_text.search_links(k)} for k in keywords]
    prompt = us_text.sourcing_prompt(keywords[0] if keywords else idea, store.sales_titles()) if idea else ""
    return render_template("us/ideas.html", idea=idea, rows=rows, prompt=prompt)


# --- 2. 후보 가져오기 --------------------------------------------------------
@us_bp.route("/import", methods=["GET", "POST"])
def import_items():
    if request.method == "POST":
        raw_rows = []
        f = request.files.get("file")
        pasted = request.form.get("pasted", "").strip()
        try:
            if f and f.filename:
                raw_rows = us.read_table(f.filename, f.read())
            elif pasted:
                pasted = pasted.strip().strip("`")
                if pasted.lower().startswith("csv"):
                    pasted = pasted[3:].lstrip()
                raw_rows = us.read_table("pasted.csv", pasted.encode("utf-8"))
            elif request.form.get("single_title"):
                raw_rows = [{
                    "title": request.form.get("single_title"), "url": request.form.get("single_url"),
                    "price_usd": request.form.get("single_price"), "brand": request.form.get("single_brand"),
                    "free_ship_kr": request.form.get("single_free") and "Y",
                    "ships_to_kr": "Y",
                }]
        except Exception as e:  # 파일 형식 오류를 화면에 보여준다
            flash(f"파일을 읽지 못했습니다: {e}", "error")
            return redirect(url_for("us.import_items"))

        items = [us.normalize_row(r) for r in raw_rows]
        valid = [i for i in items if i["title"] and i["price_usd"] is not None]
        bad = len(items) - len(valid)
        added, dup = store.add_candidates(valid)
        flash(f"{added}개 추가 · 중복 {dup}개 건너뜀 · 필수값(상품명/가격) 없음 {bad}개", "ok")
        return redirect(url_for("us.candidates"))
    return render_template("us/import.html", aliases=us.COLUMN_ALIASES)


@us_bp.route("/sample.csv")
def sample_csv():
    return Response(("﻿" + us.SAMPLE_CSV).encode("utf-8"), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=us_candidates_sample.csv"})


# --- 3. 후보 목록/평가 -------------------------------------------------------
@us_bp.route("/candidates")
def candidates():
    status = request.args.get("status") or None
    hide_blocked = request.args.get("hide_blocked") == "1"
    rows = _evaluated(status)
    if hide_blocked:
        rows = [r for r in rows if not r["ev"]["blocked"]]
    blocked_count = sum(1 for r in rows if r["ev"]["blocked"])
    return render_template("us/candidates.html", rows=rows, status=status, statuses=store.STATUSES,
                           hide_blocked=hide_blocked, blocked_count=blocked_count)


@us_bp.route("/bulk", methods=["POST"])
def bulk():
    ids = [int(x) for x in request.form.getlist("ids")]
    action = request.form.get("action")
    if not ids:
        flash("선택된 상품이 없습니다.", "error")
        return redirect(request.referrer or url_for("us.candidates"))
    if action == "delete":
        for i in ids:
            store.delete_candidate(i)
        flash(f"{len(ids)}개 삭제", "ok")
    elif action in store.STATUSES:
        for i in ids:
            store.update_candidate(i, status=action)
        flash(f"{len(ids)}개 → {action}", "ok")
    elif action == "prompt":
        items = [store.get_candidate(i) for i in ids]
        return render_template("us/prompt.html", prompt=us_text.rewrite_prompt([i for i in items if i]))
    elif action == "export":
        return _export([store.get_candidate(i) for i in ids])
    return redirect(request.referrer or url_for("us.candidates"))


@us_bp.route("/auto-exclude", methods=["POST"])
def auto_exclude():
    n = 0
    for r in _evaluated("후보"):
        if r["ev"]["blocked"]:
            store.update_candidate(r["item"]["id"], status="제외")
            n += 1
    flash(f"판매 불가 규칙에 걸린 {n}개를 '제외'로 옮겼습니다.", "ok")
    return redirect(url_for("us.candidates"))


# --- 4. 상품 상세 (원가/가격/상품명/태그/상세페이지) ------------------------
def _parse_form_item(form, base):
    item = dict(base)
    for key, _label, kind in EDITABLE_FIELDS:
        v = form.get(key)
        if kind == "number":
            item[key] = us.to_float(v)
        elif kind == "bool":
            item[key] = True if v == "Y" else (False if v == "N" else None)
        else:
            item[key] = (v or "").strip()
    item["asin"] = us.extract_asin(item.get("url")) or item.get("asin", "")
    for k in ("title_ko", "tags_ko"):
        if form.get(k) is not None:
            item[k] = form.get(k).strip()
    return item


@us_bp.route("/item/<int:cid>", methods=["GET", "POST"])
def item(cid):
    c = store.get_candidate(cid)
    if not c:
        flash("상품을 찾을 수 없습니다.", "error")
        return redirect(url_for("us.candidates"))
    if request.method == "POST":
        updated = _parse_form_item(request.form, c)
        store.update_candidate(cid, data=updated, status=request.form.get("status"), memo=request.form.get("memo", ""))
        flash("저장했습니다.", "ok")
        return redirect(url_for("us.item", cid=cid))

    s, fees = _settings()
    ev = us.evaluate(c, s, fees, _affinity_model())
    title_ko = c.get("title_ko") or us_text.korean_title(c)
    tags = c.get("tags_ko") or ", ".join(us_text.make_tags(c))
    detail = us_text.detail_page_html(c, ev, title_ko)
    return render_template("us/item.html", c=c, ev=ev, fields=EDITABLE_FIELDS, statuses=store.STATUSES,
                           title_ko=title_ko, tags=tags, detail=detail, settings=s,
                           links=us_text.search_links(c.get("title", "")[:80]))


# --- 5. 내보내기 -------------------------------------------------------------
EXPORT_COLUMNS = ["ASIN", "원문URL", "한국어상품명", "태그", "브랜드", "카테고리", "원가합계(원)", "가격(USD)",
                  "쿠팡 판매가", "네이버 판매가", "G마켓 판매가", "옥션 판매가", "11번가 판매가", "롯데온 판매가",
                  "국내최저가", "점수", "주의사항", "상세페이지HTML"]


def _export(items):
    s, fees = _settings()
    model = _affinity_model()
    wb = Workbook()
    ws = wb.active
    ws.title = "등록용"
    ws.append(EXPORT_COLUMNS)
    for c in items:
        if not c:
            continue
        ev = us.evaluate(c, s, fees, model)
        price = {p["key"]: p["recommended_price"] for p in ev["pricing"]}
        title_ko = c.get("title_ko") or us_text.korean_title(c)
        tags = c.get("tags_ko") or ", ".join(us_text.make_tags(c))
        ws.append([
            c.get("asin"), c.get("url"), title_ko, tags, c.get("brand"), c.get("category"),
            ev["cost"]["total_krw"], c.get("price_usd"),
            price.get("coupang"), price.get("naver"), price.get("gmarket"), price.get("auction"),
            price.get("st11"), price.get("lotteon"), c.get("kr_min_price"), ev["score"],
            " / ".join(f["label"] for f in ev["flags"]),
            us_text.detail_page_html(c, ev, title_ko),
        ])
    for col in "ABCDEFGHIJKLMNOPQR":
        ws.column_dimensions[col].width = 18
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="미국소싱_등록용.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@us_bp.route("/export")
def export_selected_status():
    status = request.args.get("status", "선정")
    return _export(store.list_candidates(status))


# --- 6. 내 판매이력 (유사도 학습) --------------------------------------------
@us_bp.route("/sales", methods=["GET", "POST"])
def sales():
    if request.method == "POST":
        if request.form.get("action") == "clear":
            store.clear_sales()
            flash("판매이력을 비웠습니다.", "ok")
            return redirect(url_for("us.sales"))
        titles = []
        f = request.files.get("file")
        if f and f.filename:
            for r in us.read_table(f.filename, f.read()):
                titles.append(us.normalize_row(r)["title"] or next(iter(r.values()), ""))
        titles += [ln for ln in request.form.get("pasted", "").splitlines() if ln.strip()]
        n = store.add_sales(titles)
        flash(f"판매이력 {n}건 추가", "ok")
        return redirect(url_for("us.sales"))
    titles = store.sales_titles()
    model = us.build_affinity_model(titles)
    top = sorted(model.items(), key=lambda x: x[1], reverse=True)[:30]
    return render_template("us/sales.html", titles=titles, top=top, sample=us.SALES_SAMPLE_CSV)


# --- 7. 설정 -----------------------------------------------------------------
@us_bp.route("/settings", methods=["GET", "POST"])
def settings():
    s, fees = _settings()
    if request.method == "POST":
        new = {k: us.to_float(request.form.get(k), v) for k, v in us.DEFAULT_SETTINGS.items()}
        new_fees = {}
        for key, ch in fees.items():
            new_fees[key] = {"label": ch["label"], "fee_pct": us.to_float(request.form.get(f"fee_{key}"), ch["fee_pct"])}
        store.save_settings({**new, "channel_fees": new_fees})
        flash("설정을 저장했습니다.", "ok")
        return redirect(url_for("us.settings"))
    return render_template("us/settings.html", s=s, fees=fees)


# --- 8. 롱테일 플래너 --------------------------------------------------------
@us_bp.route("/longtail")
def longtail():
    v = request.args
    target = us.to_float(v.get("target"), 30)
    st = us.to_float(v.get("sell_through"), 5)
    price = us.to_float(v.get("price"), 50000)
    margin = us.to_float(v.get("margin"), 30)
    plan = us.longtail_plan(target, st, price, margin)
    return render_template("us/longtail.html", plan=plan, target=target, st=st, price=price, margin=margin)


# --- 9. 주문 처리 도우미 -----------------------------------------------------
@us_bp.route("/order", methods=["GET", "POST"])
def order():
    result, code_ok, code = None, None, ""
    form = request.form
    if request.method == "POST":
        result = us_text.address_to_english(form.get("addr", ""), form.get("detail", ""), form.get("zip", ""))
        result["name"] = us_text.romanize_name(form.get("name", ""))
        result["phone"] = form.get("phone", "")
        if form.get("customs"):
            code_ok, code = us_text.validate_customs_code(form.get("customs"))
    return render_template("us/order.html", result=result, code_ok=code_ok, code=code, form=form)
