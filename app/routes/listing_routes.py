import io
import uuid
from flask import Blueprint, render_template, request, jsonify, send_file

from app import listing

listing_bp = Blueprint("listing", __name__)

# 업로드된 소스 데이터를 잠깐 보관하는 메모리 캐시 (로컬 1인 사용 도구 기준).
_UPLOAD_CACHE = {}
_MAX_CACHE = 20


def _remember(headers, rows):
    upload_id = uuid.uuid4().hex[:12]
    if len(_UPLOAD_CACHE) >= _MAX_CACHE:
        _UPLOAD_CACHE.pop(next(iter(_UPLOAD_CACHE)))
    _UPLOAD_CACHE[upload_id] = {"headers": headers, "rows": rows}
    return upload_id


def _suggest_mapping(target_columns, source_headers):
    mapping = {}
    norm_source = {h.replace(" ", "").lower(): h for h in source_headers}
    for col in target_columns:
        key = col.replace(" ", "").lower()
        if key in norm_source:
            mapping[col] = norm_source[key]
            continue
        match = next((h for nh, h in norm_source.items() if key in nh or nh in key), None)
        mapping[col] = match or ""
    return mapping


@listing_bp.route("/")
def index():
    return render_template("listing.html", templates=listing.list_templates())


@listing_bp.route("/upload", methods=["POST"])
def upload():
    template_key = request.form.get("template", "generic")
    tpl = listing.get_template(template_key)
    if not tpl:
        return jsonify({"error": "알 수 없는 템플릿입니다."}), 400

    file = request.files.get("source_file")
    if not file or not file.filename:
        return jsonify({"error": "상품 데이터 파일(csv/xlsx)을 업로드해주세요."}), 400

    try:
        headers, rows = listing.read_source_table(file.filename, file.read())
    except Exception as e:
        return jsonify({"error": f"파일을 읽는 중 오류가 발생했습니다: {e}"}), 400

    if not rows:
        return jsonify({"error": "데이터 행이 없습니다."}), 400

    upload_id = _remember(headers, rows)
    suggested = _suggest_mapping(tpl["columns"], headers)

    return jsonify({
        "upload_id": upload_id,
        "source_headers": headers,
        "preview_rows": rows[:5],
        "row_count": len(rows),
        "target_columns": tpl["columns"],
        "template_label": tpl["label"],
        "template_notes": tpl["notes"],
        "suggested_mapping": suggested,
    })


@listing_bp.route("/export", methods=["POST"])
def export():
    data = request.get_json(silent=True) or {}
    upload_id = data.get("upload_id")
    template_key = data.get("template", "generic")
    mapping = data.get("mapping", {})

    cached = _UPLOAD_CACHE.get(upload_id)
    tpl = listing.get_template(template_key)
    if not cached or not tpl:
        return jsonify({"error": "업로드 정보가 만료되었습니다. 파일을 다시 업로드해주세요."}), 400

    out_rows = listing.apply_mapping(cached["rows"], tpl["columns"], mapping)
    wb = listing.build_output_workbook(tpl["columns"], out_rows, sheet_title=template_key)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{template_key}_상품등록양식.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
