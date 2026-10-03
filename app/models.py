"""Mô hình dữ liệu ZHI.PAT Work – Giai đoạn 1 (xem Mục 3 tài liệu đặc tả)."""
import json
from datetime import date, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def now():
    return datetime.now()


# ---------------------------------------------------------------- Hằng số
ROLES = {
    "admin": "Quản trị",
    "director": "Giám đốc Khối",
    "manager": "Trưởng phòng",
    "leader": "Trưởng nhóm",
    "staff": "Nhân viên",
}
ROLE_RANK = {"staff": 1, "leader": 2, "manager": 3, "director": 4, "admin": 5}

DEPT_LEVELS = {"division": "Khối", "department": "Phòng", "team": "Nhóm"}

PROJECT_TYPES = {
    "launch": "Ra mắt sản phẩm",
    "trade_show": "Hội chợ / Triển lãm",
    "dealer_program": "Chương trình đại lý",
    "market_entry": "Mở thị trường",
    "campaign": "Chiến dịch marketing",
    "other": "Khác",
}
PROJECT_STATUSES = {
    "planning": "Đang lập kế hoạch",
    "active": "Đang thực hiện",
    "on_hold": "Tạm dừng",
    "done": "Hoàn thành",
    "cancelled": "Hủy",
}

TASK_STATUSES = {
    "new": "Mới",
    "in_progress": "Đang làm",
    "review": "Chờ duyệt",
    "revision": "Cần sửa",
    "done": "Hoàn thành",
    "paused": "Tạm dừng",
    "cancelled": "Hủy",
}
KANBAN_COLUMNS = ["new", "in_progress", "review", "revision", "done"]
OPEN_STATUSES = ("new", "in_progress", "review", "revision", "paused")

PRIORITIES = {"low": "Thấp", "normal": "Bình thường", "high": "Cao", "urgent": "Gấp"}
PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


# ---------------------------------------------------------------- Tổ chức
class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(30), unique=True)
    level = db.Column(db.String(20), nullable=False, default="team")
    parent_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    created_at = db.Column(db.DateTime, default=now)

    parent = db.relationship("Department", remote_side=[id], backref="children")

    def descendant_ids(self):
        ids = [self.id]
        for c in self.children:
            ids.extend(c.descendant_ids())
        return ids

    @property
    def full_name(self):
        return f"{self.parent.name} › {self.name}" if self.parent and self.level == "team" else self.name

    def __repr__(self):
        return f"<Dept {self.code}>"


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(60), unique=True, nullable=False, index=True)
    email = db.Column(db.String(160), unique=True, index=True)
    phone = db.Column(db.String(30))
    telegram_chat_id = db.Column(db.String(64))
    telegram_link_token = db.Column(db.String(64), unique=True)
    title = db.Column(db.String(120))
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20), nullable=False, default="staff")
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    is_active_flag = db.Column("is_active", db.Boolean, default=True, nullable=False)
    failed_logins = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now)

    department = db.relationship("Department", backref="users")

    @property
    def is_active(self):
        return bool(self.is_active_flag)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def rank(self):
        return ROLE_RANK.get(self.role, 1)

    @property
    def role_label(self):
        return ROLES.get(self.role, self.role)

    @property
    def initials(self):
        parts = self.full_name.split()
        return (parts[-1][0] if parts else "?").upper()

    def __repr__(self):
        return f"<User {self.username}>"


# ---------------------------------------------------------------- Dự án
class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    type = db.Column(db.String(30), default="other")
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    goal_id = db.Column(db.Integer)  # GĐ3
    status = db.Column(db.String(20), default="planning")
    start_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    budget = db.Column(db.Float, default=0)
    spent = db.Column(db.Float, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=now)

    department = db.relationship("Department")
    owner = db.relationship("User", foreign_keys=[owner_id])
    members = db.relationship("ProjectMember", backref="project", cascade="all, delete-orphan")
    tasks = db.relationship("Task", backref="project", lazy="dynamic")

    @property
    def top_tasks(self):
        return self.tasks.filter(Task.parent_id.is_(None), Task.status != "cancelled")

    @property
    def progress(self):
        total = self.top_tasks.count()
        if not total:
            return 0
        done = self.top_tasks.filter(Task.status == "done").count()
        return round(done * 100 / total)

    @property
    def overdue_count(self):
        return self.tasks.filter(Task.status.in_(OPEN_STATUSES), Task.due_date < date.today()).count()

    def member_ids(self):
        return {m.user_id for m in self.members} | ({self.owner_id} if self.owner_id else set())


