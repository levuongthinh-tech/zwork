import json
import secrets
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import DEPT_LEVELS, PROJECT_TYPES, ROLES, Department, ProjectTemplate, User
from ..services import log_activity

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if current_user.role != "admin":
            abort(403)
        return fn(*a, **kw)
    return wrapper


@bp.route("/")
@admin_required
def index():
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------- Người dùng
@bp.route("/users")
@admin_required
def users():
    items = User.query.order_by(User.is_active_flag.desc(), User.department_id, User.full_name).all()
    return render_template("admin/users.html", items=items)


@bp.route("/users/new", methods=["GET", "POST"])
@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
@admin_required
def user_form(user_id=None):
    u = db.session.get(User, user_id) if user_id else None
    if user_id and not u:
        abort(404)
    if request.method == "POST":
        f = request.form
        username = (f.get("username") or "").strip().lower()
        email = (f.get("email") or "").strip().lower() or None
        if not username or not (f.get("full_name") or "").strip():
            flash("Tên đăng nhập và họ tên là bắt buộc.", "danger")
            return render_template("admin/user_form.html", u=u, form=f, **_ctx()), 400
        dup = User.query.filter(User.username == username, User.id != (u.id if u else 0)).first()
        dup_mail = email and User.query.filter(User.email == email, User.id != (u.id if u else 0)).first()
        if dup or dup_mail:
            flash("Tên đăng nhập hoặc email đã tồn tại.", "danger")
            return render_template("admin/user_form.html", u=u, form=f, **_ctx()), 400
        temp = None
        if not u:
            u = User(username=username)
            temp = secrets.token_urlsafe(6)
            u.set_password(temp)
            u.must_change_password = True
            db.session.add(u)
        u.username = username
        u.email = email
        u.full_name = f["full_name"].strip()
        u.title = (f.get("title") or "").strip()
        u.phone = (f.get("phone") or "").strip()
        u.role = f.get("role") if f.get("role") in ROLES else "staff"
        u.department_id = f.get("department_id", type=int)
        if u.id != current_user.id:
            u.is_active_flag = bool(f.get("is_active"))
        db.session.flush()
        log_activity("user", u.id, current_user, "saved", {"username": u.username, "role": u.role})
        db.session.commit()
        if temp:
            flash(f"Đã tạo tài khoản {u.username}. Mật khẩu tạm: {temp} (bắt buộc đổi khi đăng nhập).", "success")
        else:
            flash("Đã lưu người dùng.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", u=u, form={}, **_ctx())


@bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def reset_password(user_id):
    u = db.session.get(User, user_id) or abort(404)
    temp = secrets.token_urlsafe(6)
    u.set_password(temp)
    u.must_change_password = True
    u.failed_logins = 0
    u.locked_until = None
    log_activity("user", u.id, current_user, "reset_password", {})
    db.session.commit()
    flash(f"Mật khẩu tạm mới của {u.username}: {temp}", "success")
    return redirect(url_for("admin.user_form", user_id=u.id))


def _ctx():
    return dict(roles=ROLES, departments=Department.query.order_by(Department.id).all())


# ---------------------------------------------------------------- Cơ cấu
@bp.route("/departments", methods=["GET", "POST"])
@admin_required
def departments():
    if request.method == "POST":
        f = request.form
        did = f.get("id", type=int)
        d = db.session.get(Department, did) if did else Department()
        if did and not d:
            abort(404)
        name = (f.get("name") or "").strip()
        if not name:
            flash("Tên phòng/nhóm là bắt buộc.", "danger")
            return redirect(url_for("admin.departments"))
        d.name = name
        d.code = (f.get("code") or "").strip().upper() or None
        d.level = f.get("level") if f.get("level") in DEPT_LEVELS else "team"
        parent_id = f.get("parent_id", type=int)
        if did and parent_id and parent_id in d.descendant_ids():
            flash("Không thể chọn đơn vị con làm đơn vị cha.", "danger")
            return redirect(url_for("admin.departments"))
        d.parent_id = parent_id
        db.session.add(d)
        db.session.commit()
        flash("Đã lưu cơ cấu.", "success")
        return redirect(url_for("admin.departments"))
    roots = Department.query.filter(Department.parent_id.is_(None)).order_by(Department.id).all()
    return render_template("admin/departments.html", roots=roots, levels=DEPT_LEVELS,
                           all_depts=Department.query.order_by(Department.id).all())


