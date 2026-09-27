import io
from flask import Blueprint, render_template, request, jsonify, send_file, current_app

from app import sourcing

sourcing_bp = Blueprint("sourcing", __name__)


@sourcing_bp.route("/")
def index():
    return render_template("sourcing.html")


@sourcing_bp.route("/sample")
def sample():
    import os
    path = os.path.join(current_app.config["SAMPLE_DIR"], "wholesale_sample.csv")
    return send_file(path, as_attachment=True, download_name="wholesale_sample.csv")


@sourcing_bp.route("/analyze", methods=["POST"])
def analyze():
    file = request.files.get("candidates_file")
    if not file or not file.filename:
        return jsonify({"error": "도매 상품 후보 CSV 파일을 업로드해주세요."}), 400

    try:
        headers, rows = sourcing.parse_candidates_csv(file.read())
    except Exception as e:
        return jsonify({"error": f"파일을 읽는 중 오류가 발생했습니다: {e}"}), 400

    missing = [c for c in sourcing.REQUIRED_COLUMNS if c not in headers]
    if missing:
        return jsonify({"error": f"필수 컬럼이 없습니다: {', '.join(missing)}"}), 400

    scored = sourcing.score_candidates(rows)
    return jsonify({"rows": scored, "count": len(scored)})


@sourcing_bp.route("/export", methods=["POST"])
def export():
    data = request.get_json(silent=True) or {}
    rows = data.get("rows", [])
    csv_bytes = sourcing.to_csv_bytes(rows)
    return send_file(
        io.BytesIO(csv_bytes),
        as_attachment=True,
        download_name="소싱_스코어링_결과.csv",
        mimetype="text/csv",
    )