class ProjectMember(db.Model):
    __tablename__ = "project_members"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    member_role = db.Column(db.String(20), default="member")
    created_at = db.Column(db.DateTime, default=now)

    user = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("project_id", "user_id"),)


class ProjectTemplate(db.Model):
    __tablename__ = "project_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(30), default="other")
    description = db.Column(db.Text)
    # [{"title":..., "offset_start":0, "offset_due":7, "priority":"normal", "needs_review":true, "checklist":[...]}]
    tasks_json = db.Column(db.Text, default="[]")
    created_at = db.Column(db.DateTime, default=now)

    @property
    def items(self):
        try:
            return json.loads(self.tasks_json or "[]")
        except ValueError:
            return []


# ---------------------------------------------------------------- Công việc
task_watchers = db.Table(
    "task_watchers",
    db.Column("task_id", db.Integer, db.ForeignKey("tasks.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)


class Task(db.Model):
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), index=True)
    priority = db.Column(db.String(10), default="normal")
    status = db.Column(db.String(20), default="new", index=True)
    start_date = db.Column(db.Date)
    due_date = db.Column(db.Date, index=True)
    completed_at = db.Column(db.DateTime)
    estimate_hours = db.Column(db.Float)
    needs_review = db.Column(db.Boolean, default=False)
    due_changes = db.Column(db.Integer, default=0)
    source = db.Column(db.String(20), default="manual")
    source_id = db.Column(db.Integer)
    position = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=now)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)

    assignee = db.relationship("User", foreign_keys=[assignee_id])
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    department = db.relationship("Department")
    parent = db.relationship("Task", remote_side=[id], backref=db.backref("subtasks", order_by="Task.id"))
    watchers = db.relationship("User", secondary=task_watchers, lazy="subquery")
    checklist = db.relationship("ChecklistItem", backref="task", cascade="all, delete-orphan",
                                order_by="ChecklistItem.position")
    comments = db.relationship("Comment", backref="task", cascade="all, delete-orphan",
                               order_by="Comment.created_at")
    attachments = db.relationship("Attachment", backref="task", cascade="all, delete-orphan")

    @property
    def status_label(self):
        return TASK_STATUSES.get(self.status, self.status)

    @property
    def priority_label(self):
        return PRIORITIES.get(self.priority, self.priority)

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def days_overdue(self):
        if self.due_date and self.is_open and self.due_date < date.today():
            return (date.today() - self.due_date).days
        return 0

    @property
    def checklist_done(self):
        return sum(1 for c in self.checklist if c.is_done)

    def __repr__(self):
        return f"<Task {self.code}>"


class ChecklistItem(db.Model):
    __tablename__ = "checklist_items"
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False)
    content = db.Column(db.String(255), nullable=False)
    is_done = db.Column(db.Boolean, default=False)
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=now)


class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=now)

    user = db.relationship("User")


class Attachment(db.Model):
    __tablename__ = "attachments"
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(255), nullable=False)
    size = db.Column(db.Integer)
    mime = db.Column(db.String(120))
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=now)

    uploader = db.relationship("User")


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(30), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(50), nullable=False)
    detail_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now)

    user = db.relationship("User")

    @property
    def detail(self):
        try:
            return json.loads(self.detail_json or "{}")
        except ValueError:
            return {}


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    type = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text)
    link = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False, index=True)
    push_status = db.Column(db.String(20), default="skipped")
    created_at = db.Column(db.DateTime, default=now)


class JobRun(db.Model):
    """Ghi lại lần chạy gần nhất của tác vụ nền để không chạy trùng."""
    __tablename__ = "job_runs"
    key = db.Column(db.String(40), primary_key=True)
    last_run_on = db.Column(db.String(20))
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)
