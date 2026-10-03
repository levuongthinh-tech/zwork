import os
import uuid
from datetime import date, timedelta

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory,
                   url_for)
from flask_login import current_user, login_required
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from .. import permissions as perm
from ..extensions import db
from ..models import (KANBAN_COLUMNS, OPEN_STATUSES, PRIORITIES, PRIORITY_ORDER, ActivityLog, Attachment,
                      ChecklistItem, Comment, Department, Project, Task, User)
from ..notify import notify, notify_many
from ..services import create_task, get_user, log_activity, mentioned_users, parse_date, task_link
from ..workflow import WorkflowError, allowed_targets, transition

bp = Blueprint("tasks", __name__, url_prefix="/tasks")


def get_task(task_id, edit=False):
    t = db.session.get(Task, task_id)
    if not t or not perm.can_view_task(current_user, t):
        abort(404)
    if edit and not perm.can_edit_task(current_user, t):
        abort(403)
    return t


def sort_tasks(tasks):
    return sorted(tasks, key=lambda t: (t.due_date or date.max, PRIORITY_ORDER.get(t.priority, 9), t.id))


# ---------------------------------------------------------------- Danh sách
@bp.route("/my")
@login_required
def my():
    today = date.today()
    mine = sort_tasks(Task.query.filter(Task.assignee_id == current_user.id, Task.status.in_(OPEN_STATUSES)).all())
    week_end = today + timedelta(days=6 - today.weekday())
    groups = [
        ("Quá hạn", [t for t in mine if t.due_date and t.due_date < today], "danger"),
        ("Hôm nay", [t for t in mine if t.due_date == today], "warn"),
        ("Tuần này", [t for t in mine if t.due_date and today < t.due_date <= week_end], ""),
        ("Sau đó", [t for t in mine if not t.due_date or t.due_date > week_end], ""),
    ]
    reviewing = [t for t in perm.task_query_for(current_user).filter(Task.status == "review").all()
                 if (t.reviewer_id or t.created_by) == current_user.id]
    created_by_me = sort_tasks(Task.query.filter(Task.created_by == current_user.id,
                                                 Task.assignee_id != current_user.id,
                                                 Task.status.in_(OPEN_STATUSES)).all())
    return render_template("tasks/my.html", groups=groups, reviewing=reviewing, created_by_me=created_by_me)


def filtered_query(args):
    q = perm.task_query_for(current_user)
    if args.get("q"):
        like = f"%{args['q'].strip()}%"
        q = q.filter(or_(Task.title.ilike(like), Task.code.ilike(like)))
    if args.get("assignee"):
        q = q.filter(Task.assignee_id == int(args["assignee"]))
    if args.get("project"):
        q = q.filter(Task.project_id == int(args["project"]))
    if args.get("dept"):
        d = db.session.get(Department, int(args["dept"]))
        if d:
            q = q.filter(Task.department_id.in_(d.descendant_ids()))
    if args.get("priority"):
        q = q.filter(Task.priority == args["priority"])
    status = args.get("status", "open")
    if status == "open":
        q = q.filter(Task.status.in_(OPEN_STATUSES))
    elif status and status != "all":
        q = q.filter(Task.status == status)
    due = args.get("due")
    today = date.today()
    if due == "overdue":
        q = q.filter(Task.due_date < today, Task.status.in_(OPEN_STATUSES))
    elif due == "week":
        q = q.filter(Task.due_date >= today, Task.due_date <= today + timedelta(days=7))
    if not args.get("subtasks"):
        q = q.filter(Task.parent_id.is_(None))
    return q


