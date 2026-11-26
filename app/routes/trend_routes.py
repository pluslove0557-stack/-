"""수요 먼저 → 자체 브랜드 (/trend)."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import store, trend_sourcing as ts
from app.us_sourcing import to_float

trend_bp = Blueprint("trend", __name__)

PL_FIELDS = [
    ("unit_cost", "공장 단가", "number"), ("currency", "통화(USD/CNY)", "text"),
    ("fx_usd", "원/달러", "number"), ("fx_cny", "원/위안", "number"),
    ("moq", "최소 주문 수량(MOQ)", "number"), ("freight_per_unit", "국제 운송비(개당, 원)", "number"),
    ("duty_pct", "관세율(%)", "number"), ("packaging", "포장·라벨(개당, 원)", "number"),
    ("fixed_cost", "1회성 비용(샘플·로고·촬영, 원)", "number"), ("sale_price", "판매가(원)", "number"),
    ("channel_fee_pct", "마켓 수수료(%)", "number"), ("ad_per_sale", "판매 1건당 광고비(원)", "number"),
    ("return_pct", "반품·불량률(%)", "number"), ("shipping_per_order", "국내 택배비(판매자 부담, 원)", "number"),
]


@trend_bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        niche = request.form.get("niche", "").strip()
        if not niche:
            flash("니치(분야) 이름을 넣어주세요.", "error")
            return redirect(url_for("trend.index"))
        nid = store.add_niche({"niche": niche, "keyword_en": request.form.get("keyword_en", "").strip()})
        return redirect(url_for("trend.niche", nid=nid))
    niches = store.list_niches()
    for n in niches:
        n["profit"] = ts.private_label(n["pl"])["profit_krw"] if n.get("pl") else None
    return render_template("trend/index.html", niches=niches)


@trend_bp.route("/<int:nid>")
def niche(nid):
    n = store.get_niche(nid)
    if not n:
        flash("찾을 수 없습니다.", "error")
        return redirect(url_for("trend.index"))
    kw = n.get("keyword_en") or n["niche"]
    transcripts = ts.split_transcripts(n.get("transcripts", ""))
    pl = ts.private_label(n.get("pl"))
    product_en = n.get("product_en", "")
    return render_template(
        "trend/niche.html", n=n, statuses=store.NICHE_STATUSES,
        links=ts.demand_links(kw),
        transcript_count=len(transcripts),
        t_prompt=ts.transcript_prompt(n["niche"], transcripts) if transcripts else "",
        pl=pl, pl_fields=PL_FIELDS,
        src_links=ts.sourcing_links(product_en, n.get("product_ko", "")),
        brands=ts.brand_ideas(product_en, n.get("feeling", "grip")) if product_en else [],
        feelings=list(ts._BRAND_WORDS.keys()),
        scripts=ts.shortform_scripts(n.get("product_ko") or product_en, n.get("problem"), n.get("solution"),
                                     n.get("target"), n.get("brand")),
        b_prompt=ts.brand_prompt(n["niche"], n.get("product_ko") or product_en, n.get("problem"), n.get("target")),
    )


@trend_bp.route("/<int:nid>/save", methods=["POST"])
def save(nid):
    n = store.get_niche(nid)
    if not n:
        return redirect(url_for("trend.index"))
    step = request.form.get("step")
    f = request.form
    if step == "demand":
        text = f.get("trend_csv", "").strip()
        if text:
            try:
                n["trend"] = ts.analyze_trend_text(text)
                flash(f"트렌드 {len(n['trend'])}개 키워드 분석 완료", "ok")
            except ValueError as e:
                flash(str(e), "error")
        n["keyword_en"] = f.get("keyword_en", n.get("keyword_en", "")).strip()
    elif step == "creators":
        n["transcripts"] = f.get("transcripts", "")
        parts = ts.split_transcripts(n["transcripts"])
        n["terms"] = ts.repeated_terms(parts)
        flash(f"자막 {len(parts)}개에서 반복 단어 {len(n['terms'])}개를 찾았습니다.", "ok")
    elif step == "product":
        for k in ("product_en", "product_ko", "problem", "solution", "target", "brand", "feeling"):
            n[k] = f.get(k, "").strip()
    elif step == "pl":
        pl = {}
        for key, _label, kind in PL_FIELDS:
            v = f.get(key)
            pl[key] = (v or "").strip().upper() if kind == "text" else to_float(v)
        n["pl"] = pl
    elif step == "status":
        store.update_niche(nid, status=f.get("status"))
        n["memo"] = f.get("memo", "")
    elif step == "delete":
        store.delete_niche(nid)
        flash("삭제했습니다.", "ok")
        return redirect(url_for("trend.index"))
    store.update_niche(nid, data=n)
    return redirect(url_for("trend.niche", nid=nid) + f"#{step}")
