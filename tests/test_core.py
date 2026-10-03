"""Kiểm thử theo tiêu chí nghiệm thu GĐ1 (Mục 8 tài liệu đặc tả)."""
from datetime import date, timedelta

import pytest

from app import permissions as perm
from app.extensions import db
from app.models import Notification, Project, ProjectTemplate, Task, User
from app.services import apply_template, create_project, create_task
from app.workflow import WorkflowError, transition
from tests.conftest import login


# ---------------------------------------------------------------- Đăng nhập
def test_login_and_lockout(app):
    c = app.test_client()
    assert login(c, "vy.nmt", "sai").status_code == 200
    for _ in range(4):
        login(c, "vy.nmt", "sai")
    r = login(c, "vy.nmt")  # đúng mật khẩu nhưng đang bị khóa
    assert r.status_code == 429


def test_force_password_change(app, users):
    users["vu.th"].must_change_password = True
    db.session.commit()
    c = app.test_client()
    login(c, "vu.th")
    r = c.get("/")
    assert r.status_code == 302 and "/change-password" in r.location
    r = c.post("/change-password", data={"old_password": "matkhau123", "new_password": "MatKhauMoi9",
                                         "confirm_password": "MatKhauMoi9"})
    assert r.status_code == 302
    assert c.get("/").status_code == 200


# ---------------------------------------------------------------- Mẫu dự án
def test_template_creates_tasks_with_correct_due_dates(app, users):
    mgr = users["tien.htq"]
    tpl = ProjectTemplate.query.filter_by(type="launch").first()
    p = create_project(mgr, name="Thử mẫu", type_="launch", department_id=mgr.department_id)
    start = date(2026, 11, 2)
    tasks = apply_template(p, tpl, start, mgr)
    db.session.commit()
    assert len(tasks) == len(tpl.items) == 10
    for t, item in zip(tasks, tpl.items):
        assert t.due_date == start + timedelta(days=item["offset_due"])
        assert t.assignee_id == mgr.id
    assert p.due_date == start + timedelta(days=60)


# ---------------------------------------------------------------- Phân quyền
def test_staff_cannot_see_tasks_outside_scope(app, users, client_as):
    kd = users["tien.nm"]
    secret = create_task(kd, "Việc riêng phòng KD", users["qui.nmn"], date.today(), notify_assignee=False)
    db.session.commit()
    c = client_as("vu.th")  # Thiết kế, Phòng Marketing
    assert c.get(f"/tasks/{secret.id}").status_code == 404
    assert c.post(f"/api/tasks/{secret.id}/move", json={"status": "in_progress"}).status_code == 404
    # Trưởng phòng Kinh doanh và Giám đốc khối xem được
    assert client_as("tien.nm").get(f"/tasks/{secret.id}").status_code == 200
    assert client_as("thinh.lv").get(f"/tasks/{secret.id}").status_code == 200
    # Trưởng phòng Marketing thì không
    assert client_as("tien.htq").get(f"/tasks/{secret.id}").status_code == 404


def test_project_member_sees_project_tasks(app, users):
    p = Project.query.filter_by(name="Mở thị trường Campuchia").first()
    vu = users["vu.th"]  # thành viên dự án dù thuộc Phòng Marketing
    assert perm.can_view_project(vu, p)
    t = p.tasks.first()
    assert perm.can_view_task(vu, t)
    assert not perm.can_view_project(users["diep.mtn"], p)


def test_assign_scope(app, users):
    assert perm.can_assign_to(users["tien.nm"], users["qui.nmn"])
    assert not perm.can_assign_to(users["tien.nm"], users["vu.th"])
    assert perm.can_assign_to(users["thinh.lv"], users["vu.th"])
    assert not perm.can_assign_to(users["diep.mtn"], users["qui.nmn"])
    assert perm.can_assign_to(users["diep.mtn"], users["diep.mtn"])


def test_direct_manager(app, users):
    assert perm.direct_manager(users["qui.nmn"]).username == "tien.nm"
    assert perm.direct_manager(users["vu.th"]).username == "tien.htq"
    assert perm.direct_manager(users["tien.nm"]).username == "thinh.lv"


# ---------------------------------------------------------------- Quy trình
@pytest.fixture()
def review_task(app, users):
    t = create_task(users["tien.htq"], "Thiết kế banner", users["vu.th"], date.today() + timedelta(days=3),
                    needs_review=True, notify_assignee=False)
    db.session.commit()
    return t


