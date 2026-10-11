"""소유자 1명 전용 잠금.

- 최초 실행 시 이 컴퓨터(localhost)에서만 소유자 비밀번호를 설정할 수 있습니다.
- 이후 모든 페이지는 로그인한 소유자만 접근 가능합니다.
- 비밀번호는 해시로만 저장하고(data/owner.json), 세션 서명 키는 무작위로
  생성해 data/secret_key 에 보관합니다(둘 다 git 추적 안 함).
- 로그인 5회 실패 시 해당 IP를 10분간 잠급니다.
"""
import json
import os
import secrets
import time
from datetime import timedelta

from flask import (Blueprint, current_app, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint("auth", __name__)

MIN_PASSWORD_LEN = 8
MAX_FAILS = 5
LOCK_SECONDS = 600
PUBLIC_ENDPOINTS = {"auth.login", "auth.setup", "static"}
LOCAL_ADDRS = {"127.0.0.1", "::1"}

_fails = {}  # ip -> (실패횟수, 잠금해제시각)


def _owner_path():
    return os.path.join(current_app.config["DB_DIR"], "owner.json")


def _write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def load_secret_key(data_dir):
    """세션 서명 키: 환경변수 > 파일 > 새로 생성."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(data_dir, "secret_key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
    key = secrets.token_hex(32)
    _write_private(path, key)
    return key


def owner_exists():
    return os.path.exists(_owner_path())


def _load_owner():
    with open(_owner_path(), encoding="utf-8") as f:
        return json.load(f)


def set_password(password):
    _write_private(_owner_path(), json.dumps({"password_hash": generate_password_hash(password)}))


def verify_password(password):
    return owner_exists() and check_password_hash(_load_owner()["password_hash"], password)


def _is_local():
    return request.remote_addr in LOCAL_ADDRS


def _locked_for():
    count, until = _fails.get(request.remote_addr, (0, 0))
    return max(0, int(until - time.time())) if count >= MAX_FAILS else 0


def _record_fail():
    ip = request.remote_addr
    count, until = _fails.get(ip, (0, 0))
    if until and until < time.time():
        count = 0
    count += 1
    _fails[ip] = (count, time.time() + LOCK_SECONDS if count >= MAX_FAILS else 0)


def _start_session():
    session.clear()
    session.permanent = True
    session["owner"] = True
    session["csrf"] = secrets.token_hex(16)


def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else url_for("home.index")


@auth_bp.before_app_request
def require_owner():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not owner_exists():
        return redirect(url_for("auth.setup"))
    if not session.get("owner"):
        if request.method == "GET":
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return {"error": "로그인이 필요합니다."}, 401
    # 상태를 바꾸는 요청은 같은 출처(Origin)에서 온 것만 허용 (CSRF 방어)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin") or request.headers.get("Referer", "")
        if origin and not origin.startswith(request.host_url.rstrip("/")):
            return {"error": "허용되지 않은 요청 출처입니다."}, 403
    return None


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    if owner_exists():
        return redirect(url_for("auth.login"))
    if not _is_local():
        return render_template("auth.html", mode="setup",
                               error="최초 설정은 이 앱을 실행한 컴퓨터에서만 할 수 있습니다."), 403
    error = None
    if request.method == "POST":
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        if len(pw) < MIN_PASSWORD_LEN:
            error = f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다."
        elif pw != pw2:
            error = "비밀번호 확인이 일치하지 않습니다."
        else:
            set_password(pw)
            _start_session()
            return redirect(url_for("home.index"))
    return render_template("auth.html", mode="setup", error=error)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if not owner_exists():
        return redirect(url_for("auth.setup"))
    error = None
    if request.method == "POST":
        wait = _locked_for()
        if wait:
            error = f"로그인 시도가 너무 많습니다. {wait // 60 + 1}분 후 다시 시도하세요."
        elif verify_password(request.form.get("password", "")):
            _fails.pop(request.remote_addr, None)
            _start_session()
            return redirect(_safe_next(request.args.get("next")))
        else:
            _record_fail()
            error = "비밀번호가 올바르지 않습니다."
    return render_template("auth.html", mode="login", error=error)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/password", methods=["GET", "POST"])
def change_password():
    error = done = None
    if request.method == "POST":
        cur, pw, pw2 = (request.form.get(k, "") for k in ("current", "password", "password2"))
        if not verify_password(cur):
            error = "현재 비밀번호가 올바르지 않습니다."
        elif len(pw) < MIN_PASSWORD_LEN:
            error = f"새 비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다."
        elif pw != pw2:
            error = "새 비밀번호 확인이 일치하지 않습니다."
        else:
            set_password(pw)
            _start_session()
            done = "비밀번호를 변경했습니다."
    return render_template("auth.html", mode="password", error=error, done=done)


def init_app(app):
    app.config["SECRET_KEY"] = load_secret_key(app.config["DB_DIR"])
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )
    app.register_blueprint(auth_bp)
