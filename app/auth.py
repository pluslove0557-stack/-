"""나만 쓰는 앱 - 비밀번호 1개로 잠그는 간단한 로그인.

잠금을 켜는 방법은 두 가지다.
- `python run.py --set-password` 로 비밀번호를 정한다(해시만 data/.app_password 에 저장).
- 환경변수 APP_PASSWORD 를 설정한다(서버에 올릴 때).
둘 다 없으면 잠금 없이 동작한다(이 PC에서만 열리는 기본 설정일 때).
"""

import hmac
import os

from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

_PW_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", ".app_password")

auth_bp = Blueprint("auth", __name__)

_OPEN_ENDPOINTS = {"auth.login", "static", "pwa.manifest", "pwa.service_worker"}


def _stored_hash():
    try:
        with open(_PW_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def save_password(password):
    os.makedirs(os.path.dirname(_PW_FILE), exist_ok=True)
    with open(_PW_FILE, "w", encoding="utf-8") as f:
        f.write(generate_password_hash(password))


def password_enabled():
    return bool(os.environ.get("APP_PASSWORD") or _stored_hash())


def _password_ok(pw):
    env = os.environ.get("APP_PASSWORD")
    if env:
        return hmac.compare_digest(pw.encode(), env.encode())
    stored = _stored_hash()
    return bool(stored) and check_password_hash(stored, pw)


def require_login():
    if not password_enabled():
        return None
    if request.endpoint in _OPEN_ENDPOINTS or session.get("authed"):
        return None
    return redirect(url_for("auth.login", next=request.path))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if _password_ok(pw):
            session["authed"] = True
            session.permanent = True
            nxt = request.args.get("next") or "/"
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/"
            return redirect(nxt)
        error = "비밀번호가 맞지 않습니다."
    return render_template("login.html", error=error)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