def test_needs_review_cannot_jump_to_done(app, users, review_task):
    vu = users["vu.th"]
    transition(review_task, "in_progress", vu)
    with pytest.raises(WorkflowError):
        transition(review_task, "done", vu)


def test_kanban_blocks_jump_to_done(app, users, review_task, client_as):
    c = client_as("vu.th")
    assert c.post(f"/api/tasks/{review_task.id}/move", json={"status": "in_progress"}).json["ok"]
    r = c.post(f"/api/tasks/{review_task.id}/move", json={"status": "done"})
    assert r.status_code == 400 and "duyệt" in r.json["error"]
    assert db.session.get(Task, review_task.id).status == "in_progress"


def test_full_review_cycle_and_notifications(app, users, review_task):
    vu, mgr = users["vu.th"], users["tien.htq"]
    transition(review_task, "in_progress", vu)
    transition(review_task, "review", vu)
    assert Notification.query.filter_by(user_id=mgr.id, type="task_review").count() == 1
    with pytest.raises(WorkflowError):  # người phụ trách không tự duyệt
        transition(review_task, "done", vu)
    with pytest.raises(WorkflowError):  # yêu cầu sửa phải có nhận xét
        transition(review_task, "revision", mgr)
    transition(review_task, "revision", mgr, "Đổi màu nền")
    assert Notification.query.filter_by(user_id=vu.id, type="task_revision").count() == 1
    transition(review_task, "review", vu)
    transition(review_task, "done", mgr)
    assert review_task.status == "done" and review_task.completed_at is not None


def test_checklist_and_subtasks_block_done(app, users):
    nm = users["tien.nm"]
    t = create_task(nm, "Báo giá", users["qui.nmn"], date.today(), checklist=["Bước 1"], notify_assignee=False)
    db.session.commit()
    transition(t, "in_progress", users["qui.nmn"])
    with pytest.raises(WorkflowError):
        transition(t, "done", users["qui.nmn"])
    t.checklist[0].is_done = True
    sub = create_task(nm, "Việc con", users["qui.nmn"], date.today(), parent=t, notify_assignee=False)
    with pytest.raises(WorkflowError):
        transition(t, "done", users["qui.nmn"])
    transition(sub, "in_progress", users["qui.nmn"])
    transition(sub, "done", users["qui.nmn"])
    transition(t, "done", users["qui.nmn"])
    with pytest.raises(ValueError):
        create_task(nm, "Cháu", users["qui.nmn"], date.today(), parent=sub)


def test_due_change_needs_reason_second_time(app, users, client_as):
    t = create_task(users["tien.nm"], "Đối soát", users["qui.nmn"], date.today(), notify_assignee=False)
    db.session.commit()
    c = client_as("qui.nmn")
    d1 = (date.today() + timedelta(days=2)).isoformat()
    d2 = (date.today() + timedelta(days=4)).isoformat()
    assert c.post(f"/api/tasks/{t.id}/quick", json={"field": "due_date", "value": d1}).json["ok"]
    r = c.post(f"/api/tasks/{t.id}/quick", json={"field": "due_date", "value": d2})
    assert r.status_code == 400 and r.json["need_reason"]
    assert c.post(f"/api/tasks/{t.id}/quick",
                  json={"field": "due_date", "value": d2, "reason": "Chờ số liệu"}).json["ok"]


# ---------------------------------------------------------------- Tác vụ nền & Telegram
def test_daily_job_notifies_assignee_and_manager(app, users):
    t = create_task(users["tien.nm"], "Quá hạn", users["diep.mtn"], date.today() - timedelta(days=3),
                    notify_assignee=False)
    db.session.commit()
    from app.jobs import run_daily
    with app.test_request_context():
        res = run_daily()
    assert res["overdue"] >= 1
    assert Notification.query.filter_by(user_id=users["diep.mtn"].id, type="task_overdue").count() >= 1
    assert Notification.query.filter_by(user_id=users["tien.nm"].id, type="team_overdue").count() == 1
    assert t.days_overdue == 3


