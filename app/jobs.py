"""Tác vụ nền chạy bằng Railway Cron: `flask jobs daily` (8:00) và `flask jobs weekly` (17:00 thứ Sáu)."""
from collections import defaultdict
from datetime import date, timedelta

from .extensions import db
from .models import OPEN_STATUSES, Task, User
from .notify import notify
from .permissions import direct_manager
from .services import task_link


def run_daily():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    sent = {"due_soon": 0, "overdue": 0, "manager_digest": 0}

    due_soon = Task.query.filter(Task.status.in_(OPEN_STATUSES), Task.due_date == tomorrow,
                                 Task.assignee_id.isnot(None)).all()
    for t in due_soon:
        notify(t.assignee, "task_due_soon", f"Hạn ngày mai: {t.title}", f"Hạn {tomorrow:%d/%m/%Y}",
               task_link(t), push=True)
        sent["due_soon"] += 1

    overdue = Task.query.filter(Task.status.in_(OPEN_STATUSES), Task.due_date < today,
                                Task.assignee_id.isnot(None)).all()
    by_manager = defaultdict(list)
    for t in overdue:
        notify(t.assignee, "task_overdue", f"Quá hạn {t.days_overdue} ngày: {t.title}", "",
               task_link(t), push=True)
        sent["overdue"] += 1
        mgr = direct_manager(t.assignee)
        if mgr and mgr.id != t.assignee_id:
            by_manager[mgr.id].append(t)

    for mgr_id, tasks in by_manager.items():
        mgr = db.session.get(User, mgr_id)
        lines = [f"- {t.assignee.full_name}: {t.title} (trễ {t.days_overdue} ngày)" for t in tasks[:15]]
        if len(tasks) > 15:
            lines.append(f"... và {len(tasks) - 15} việc khác")
        notify(mgr, "team_overdue", f"Đội của bạn có {len(tasks)} việc quá hạn", "\n".join(lines),
               "/tasks?view=list&due=overdue", push=True)
        sent["manager_digest"] += 1

    db.session.commit()
    return sent


def run_weekly():
    today = date.today()
    week_ago = today - timedelta(days=7)
    managers = User.query.filter(User.role.in_(["manager", "director"]), User.is_active_flag.is_(True)).all()
    from .permissions import task_query_for
    count = 0
    for m in managers:
        q = task_query_for(m)
        done = q.filter(Task.status == "done", Task.completed_at >= week_ago).count()
        created = q.filter(Task.created_at >= week_ago).count()
        overdue = q.filter(Task.status.in_(OPEN_STATUSES), Task.due_date < today).count()
        open_ = q.filter(Task.status.in_(OPEN_STATUSES)).count()
        body = (f"Hoàn thành: {done} · Tạo mới: {created}\n"
                f"Đang mở: {open_} · Quá hạn: {overdue}")
        notify(m, "weekly_summary", f"Tổng hợp tuần {week_ago:%d/%m}–{today:%d/%m}", body, "/", push=True)
        count += 1
    db.session.commit()
    return {"weekly_summary": count}
