import os
from flask import Flask


def _load_or_create_secret(base_dir):
    """SECRET_KEY 환경변수가 없으면 data/.secret_key 에 무작위 키를 만들어 재사용한다."""
    import secrets
    path = os.path.join(base_dir, "data", ".secret_key")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = secrets.token_hex(32)
    with open(path, "w") as f:
        f.write(key)
    return key


def create_app():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or _load_or_create_secret(base_dir)
    app.config["UPLOAD_DIR"] = os.path.join(base_dir, "data", "uploads")
    app.config["OUTPUT_DIR"] = os.path.join(base_dir, "data", "outputs")
    app.config["SAMPLE_DIR"] = os.path.join(base_dir, "data", "sample")
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB
    app.config["DB_PATH"] = os.environ.get("DB_PATH", os.path.join(base_dir, "data", "sourcing.db"))
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30  # 로그인 30일 유지

    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    os.makedirs(app.config["OUTPUT_DIR"], exist_ok=True)

    from app.routes.home_routes import home_bp
    from app.routes.margin_routes import margin_bp
    from app.routes.image_routes import image_bp
    from app.routes.listing_routes import listing_bp
    from app.routes.sourcing_routes import sourcing_bp
    from app.routes.prompts_routes import prompts_bp
    from app.routes.us_routes import us_bp
    from app.routes.pwa_routes import pwa_bp
    from app.auth import auth_bp, require_login
    from app import store

    app.register_blueprint(home_bp)
    app.register_blueprint(margin_bp, url_prefix="/margin")
    app.register_blueprint(image_bp, url_prefix="/image")
    app.register_blueprint(listing_bp, url_prefix="/listing")
    app.register_blueprint(sourcing_bp, url_prefix="/sourcing")
    app.register_blueprint(prompts_bp, url_prefix="/prompts")
    app.register_blueprint(us_bp, url_prefix="/us")
    app.register_blueprint(pwa_bp)
    app.register_blueprint(auth_bp)

    app.before_request(require_login)
    app.teardown_appcontext(store.close_db)

    return app