def test_telegram_link_flow(app, users, client_as, monkeypatch):
    app.config.update(TELEGRAM_BOT_TOKEN="x", TELEGRAM_BOT_USERNAME="zhipat_bot", TELEGRAM_WEBHOOK_SECRET="s3cret")
    sent = []
    monkeypatch.setattr("app.views.api.send_telegram", lambda chat, text: sent.append((chat, text)) or "sent")
    c = client_as("vy.nmt")
    r = c.post("/profile/telegram/connect")
    assert r.status_code == 302 and r.location.startswith("https://t.me/zhipat_bot?start=")
    token = r.location.split("start=")[1]
    anon = app.test_client()
    body = {"message": {"text": f"/start {token}", "chat": {"id": 123456}}}
    assert anon.post("/api/telegram/webhook/sai", json=body).status_code == 404
    assert anon.post("/api/telegram/webhook/s3cret", json=body,
                     headers={"X-Telegram-Bot-Api-Secret-Token": "sai"}).status_code == 403
    r = anon.post("/api/telegram/webhook/s3cret", json=body, headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert r.status_code == 200
    assert db.session.get(User, users["vy.nmt"].id).telegram_chat_id == "123456"
    assert sent and sent[0][0] == "123456"


# ---------------------------------------------------------------- Màn hình chính
@pytest.mark.parametrize("username", ["thinh.lv", "tien.nm", "tien.htq", "vy.nmt", "admin"])
def test_pages_render(app, client_as, username):
    c = client_as(username)
    p = Project.query.first()
    t = Task.query.first()
    pages = ["/", "/tasks/my", "/tasks/", "/tasks/?view=kanban", "/projects/", "/notifications", "/profile",
             "/tasks/new"]
    me = User.query.filter_by(username=username).first()
    if perm.can_view_project(me, p):
        pages += [f"/projects/{p.id}?view={v}" for v in ("list", "kanban", "timeline", "members", "info")]
        pages.append(f"/tasks/{t.id}")
        expected_edit = 200 if perm.can_edit_task(me, t) else 403
        assert c.get(f"/tasks/{t.id}/edit").status_code == expected_edit
    if username == "admin":
        pages += ["/admin/users", "/admin/departments", "/admin/templates", "/admin/templates/1", "/admin/users/new"]
    for url in pages:
        r = c.get(url)
        assert r.status_code == 200, (url, r.status_code)


def test_create_project_and_task_via_forms(app, users, client_as):
    c = client_as("tien.htq")
    tpl = ProjectTemplate.query.filter_by(type="trade_show").first()
    r = c.post("/projects/new", data={"name": "Hội chợ EICMA 2026", "type": "trade_show", "template_id": tpl.id,
                                      "start_date": "2026-10-05", "department_id": users["tien.htq"].department_id,
                                      "owner_id": users["tien.htq"].id})
    assert r.status_code == 302
    p = Project.query.filter_by(name="Hội chợ EICMA 2026").first()
    assert p.tasks.count() == 9
    r = c.post("/tasks/new", data={"title": "In standee", "assignee_id": users["vu.th"].id,
                                   "due_date": "2026-10-20", "project_id": p.id, "needs_review": "1"})
    assert r.status_code == 302
    t = Task.query.filter_by(title="In standee").first()
    assert t.needs_review and t.assignee_id == users["vu.th"].id
    assert Notification.query.filter_by(user_id=users["vu.th"].id, type="task_assigned").count() >= 1
    # Nhân viên không tạo được dự án, không giao việc ngoài phạm vi
    s = client_as("diep.mtn")
    assert s.get("/projects/new").status_code == 403
    r = s.post("/tasks/new", data={"title": "x", "assignee_id": users["vu.th"].id, "due_date": "2026-10-20"})
    assert r.status_code == 400


def test_scheduler_runs_each_job_once_per_day(app, users):
    from datetime import datetime
    from app.scheduler import tick
    create_task(users["tien.nm"], "Trễ", users["diep.mtn"], date.today() - timedelta(days=1), notify_assignee=False)
    db.session.commit()
    assert tick(app, datetime(2026, 10, 9, 7, 30)) == []           # trước 8:00
    assert tick(app, datetime(2026, 10, 9, 8, 1)) == ["daily"]      # thứ Sáu 8:01
    assert tick(app, datetime(2026, 10, 9, 9, 0)) == []             # đã chạy hôm nay
    assert tick(app, datetime(2026, 10, 9, 17, 5)) == ["weekly"]    # thứ Sáu 17:05
    assert tick(app, datetime(2026, 10, 10, 8, 0)) == ["daily"]     # ngày hôm sau


def test_healthz_and_issue_passwords(app, client_as):
    assert app.test_client().get("/healthz").json["ok"]
    c = client_as("admin")
    r = c.post("/admin/users/issue-passwords")
    assert r.status_code == 200 and "vy.nmt" in r.get_data(as_text=True)
