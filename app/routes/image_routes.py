import io
import os
import zipfile
from flask import Blueprint, render_template, request, send_file, jsonify

from app import image_tool

image_bp = Blueprint("image", __name__)


@image_bp.route("/")
def index():
    return render_template(
        "image.html",
        ai_bg_available=image_tool.AI_BG_REMOVAL_AVAILABLE,
    )


def _bool(v):
    return str(v).lower() in ("1", "true", "on", "yes")


@image_bp.route("/process", methods=["POST"])
def process():
    files = request.files.getlist("images")
    if not files:
        return jsonify({"error": "이미지 파일을 선택해주세요."}), 400

    opts = {
        "remove_bg": _bool(request.form.get("remove_bg")),
        "bg_method": request.form.get("bg_method", "auto"),
        "bg_threshold": request.form.get("bg_threshold", 235),
        "bg_tolerance": request.form.get("bg_tolerance", 18),
        "pad_square": _bool(request.form.get("pad_square")),
        "resize": _bool(request.form.get("resize")),
        "size": request.form.get("size", 1000),
        "watermark_text": request.form.get("watermark_text", ""),
        "watermark_opacity": request.form.get("watermark_opacity", 110),
        "watermark_position": request.form.get("watermark_position", "bottom-right"),
    }
    out_format = request.form.get("format", "PNG")

    results = []
    for f in files:
        img, bg_method = image_tool.process_image(f.read(), opts)
        buf = image_tool.image_to_bytes(img, out_format)
        base_name = os.path.splitext(f.filename or "image")[0]
        ext = "jpg" if out_format.upper() in ("JPG", "JPEG") else "png"
        results.append((f"{base_name}_edited.{ext}", buf.getvalue(), bg_method))

    if len(results) == 1:
        name, data, _ = results[0]
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data, _ in results:
            zf.writestr(name, data)
    zip_buf.seek(0)
    return send_file(zip_buf, as_attachment=True, download_name="processed_images.zip")
