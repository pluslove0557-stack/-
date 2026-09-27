import os
from flask import Flask


def create_app():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-not-for-production")
    app.config["UPLOAD_DIR"] = os.path.join(base_dir, "data", "uploads")
    app.config["OUTPUT_DIR"] = os.path.join(base_dir, "data", "outputs")
    app.config["SAMPLE_DIR"] = os.path.join(base_dir, "data", "sample")
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB

    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    os.makedirs(app.config["OUTPUT_DIR"], exist_ok=True)

    from app.routes.home_routes import home_bp
    from app.routes.margin_routes import margin_bp
    from app.routes.image_routes import image_bp
    from app.routes.listing_routes import listing_bp
    from app.routes.sourcing_routes import sourcing_bp
    from app.routes.prompts_routes import prompts_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(margin_bp, url_prefix="/margin")
    app.register_blueprint(image_bp, url_prefix="/image")
    app.register_blueprint(listing_bp, url_prefix="/listing")
    app.register_blueprint(sourcing_bp, url_prefix="/sourcing")
    app.register_blueprint(prompts_bp, url_prefix="/prompts")

    return app
