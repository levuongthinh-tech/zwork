import secrets
from collections import Counter
from datetime import date, timedelta

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import permissions as perm
from ..extensions import db
from ..models import OPEN_STATUSES, PRIORITY_ORDER, Notification, Task, User
from ..notify import send_telegram

bp = Blueprint("main", __name__)


def _sort_key(t):
    return (t.due_date or date.max, PRIORITY_ORDER.get(t.priority, 9))


@bp.route("/")
@login_required
def dashboard():
    today = date.today()
    mine = Task.query.filter(Task.assignee_id == current_user.id, Task.status.in_(OPEN_STATUSES)).all()
    overdue = sorted([t for t in mine if t.due_date and t.due_date < today], key=_sort_key)
    due_today = sorted([t for t in mine if t.due_date == today], key=_sort_key)
    upcoming = sorted([t for t in mine if t.due_date and today < t.due_date <= today + timedelta(days=7)],
                      key=_sort_key)
    to_review = [t for t in perm.task_query_for(current_user).filter(Task.status == "review").all()
                 if (t.reviewer_id or t.created_by) == current_user.id]

    team = None
    if current_user.rank >= 2:
        q = perm.task_query_for(current_user)
        if current_user.role not in ("admin", "director"):
            scope = perm.scope_department_ids(current_user)
            q = q.filter(Task.department_id.in_(scope))
        all_tasks = q.filter(Task.parent_id.is_(None)).all()
        open_tasks = [t for t in all_tasks if t.is_open]
        status_counts = Counter(t.status for t in all_tasks if t.status != "cancelled")
        overdue_by = Counter(t.assignee.full_name for t in open_tasks if t.days_overdue and t.assignee)
        load_by = Counter(t.assignee.full_name for t in open_tasks if t.assignee)
        done_7d = sum(1 for t in all_tasks if t.completed_at and t.completed_at.date() >= today - timedelta(days=7))
        projects = (perm.project_query_for(current_user).filter_by(status="active")
                    .order_by("due_date").limit(8).all())
        team = dict(status_counts=status_counts, overdue_by=overdue_by.most_common(10),
                    load_by=load_by.most_common(12), total_open=len(open_tasks),
                    total_overdue=sum(overdue_by.values()), done_7d=done_7d, projects=projects,
                    max_load=max(load_by.values(), default=1))
    return render_template("dashboard.html", overdue=overdue, due_today=due_today, upcoming=upcoming,
                           to_review=to_review, team=team)


# ---------------------------------------------------------------- Thông báo
@bp.route("/notifications")
@login_required
def notifications():
    items = (Notification.query.filter_by(user_id=current_user.id)
             .order_by(Notification.created_at.desc()).limit(200).all())
    return render_template("notifications.html", items=items)


@bp.route("/notifications/<int:nid>/open")
@login_required
def open_notification(nid):
    n = db.session.get(Notification, nid)
    if not n or n.user_id != current_user.id:
        abort(404)
    n.is_read = True
    db.session.commit()
    link = n.link if (n.link or "").startswith("/") else url_for("main.notifications")
    return redirect(link)


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return redirect(url_for("main.notifications"))


# ---------------------------------------------------------------- Hồ sơ + Telegram
@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower() or None
        if email and User.query.filter(User.email == email, User.id != current_user.id).first():
            flash("Email này đã được dùng cho tài khoản khác.", "danger")
        else:
            current_user.email = email
            current_user.phone = (request.form.get("phone") or "").strip()
            db.session.commit()
            flash("Đã lưu hồ sơ.", "success")
        return redirect(url_for("main.profile"))
    bot = current_app.config.get("TELEGRAM_BOT_USERNAME")
    return render_template("profile.html", telegram_ready=bool(bot and current_app.config.get("TELEGRAM_BOT_TOKEN")))


@bp.route("/profile/telegram/connect", methods=["POST"])
@login_required
def telegram_connect():
    bot = current_app.config.get("TELEGRAM_BOT_USERNAME")
    if not bot or not current_app.config.get("TELEGRAM_BOT_TOKEN"):
        flash("Hệ thống chưa cấu hình Telegram bot. Liên hệ quản trị.", "warning")
        return redirect(url_for("main.profile"))
    current_user.telegram_link_token = secrets.token_urlsafe(16)
    db.session.commit()
    return redirect(f"https://t.me/{bot}?start={current_user.telegram_link_token}")


@bp.route("/profile/telegram/disconnect", methods=["POST"])
@login_required
def telegram_disconnect():
    current_user.telegram_chat_id = None
    current_user.telegram_link_token = None
    db.session.commit()
    flash("Đã ngắt kết nối Telegram.", "success")
    return redirect(url_for("main.profile"))


@bp.route("/profile/telegram/test", methods=["POST"])
@login_required
def telegram_test():
    status = send_telegram(current_user.telegram_chat_id,
                           f"<b>{current_app.config['APP_NAME']}</b>\nKết nối Telegram hoạt động tốt.")
    flash("Đã gửi tin thử, hãy kiểm tra Telegram." if status == "sent" else "Gửi thất bại, hãy kết nối lại.",
          "success" if status == "sent" else "danger")
    return redirect(url_for("main.profile"))
