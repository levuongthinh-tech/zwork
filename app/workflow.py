"""Quy tắc chuyển trạng thái công việc (Mục 5 tài liệu đặc tả).

Đây là nơi DUY NHẤT được đổi Task.status – cả form, Kanban kéo-thả và API đều gọi transition().
"""
from datetime import datetime

from . import permissions as perm
from .models import TASK_STATUSES
from .notify import notify, notify_many
from .services import log_activity, task_link


class WorkflowError(Exception):
    pass


# (từ, đến) -> vai trò được phép: "assignee", "reviewer", "manager"
TRANSITIONS = {
    ("new", "in_progress"): {"assignee", "manager"},
    ("in_progress", "review"): {"assignee", "manager"},
    ("in_progress", "done"): {"assignee", "manager"},
    ("review", "done"): {"reviewer"},
    ("review", "revision"): {"reviewer"},
    ("revision", "review"): {"assignee", "manager"},
    ("in_progress", "paused"): {"assignee", "manager"},
    ("paused", "in_progress"): {"assignee", "manager"},
    ("done", "in_progress"): {"manager"},  # mở lại
}
for _s in ("new", "in_progress", "review", "revision", "paused"):
    TRANSITIONS[(_s, "cancelled")] = {"manager"}

NOTE_REQUIRED = {"revision", "paused", "cancelled"}


def actor_roles(user, task):
    roles = set()
    if task.assignee_id == user.id:
        roles.add("assignee")
    if perm.is_task_manager(user, task):
        roles.add("manager")
    reviewer_id = task.reviewer_id or task.created_by
    if user.id == reviewer_id or user.role in ("admin", "director"):
        roles.add("reviewer")
    elif task.reviewer_id is None and "manager" in roles:
        roles.add("reviewer")
    return roles


def allowed_targets(user, task):
    """Các trạng thái user được phép chuyển task sang (dùng để vẽ nút)."""
    roles = actor_roles(user, task)
    out = []
    for (src, dst), who in TRANSITIONS.items():
        if src != task.status or not (roles & who):
            continue
        if (src, dst) == ("in_progress", "review") and not task.needs_review:
            continue
        if (src, dst) == ("in_progress", "done") and task.needs_review:
            continue
        out.append(dst)
    return out


def transition(task, new_status, user, note=None):
    if new_status not in TASK_STATUSES:
        raise WorkflowError("Trạng thái không hợp lệ.")
    if new_status == task.status:
        return task
    key = (task.status, new_status)
    if key not in TRANSITIONS:
        raise WorkflowError(
            f"Không thể chuyển từ \"{task.status_label}\" sang \"{TASK_STATUSES[new_status]}\"."
        )
    if new_status not in allowed_targets(user, task):
        if key == ("in_progress", "done") and task.needs_review:
            raise WorkflowError("Việc này cần duyệt: hãy gửi duyệt thay vì hoàn thành trực tiếp.")
        if key == ("in_progress", "review") and not task.needs_review:
            raise WorkflowError("Việc này không cần duyệt: có thể chuyển thẳng sang Hoàn thành.")
        raise WorkflowError("Bạn không có quyền thực hiện bước chuyển này.")
    if new_status in NOTE_REQUIRED and not (note or "").strip():
        raise WorkflowError("Vui lòng ghi lý do / nhận xét cho bước chuyển này.")
    if new_status in ("done", "review"):
        open_subs = [s for s in task.subtasks if s.is_open]
        if open_subs:
            raise WorkflowError(f"Còn {len(open_subs)} việc con chưa xong.")
        if new_status == "done" and key == ("in_progress", "done") and task.checklist_done < len(task.checklist):
            raise WorkflowError("Checklist chưa hoàn thành hết.")

    old = task.status
    task.status = new_status
    task.completed_at = datetime.now() if new_status == "done" else None
    log_activity("task", task.id, user, "status", {"from": old, "to": new_status, "note": note or ""})

    link = task_link(task)
    reviewer = task.reviewer or task.creator
    if new_status == "review":
        notify(reviewer, "task_review", f"Chờ duyệt: {task.title}", f"{user.full_name} đã gửi duyệt.",
               link, push=True, actor=user)
    elif new_status == "revision":
        notify(task.assignee, "task_revision", f"Cần sửa: {task.title}", note, link, push=True, actor=user)
    elif new_status == "done":
        if old == "review":
            notify(task.assignee, "task_approved", f"Đã duyệt: {task.title}", note or "", link,
                   push=True, actor=user)
        notify_many([task.creator] + list(task.watchers), "task_done", f"Hoàn thành: {task.title}",
                    f"bởi {user.full_name}", link, actor=user)
    else:
        notify_many([task.assignee, task.creator], "task_status",
                    f"{TASK_STATUSES[new_status]}: {task.title}", note or "", link, actor=user)
    return task
