"""Nghiệp vụ dùng chung: sinh mã, ghi lịch sử, tạo việc, tạo dự án từ mẫu, nhắc tên."""
import json
import re
from datetime import date, timedelta

from flask import url_for

from .extensions import db
from .models import ActivityLog, Project, Task, User


def next_code(prefix, model):
    """DA-2026-001 cho dự án, CV-2026-0001 cho công việc."""
    year = date.today().year
    stem = f"{prefix}-{year}-"
    last = (model.query.filter(model.code.like(f"{stem}%")).order_by(model.id.desc()).first())
    n = int(last.code.rsplit("-", 1)[1]) + 1 if last and last.code else 1
    width = 3 if prefix == "DA" else 4
    return f"{stem}{n:0{width}d}"


def log_activity(entity_type, entity_id, user, action, detail=None):
    db.session.add(ActivityLog(
        entity_type=entity_type, entity_id=entity_id, user_id=user.id if user else None,
        action=action, detail_json=json.dumps(detail or {}, ensure_ascii=False, default=str),
    ))


def task_link(task):
    try:
        return url_for("tasks.detail", task_id=task.id)
    except RuntimeError:
        return f"/tasks/{task.id}"


def create_task(actor, title, assignee, due_date, *, project=None, parent=None, description="",
                priority="normal", start_date=None, reviewer=None, needs_review=False,
                estimate_hours=None, watchers=(), source="manual", source_id=None, checklist=(),
                notify_assignee=True):
    from .models import ChecklistItem
    from .notify import notify

    if parent is not None:
        if parent.parent_id is not None:
            raise ValueError("Việc con không được có việc con (tối đa 1 cấp).")
        project = parent.project
    task = Task(
        code=next_code("CV", Task), title=title.strip(), description=description or "",
        project=project, parent=parent, assignee_id=assignee.id if assignee else None,
        reviewer_id=reviewer.id if reviewer else None, created_by=actor.id,
        department_id=(assignee.department_id if assignee else None) or (project.department_id if project else None),
        priority=priority or "normal", start_date=start_date, due_date=due_date,
        estimate_hours=estimate_hours, needs_review=bool(needs_review), source=source, source_id=source_id,
    )
    for w in watchers:
        if w and w not in task.watchers and (not assignee or w.id != assignee.id):
            task.watchers.append(w)
    for i, item in enumerate(checklist):
        if item and str(item).strip():
            task.checklist.append(ChecklistItem(content=str(item).strip()[:255], position=i))
    db.session.add(task)
    db.session.flush()
    log_activity("task", task.id, actor, "created", {"assignee": assignee.full_name if assignee else None})
    if notify_assignee and assignee:
        due = due_date.strftime("%d/%m/%Y") if due_date else "không có"
        notify(assignee, "task_assigned", f"Việc mới: {task.title}",
               f"Giao bởi {actor.full_name} · Hạn {due}", task_link(task), push=True, actor=actor)
    return task


def create_project(actor, *, name, type_="other", department_id=None, owner=None, description="",
                   start_date=None, due_date=None, budget=0, members=()):
    from .models import ProjectMember

    p = Project(code=next_code("DA", Project), name=name.strip(), type=type_, department_id=department_id,
                owner_id=(owner or actor).id, description=description, start_date=start_date,
                due_date=due_date, budget=budget or 0, status="planning", created_by=actor.id)
    db.session.add(p)
    db.session.flush()
    ids = {u.id for u in members if u} | {p.owner_id}
    for uid in ids:
        p.members.append(ProjectMember(user_id=uid, member_role="owner" if uid == p.owner_id else "member"))
    log_activity("project", p.id, actor, "created", {"name": p.name})
    return p


def apply_template(project, template, start_date, actor):
    """Sinh toàn bộ việc từ mẫu. Hạn chót = ngày bắt đầu + số ngày lệch. Việc giao cho chủ dự án."""
    owner = project.owner or actor
    created = []
    last_due = start_date
    for item in template.items:
        s = start_date + timedelta(days=int(item.get("offset_start", 0)))
        d = start_date + timedelta(days=int(item.get("offset_due", item.get("offset_start", 0))))
        last_due = max(last_due, d)
        t = create_task(actor, item["title"], owner, d, project=project, start_date=s,
                        priority=item.get("priority", "normal"), needs_review=item.get("needs_review", False),
                        description=item.get("description", ""), checklist=item.get("checklist", []),
                        source="template", source_id=template.id, notify_assignee=False)
        created.append(t)
    project.start_date = project.start_date or start_date
    project.due_date = project.due_date or last_due
    if created:
        from .notify import notify
        notify(owner, "project_created", f"Dự án {project.code} đã tạo {len(created)} việc từ mẫu",
               "Hãy phân công người phụ trách.", f"/projects/{project.id}",
               push=True, actor=actor)
    return created


def mentioned_users(content, candidates):
    """Tìm người được nhắc bằng @Họ Tên trong nội dung bình luận."""
    found = []
    for u in sorted(candidates, key=lambda x: -len(x.full_name)):
        if re.search(r"@" + re.escape(u.full_name) + r"(?!\w)", content, flags=re.IGNORECASE):
            found.append(u)
    return found


def parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def get_user(user_id):
    try:
        return db.session.get(User, int(user_id)) if user_id else None
    except (TypeError, ValueError):
        return None
