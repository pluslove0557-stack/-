import io
from flask import Blueprint, render_template, request, jsonify, send_file

from app import margin

margin_bp = Blueprint("margin", __name__)


@margin_bp.route("/")
def index():
    return render_template("margin.html")


@margin_bp.route("/calculate", methods=["POST"])
def calculate():
    data = request.get_json(silent=True) or {}
    rows = data.get("rows", [])
    computed = margin.calc_rows(rows)
    total = round(sum(r["total_margin"] for r in computed), 2)
    return jsonify({"rows": computed, "total_margin": total})


@margin_bp.route("/export", methods=["POST"])
def export():
    data = request.get_json(silent=True) or {}
    rows = data.get("rows", [])
    wb = margin.build_workbook(rows)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="마진계산기.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
