from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, or_

from ..extensions import db
from ..models import User

bp = Blueprint("auth", __name__)


def _safe_next(target):
    if not target:
        return None
    parsed = urlparse(target)
    return target if not parsed.netloc and not parsed.scheme and target.startswith("/") else None


@bp.before_app_request
def force_password_change():
    if (current_user.is_authenticated and current_user.must_change_password
            and request.endpoint not in ("auth.change_password", "auth.logout", "static")):
        return redirect(url_for("auth.change_password"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        ident = (request.form.get("username") or "").strip().lower()
        pwd = request.form.get("password") or ""
        user = User.query.filter(or_(func.lower(User.username) == ident, func.lower(User.email) == ident)).first()
        now = datetime.now()
        if user and user.locked_until and user.locked_until > now:
            mins = int((user.locked_until - now).total_seconds() // 60) + 1
            flash(f"Tài khoản tạm khóa do đăng nhập sai nhiều lần. Thử lại sau {mins} phút.", "danger")
            return render_template("login.html"), 429
        if user and user.is_active and user.check_password(pwd):
            user.failed_logins = 0
            user.locked_until = None
            user.last_login_at = now
            db.session.commit()
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(_safe_next(request.args.get("next")) or url_for("main.dashboard"))
        if user:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= current_app.config["LOGIN_MAX_FAILS"]:
                user.locked_until = now + timedelta(minutes=current_app.config["LOGIN_LOCK_MINUTES"])
                user.failed_logins = 0
            db.session.commit()
        flash("Tên đăng nhập hoặc mật khẩu không đúng.", "danger")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        if not current_user.check_password(old):
            flash("Mật khẩu hiện tại không đúng.", "danger")
        elif len(new) < 8:
            flash("Mật khẩu mới phải có ít nhất 8 ký tự.", "danger")
        elif new != confirm:
            flash("Xác nhận mật khẩu không khớp.", "danger")
        elif new == old:
            flash("Mật khẩu mới phải khác mật khẩu cũ.", "danger")
        else:
            current_user.set_password(new)
            current_user.must_change_password = False
            db.session.commit()
            flash("Đã đổi mật khẩu.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("change_password.html")
