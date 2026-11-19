from flask import Blueprint, redirect, render_template, url_for

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def root():
    return redirect(url_for("us.dashboard"))


@home_bp.route("/tools")
def index():
    return render_template("home.html")