@bp.route("/")
@login_required
def index():
    view = request.args.get("view", "list")
    args = request.args.to_dict()
    if view == "kanban" and args.get("status", "open") == "open":
        args["status"] = "all"
    tasks = sort_tasks(filtered_query(args).limit(1000).all())
    if view == "kanban":
        recent = date.today() - timedelta(days=14)
        tasks = [t for t in tasks if t.status in KANBAN_COLUMNS
                 and not (t.status == "done" and t.completed_at and t.completed_at.date() < recent)]
    return render_template(
        "tasks/index.html", tasks=tasks, view=view,
        users=perm.assignable_users(current_user),
        projects=perm.project_query_for(current_user).order_by(Project.name).all(),
        departments=perm.project_departments_for(current_user), kanban_columns=KANBAN_COLUMNS,
    )


# ---------------------------------------------------------------- Tạo / sửa
def _form_context(task=None, project=None, parent=None):
    project = project or (task.project if task else None) or (parent.project if parent else None)
    return dict(
        task=task, project=project, parent=parent,
        users=perm.assignable_users(current_user, project),
        all_users=User.query.filter(User.is_active_flag.is_(True)).order_by(User.full_name).all(),
        projects=perm.project_query_for(current_user).filter(Project.status.in_(["planning", "active"]))
        .order_by(Project.name).all(),
        priorities=PRIORITIES,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    project = db.session.get(Project, request.values.get("project_id", type=int) or 0)
    parent = db.session.get(Task, request.values.get("parent_id", type=int) or 0)
    if project and not perm.can_view_project(current_user, project):
        abort(404)
    if parent and not perm.can_edit_task(current_user, parent):
        abort(403)
    if request.method == "POST":
        f = request.form
        if not parent and f.get("project_id"):
            project = db.session.get(Project, int(f["project_id"]))
            if project and not perm.can_view_project(current_user, project):
                abort(403)
        elif not parent:
            project = None
        assignee = get_user(f.get("assignee_id")) or current_user
        due = parse_date(f.get("due_date"))
        errors = []
        if not (f.get("title") or "").strip():
            errors.append("Vui lòng nhập tiêu đề.")
        if not due:
            errors.append("Vui lòng chọn hạn chót.")
        if not perm.can_assign_to(current_user, assignee, project):
            errors.append("Bạn không được giao việc cho người này.")
        if parent and parent.parent_id:
            errors.append("Việc con không được có việc con.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("tasks/form.html", form=f, **_form_context(project=project, parent=parent)), 400
        task = create_task(
            current_user, f["title"], assignee, due, project=project, parent=parent,
            description=f.get("description", ""), priority=f.get("priority", "normal"),
            start_date=parse_date(f.get("start_date")), reviewer=get_user(f.get("reviewer_id")),
            needs_review=bool(f.get("needs_review")), estimate_hours=f.get("estimate_hours", type=float),
            watchers=[get_user(x) for x in f.getlist("watcher_ids")],
            checklist=[x for x in (f.get("checklist") or "").splitlines()],
        )
        db.session.commit()
        flash(f"Đã tạo việc {task.code}.", "success")
        return redirect(url_for("tasks.detail", task_id=parent.id if parent else task.id))
    return render_template("tasks/form.html", form={}, **_form_context(project=project, parent=parent))


@bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit(task_id):
    task = get_task(task_id, edit=True)
    is_mgr = perm.is_task_manager(current_user, task)
    if request.method == "POST":
        f = request.form
        changes = {}
        title = (f.get("title") or "").strip()
        if not title:
            flash("Vui lòng nhập tiêu đề.", "danger")
            return redirect(url_for("tasks.edit", task_id=task.id))
        for field in ("title", "description", "priority"):
            val = (f.get(field) or "").strip() if field != "description" else (f.get(field) or "")
            if val != (getattr(task, field) or ""):
                changes[field] = val
                setattr(task, field, val)
        task.start_date = parse_date(f.get("start_date"))
        task.estimate_hours = f.get("estimate_hours", type=float)
        new_due = parse_date(f.get("due_date"))
        if new_due and new_due != task.due_date:
            reason = (f.get("due_reason") or "").strip()
            if task.due_changes >= 1 and not reason:
                flash("Đây là lần dời hạn thứ 2 trở lên: vui lòng ghi lý do.", "danger")
                return redirect(url_for("tasks.edit", task_id=task.id))
            changes["due_date"] = {"from": task.due_date, "to": new_due, "reason": reason}
            task.due_changes = (task.due_changes or 0) + 1
            task.due_date = new_due
        if is_mgr:
            assignee = get_user(f.get("assignee_id"))
            if assignee and assignee.id != task.assignee_id:
                if not perm.can_assign_to(current_user, assignee, task.project):
                    flash("Bạn không được giao việc cho người này.", "danger")
                    return redirect(url_for("tasks.edit", task_id=task.id))
                changes["assignee"] = assignee.full_name
                task.assignee_id = assignee.id
                task.department_id = assignee.department_id or task.department_id
                notify(assignee, "task_assigned", f"Việc mới: {task.title}",
                       f"Giao bởi {current_user.full_name} · Hạn {task.due_date:%d/%m/%Y}" if task.due_date else "",
                       task_link(task), push=True, actor=current_user)
            reviewer = get_user(f.get("reviewer_id"))
            task.reviewer_id = reviewer.id if reviewer else None
            task.needs_review = bool(f.get("needs_review"))
            ids = {int(x) for x in f.getlist("watcher_ids") if x}
            task.watchers = [u for u in User.query.filter(User.id.in_(ids)).all() if u.id != task.assignee_id]
        if changes:
            log_activity("task", task.id, current_user, "updated", changes)
        db.session.commit()
        flash("Đã lưu thay đổi.", "success")
        return redirect(url_for("tasks.detail", task_id=task.id))
    return render_template("tasks/form.html", form={}, is_mgr=is_mgr, **_form_context(task=task))


@bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete(task_id):
    task = get_task(task_id)
    if not perm.can_delete_task(current_user, task):
        abort(403)
    back = url_for("tasks.detail", task_id=task.parent_id) if task.parent_id else (
        url_for("projects.detail", project_id=task.project_id) if task.project_id else url_for("tasks.my"))
    for sub in list(task.subtasks):
        db.session.delete(sub)
    log_activity("task", task.id, current_user, "deleted", {"title": task.title, "code": task.code})
    db.session.delete(task)
    db.session.commit()
    flash("Đã xóa công việc.", "success")
    return redirect(back)


# ---------------------------------------------------------------- Chi tiết
@bp.route("/<int:task_id>")
@login_required
def detail(task_id):
    task = get_task(task_id)
    logs = (ActivityLog.query.filter_by(entity_type="task", entity_id=task.id)
            .order_by(ActivityLog.created_at.desc()).limit(100).all())
    mention_candidates = sorted({u for u in [task.assignee, task.creator, task.reviewer, *task.watchers] if u}
                                | set(perm.assignable_users(current_user, task.project)),
                                key=lambda u: u.full_name)
    return render_template(
        "tasks/detail.html", task=task, logs=logs, targets=allowed_targets(current_user, task),
        can_edit=perm.can_edit_task(current_user, task), can_delete=perm.can_delete_task(current_user, task),
        mention_candidates=mention_candidates,
    )


@bp.route("/<int:task_id>/status", methods=["POST"])
@login_required
def change_status(task_id):
    task = get_task(task_id)
    try:
        transition(task, request.form.get("status"), current_user, request.form.get("note"))
        db.session.commit()
        flash(f"Đã chuyển sang \"{task.status_label}\".", "success")
    except WorkflowError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(request.referrer or url_for("tasks.detail", task_id=task.id))


@bp.route("/<int:task_id>/comments", methods=["POST"])
@login_required
def add_comment(task_id):
    task = get_task(task_id)
    content = (request.form.get("content") or "").strip()
    if not content:
        return redirect(url_for("tasks.detail", task_id=task.id))
    db.session.add(Comment(task_id=task.id, user_id=current_user.id, content=content[:5000]))
    link = task_link(task) + "#comments"
    candidates = User.query.filter(User.is_active_flag.is_(True)).all()
    mentioned = [u for u in mentioned_users(content, candidates) if perm.can_view_task(u, task)]
    for u in mentioned:
        notify(u, "mention", f"{current_user.full_name} nhắc bạn: {task.title}", content[:300], link,
               push=True, actor=current_user)
    others = [u for u in [task.assignee, task.creator, *task.watchers] if u and u not in mentioned]
    notify_many(others, "comment", f"Bình luận mới: {task.title}", f"{current_user.full_name}: {content[:200]}",
                link, actor=current_user)
    db.session.commit()
    return redirect(link)


# ---------------------------------------------------------------- Checklist
@bp.route("/<int:task_id>/checklist", methods=["POST"])
@login_required
def checklist_add(task_id):
    task = get_task(task_id, edit=True)
    content = (request.form.get("content") or "").strip()
    if content:
        db.session.add(ChecklistItem(task_id=task.id, content=content[:255], position=len(task.checklist)))
        db.session.commit()
    return redirect(url_for("tasks.detail", task_id=task.id) + "#checklist")


@bp.route("/<int:task_id>/checklist/<int:item_id>/toggle", methods=["POST"])
@login_required
def checklist_toggle(task_id, item_id):
    task = get_task(task_id, edit=True)
    item = db.session.get(ChecklistItem, item_id)
    if not item or item.task_id != task.id:
        abort(404)
    item.is_done = not item.is_done
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return {"ok": True, "done": item.is_done, "count": task.checklist_done, "total": len(task.checklist)}
    return redirect(url_for("tasks.detail", task_id=task.id) + "#checklist")


@bp.route("/<int:task_id>/checklist/<int:item_id>/delete", methods=["POST"])
@login_required
def checklist_delete(task_id, item_id):
    task = get_task(task_id, edit=True)
    item = db.session.get(ChecklistItem, item_id)
    if item and item.task_id == task.id:
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for("tasks.detail", task_id=task.id) + "#checklist")


# ---------------------------------------------------------------- Tệp đính kèm
@bp.route("/<int:task_id>/attachments", methods=["POST"])
@login_required
def upload(task_id):
    task = get_task(task_id)
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Chưa chọn tệp.", "warning")
        return redirect(url_for("tasks.detail", task_id=task.id))
    name = secure_filename(f.filename) or "tep"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in current_app.config["ALLOWED_EXTENSIONS"]:
        flash("Định dạng tệp không được hỗ trợ.", "danger")
        return redirect(url_for("tasks.detail", task_id=task.id))
    stored = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
    f.save(path)
    db.session.add(Attachment(task_id=task.id, filename=f.filename[:255], stored_path=stored,
                              size=os.path.getsize(path), mime=f.mimetype, uploaded_by=current_user.id))
    log_activity("task", task.id, current_user, "attachment", {"filename": f.filename})
    db.session.commit()
    return redirect(url_for("tasks.detail", task_id=task.id) + "#files")


@bp.route("/<int:task_id>/attachments/<int:att_id>")
@login_required
def download(task_id, att_id):
    task = get_task(task_id)
    att = db.session.get(Attachment, att_id)
    if not att or att.task_id != task.id:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], att.stored_path,
                               as_attachment=True, download_name=att.filename)


@bp.route("/<int:task_id>/attachments/<int:att_id>/delete", methods=["POST"])
@login_required
def delete_attachment(task_id, att_id):
    task = get_task(task_id)
    att = db.session.get(Attachment, att_id)
    if not att or att.task_id != task.id:
        abort(404)
    if att.uploaded_by != current_user.id and not perm.is_task_manager(current_user, task):
        abort(403)
    try:
        os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], att.stored_path))
    except OSError:
        pass
    db.session.delete(att)
    db.session.commit()
    return redirect(url_for("tasks.detail", task_id=task.id) + "#files")
