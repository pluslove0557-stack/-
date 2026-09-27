from flask import Blueprint, render_template, request, jsonify

from app import prompts

prompts_bp = Blueprint("prompts", __name__)


@prompts_bp.route("/")
def index():
    return render_template("prompts.html", options=prompts.options())


@prompts_bp.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    variants = prompts.generate_prompts(
        product_name=data.get("product_name", ""),
        bg_key=data.get("background", "white_studio"),
        light_key=data.get("lighting", "softbox"),
        angle_key=data.get("angle", "front"),
        tone_key=data.get("tone", "minimal"),
        count=int(data.get("count", 3)),
    )
    return jsonify({"variants": variants})
