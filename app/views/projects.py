from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import permissions as perm
from ..extensions import db
from ..models import (KANBAN_COLUMNS, PROJECT_STATUSES, PROJECT_TYPES, Project, ProjectMember, ProjectTemplate,
                      Task, User)
from ..services import apply_template, create_project, get_user, log_activity, parse_date
from .tasks import sort_tasks

bp = Blueprint("projects", __name__, url_prefix="/projects")


def get_project(project_id, manage=False):
    p = db.session.get(Project, project_id)
    if not p or not perm.can_view_project(current_user, p):
        abort(404)
    if manage and not perm.can_manage_project(current_user, p):
        abort(403)
    return p


@bp.route("/")
@login_required
def index():
    status = request.args.get("status", "running")
    q = perm.project_query_for(current_user)
    if status == "running":
        q = q.filter(Project.status.in_(["planning", "active", "on_hold"]))
    elif status != "all":
        q = q.filter(Project.status == status)
    projects = q.order_by(Project.due_date.is_(None), Project.due_date).all()
    return render_template("projects/index.html", projects=projects, status=status,
                           can_create=perm.can_create_project(current_user))


def _form_ctx(project=None):
    return dict(project=project, types=PROJECT_TYPES, statuses=PROJECT_STATUSES,
                departments=perm.project_departments_for(current_user),
                users=perm.assignable_users(current_user),
                templates=ProjectTemplate.query.order_by(ProjectTemplate.name).all())


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if not perm.can_create_project(current_user):
        abort(403)
    if request.method == "POST":
        f = request.form
        if not (f.get("name") or "").strip():
            flash("Vui lòng nhập tên dự án.", "danger")
            return render_template("projects/form.html", form=f, **_form_ctx()), 400
        dept_ids = {d.id for d in perm.project_departments_for(current_user)}
        dept_id = f.get("department_id", type=int)
        if dept_id not in dept_ids:
            dept_id = current_user.department_id
        owner = get_user(f.get("owner_id")) or current_user
        if not perm.can_assign_to(current_user, owner):
            owner = current_user
        members = [get_user(x) for x in f.getlist("member_ids")]
        members = [m for m in members if m and perm.can_assign_to(current_user, m)]
        p = create_project(current_user, name=f["name"], type_=f.get("type", "other"), department_id=dept_id,
                           owner=owner, description=f.get("description", ""),
                           start_date=parse_date(f.get("start_date")), due_date=parse_date(f.get("due_date")),
                           budget=f.get("budget", type=float) or 0, members=members)
        tpl = db.session.get(ProjectTemplate, f.get("template_id", type=int) or 0)
        if tpl:
            start = parse_date(f.get("start_date")) or date.today()
            created = apply_template(p, tpl, start, current_user)
            flash(f"Đã tạo {len(created)} việc từ mẫu \"{tpl.name}\". Hãy phân công người phụ trách.", "success")
        db.session.commit()
        flash(f"Đã tạo dự án {p.code}.", "success")
        return redirect(url_for("projects.detail", project_id=p.id))
    return render_template("projects/form.html", form={}, **_form_ctx())


@bp.route("/<int:project_id>")
@login_required
def detail(project_id):
    p = get_project(project_id)
    view = request.args.get("view", "list")
    tasks = sort_tasks(p.tasks.filter(Task.parent_id.is_(None)).all())
    show_closed = request.args.get("closed") == "1"
    if view == "list" and not show_closed:
        tasks = [t for t in tasks if t.status != "cancelled"]
    ctx = dict(project=p, view=view, tasks=tasks, can_manage=perm.can_manage_project(current_user, p),
               kanban_columns=KANBAN_COLUMNS, show_closed=show_closed)
    if view == "timeline":
        dated = [t for t in tasks if t.due_date and t.status != "cancelled"]
        starts = [t.start_date or t.due_date for t in dated] + ([p.start_date] if p.start_date else [])
        ends = [t.due_date for t in dated] + ([p.due_date] if p.due_date else [])
        lo = min(starts, default=date.today())
        hi = max(ends, default=date.today() + timedelta(days=30))
        lo = lo - timedelta(days=lo.weekday())  # đầu tuần
        span = max((hi - lo).days + 1, 7)
        weeks = [lo + timedelta(days=7 * i) for i in range(span // 7 + 1)]
        ctx.update(timeline=dict(lo=lo, span=span, weeks=weeks, tasks=dated))
    if view == "members":
        ctx["candidates"] = [u for u in perm.assignable_users(current_user)
                             if u.id not in p.member_ids()] if ctx["can_manage"] else []
    return render_template("projects/detail.html", **ctx)


@bp.route("/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit(project_id):
    p = get_project(project_id, manage=True)
    if request.method == "POST":
        f = request.form
        p.name = (f.get("name") or p.name).strip()
        p.type = f.get("type", p.type)
        p.status = f.get("status", p.status) if f.get("status") in PROJECT_STATUSES else p.status
        p.description = f.get("description", "")
        p.start_date = parse_date(f.get("start_date"))
        p.due_date = parse_date(f.get("due_date"))
        p.budget = f.get("budget", type=float) or 0
        p.spent = f.get("spent", type=float) or 0
        owner = get_user(f.get("owner_id"))
        if owner and perm.can_assign_to(current_user, owner) and owner.id != p.owner_id:
            p.owner_id = owner.id
            if owner.id not in {m.user_id for m in p.members}:
                p.members.append(ProjectMember(user_id=owner.id, member_role="owner"))
        log_activity("project", p.id, current_user, "updated", {"status": p.status})
        db.session.commit()
        flash("Đã lưu dự án.", "success")
        return redirect(url_for("projects.detail", project_id=p.id, view="info"))
    return render_template("projects/form.html", form={}, **_form_ctx(p))


@bp.route("/<int:project_id>/members", methods=["POST"])
@login_required
def add_member(project_id):
    p = get_project(project_id, manage=True)
    for uid in request.form.getlist("user_ids"):
        u = get_user(uid)
        if u and perm.can_assign_to(current_user, u) and u.id not in {m.user_id for m in p.members}:
            p.members.append(ProjectMember(user_id=u.id))
    db.session.commit()
    return redirect(url_for("projects.detail", project_id=p.id, view="members"))


@bp.route("/<int:project_id>/members/<int:user_id>/remove", methods=["POST"])
@login_required
def remove_member(project_id, user_id):
    p = get_project(project_id, manage=True)
    if user_id == p.owner_id:
        flash("Không thể xóa chủ dự án.", "warning")
    else:
        ProjectMember.query.filter_by(project_id=p.id, user_id=user_id).delete()
        db.session.commit()
    return redirect(url_for("projects.detail", project_id=p.id, view="members"))


@bp.route("/<int:project_id>/delete", methods=["POST"])
@login_required
def delete(project_id):
    p = get_project(project_id, manage=True)
    if current_user.rank < 3 and p.tasks.filter(Task.status != "new").count():
        flash("Dự án đã có việc đang chạy: chỉ Trưởng phòng trở lên được xóa. Hãy chuyển trạng thái Hủy.", "warning")
        return redirect(url_for("projects.detail", project_id=p.id, view="info"))
    for t in p.tasks.filter(Task.parent_id.isnot(None)).all():
        db.session.delete(t)
    for t in p.tasks.all():
        db.session.delete(t)
    log_activity("project", p.id, current_user, "deleted", {"name": p.name, "code": p.code})
    db.session.delete(p)
    db.session.commit()
    flash("Đã xóa dự án.", "success")
    return redirect(url_for("projects.index"))
