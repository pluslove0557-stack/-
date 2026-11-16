"""나만 쓰는 앱 - 비밀번호 1개로 잠그는 간단한 로그인.

환경변수 APP_PASSWORD 를 설정하면 모든 페이지에 로그인이 필요해진다.
설정하지 않으면(로컬 PC에서만 쓸 때) 잠금 없이 동작한다.
"""

import hmac
import os

from flask import Blueprint, redirect, render_template, request, session, url_for

auth_bp = Blueprint("auth", __name__)

_OPEN_ENDPOINTS = {"auth.login", "static", "pwa.manifest", "pwa.service_worker"}


def password_enabled():
    return bool(os.environ.get("APP_PASSWORD"))


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
        if hmac.compare_digest(pw, os.environ.get("APP_PASSWORD", "")):
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
