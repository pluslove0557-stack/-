import os
from flask import Blueprint, render_template, request, jsonify, send_file, current_app
import io

from app import collector

collector_bp = Blueprint("collector", __name__)


def _db():
    return collector.connect(os.path.join(current_app.config["DB_DIR"], "collection.db"))


@collector_bp.route("/")
def index():
    return render_template("collector.html", platforms=collector.PLATFORM_LABEL,
                           categories=collector.CATEGORY_LABEL)


@collector_bp.route("/list")
def list_():
    conn = _db()
    rows = collector.list_videos(conn, request.args.get("platform", ""),
                                 request.args.get("category", ""), request.args.get("q", ""))
    return jsonify({"rows": rows})


@collector_bp.route("/add", methods=["POST"])
def add():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    if not collector.extract_urls(text):
        return jsonify({"error": "도우인/샤오홍슈 링크를 찾지 못했습니다. 앱의 '공유 > 링크 복사' 내용을 붙여넣어 주세요."}), 400
    added, dup, failed = collector.add_links(_db(), text, data.get("category"), data.get("fetch", True))
    return jsonify({"added": added, "duplicate": dup, "meta_failed": failed})


@collector_bp.route("/update/<int:vid>", methods=["POST"])
def update(vid):
    d = request.get_json(silent=True) or {}
    collector.update_video(_db(), vid, d.get("category"), d.get("tags"), d.get("note"))
    return jsonify({"ok": True})


@collector_bp.route("/delete/<int:vid>", methods=["POST"])
def delete(vid):
    collector.delete_video(_db(), vid)
    return jsonify({"ok": True})


@collector_bp.route("/export")
def export():
    rows = collector.list_videos(_db(), request.args.get("platform", ""),
                                 request.args.get("category", ""), request.args.get("q", ""))
    return send_file(io.BytesIO(collector.to_csv_bytes(rows)), as_attachment=True,
                     download_name="영상수집목록.csv", mimetype="text/csv")