# ---------------------------------------------------------------- Mẫu dự án
@bp.route("/templates")
@admin_required
def templates():
    return render_template("admin/templates.html", items=ProjectTemplate.query.order_by(ProjectTemplate.id).all(),
                           types=PROJECT_TYPES)


@bp.route("/templates/new", methods=["GET", "POST"])
@bp.route("/templates/<int:tpl_id>", methods=["GET", "POST"])
@admin_required
def template_form(tpl_id=None):
    t = db.session.get(ProjectTemplate, tpl_id) if tpl_id else ProjectTemplate(tasks_json="[]")
    if t is None:
        abort(404)
    if request.method == "POST":
        f = request.form
        items = []
        # Mỗi dòng: Tiêu đề | ngày bắt đầu | ngày hạn | duyệt (x) | ưu tiên
        for line in (f.get("lines") or "").splitlines():
            parts = [p.strip() for p in line.split("|")]
            if not parts or not parts[0]:
                continue
            try:
                s = int(parts[1]) if len(parts) > 1 and parts[1] else 0
                d = int(parts[2]) if len(parts) > 2 and parts[2] else s
            except ValueError:
                flash(f"Dòng không hợp lệ: {line}", "danger")
                return render_template("admin/template_form.html", t=t, lines=f.get("lines"), types=PROJECT_TYPES)
            items.append({"title": parts[0], "offset_start": s, "offset_due": max(s, d),
                          "needs_review": len(parts) > 3 and parts[3].lower() in ("x", "1", "có", "co"),
                          "priority": parts[4] if len(parts) > 4 and parts[4] in ("low", "normal", "high", "urgent")
                          else "normal", "checklist": []})
        old = {i["title"]: i for i in t.items}
        for i in items:  # giữ checklist cũ theo tiêu đề
            i["checklist"] = old.get(i["title"], {}).get("checklist", [])
        t.name = (f.get("name") or "Mẫu mới").strip()
        t.type = f.get("type") if f.get("type") in PROJECT_TYPES else "other"
        t.description = f.get("description", "")
        t.tasks_json = json.dumps(items, ensure_ascii=False)
        db.session.add(t)
        db.session.commit()
        flash("Đã lưu mẫu dự án.", "success")
        return redirect(url_for("admin.templates"))
    lines = "\n".join(
        f"{i['title']} | {i.get('offset_start', 0)} | {i.get('offset_due', 0)} | "
        f"{'x' if i.get('needs_review') else ''} | {i.get('priority', 'normal')}" for i in t.items)
    return render_template("admin/template_form.html", t=t, lines=lines, types=PROJECT_TYPES)


@bp.route("/users/issue-passwords", methods=["POST"])
@admin_required
def issue_passwords():
    """Cấp mật khẩu tạm hàng loạt cho người chưa từng đăng nhập (để phát cho nhân viên lần đầu)."""
    rows = []
    for u in User.query.filter(User.is_active_flag.is_(True), User.role != "admin",
                               User.last_login_at.is_(None)).order_by(User.department_id, User.full_name):
        temp = secrets.token_urlsafe(6)
        u.set_password(temp)
        u.must_change_password = True
        u.failed_logins = 0
        u.locked_until = None
        rows.append((u, temp))
    log_activity("user", current_user.id, current_user, "issue_passwords", {"count": len(rows)})
    db.session.commit()
    return render_template("admin/passwords.html", rows=rows)
