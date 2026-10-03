"""Phạm vi dữ liệu và quyền thao tác theo vai trò (Mục 2 tài liệu đặc tả).

Mọi truy vấn danh sách công việc / dự án phải đi qua task_query_for / project_query_for
để nhân viên không xem được dữ liệu ngoài phạm vi, kể cả khi đoán đúng ID.
"""
from sqlalchemy import or_

from .extensions import db
from .models import Department, Project, ProjectMember, Task, User, task_watchers


# ---------------------------------------------------------------- Phạm vi phòng ban
def scope_department_ids(user):
    """None = toàn bộ; set() = không có phạm vi quản lý; ngược lại = tập id phòng/nhóm."""
    if user.role in ("admin", "director"):
        return None
    dept = user.department
    if not dept:
        return set()
    if user.role == "manager":
        root = dept.parent if dept.level == "team" and dept.parent else dept
        return set(root.descendant_ids())
    if user.role == "leader":
        return set(dept.descendant_ids())
    return set()


def is_manager_of(user, target):
    """user có quyền quản lý target (người dùng khác) không."""
    if user.id == target.id:
        return False
    scope = scope_department_ids(user)
    if scope is None:
        return True
    return bool(scope) and target.department_id in scope and user.rank > target.rank


def direct_manager(user):
    """Quản lý trực tiếp: người có vai trò cao hơn gần nhất trong cây phòng ban."""
    dept = user.department
    while dept:
        candidates = (User.query.filter(User.department_id == dept.id, User.is_active_flag.is_(True),
                                        User.id != user.id)
                      .all())
        higher = [u for u in candidates if u.rank > user.rank and u.role != "admin"]
        if higher:
            return min(higher, key=lambda u: u.rank)
        dept = dept.parent
    return User.query.filter_by(role="director", is_active_flag=True).first()


def assignable_users(user, project=None):
    """Danh sách người mà user được phép giao việc."""
    q = User.query.filter(User.is_active_flag.is_(True))
    scope = scope_department_ids(user)
    if scope is None:
        return q.order_by(User.full_name).all()
    ids = {user.id}
    if scope:
        ids |= {u.id for u in q.filter(User.department_id.in_(scope)).all()}
    if project is not None and user.id in project.member_ids():
        ids |= project.member_ids()
    return q.filter(User.id.in_(ids)).order_by(User.full_name).all()


def can_assign_to(user, target, project=None):
    if target is None:
        return False
    return target.id in {u.id for u in assignable_users(user, project)}


# ---------------------------------------------------------------- Công việc
def task_query_for(user):
    q = Task.query
    scope = scope_department_ids(user)
    if scope is None:
        return q
    member_project_ids = db.session.query(ProjectMember.project_id).filter(ProjectMember.user_id == user.id)
    owned_project_ids = db.session.query(Project.id).filter(Project.owner_id == user.id)
    watched = db.session.query(task_watchers.c.task_id).filter(task_watchers.c.user_id == user.id)
    conds = [
        Task.assignee_id == user.id,
        Task.created_by == user.id,
        Task.reviewer_id == user.id,
        Task.id.in_(watched),
        Task.project_id.in_(member_project_ids),
        Task.project_id.in_(owned_project_ids),
    ]
    if scope:
        conds.append(Task.department_id.in_(scope))
        conds.append(Task.assignee_id.in_(db.session.query(User.id).filter(User.department_id.in_(scope))))
    return q.filter(or_(*conds))


def can_view_task(user, task):
    return task_query_for(user).filter(Task.id == task.id).first() is not None


def is_task_manager(user, task):
    """Người tạo, quản lý của người phụ trách, hoặc quản lý dự án."""
    if user.role in ("admin", "director"):
        return True
    if task.created_by == user.id:
        return True
    if task.assignee and is_manager_of(user, task.assignee):
        return True
    if task.project and can_manage_project(user, task.project):
        return True
    return False


def can_edit_task(user, task):
    return is_task_manager(user, task) or task.assignee_id == user.id


def can_delete_task(user, task):
    if user.role in ("admin", "director"):
        return True
    if user.role == "staff":
        return task.created_by == user.id and task.status == "new"
    if task.created_by == user.id:
        return True
    return user.role == "manager" and task.assignee is not None and is_manager_of(user, task.assignee)


# ---------------------------------------------------------------- Dự án
def can_create_project(user):
    return user.rank >= 2


def project_query_for(user):
    q = Project.query
    scope = scope_department_ids(user)
    if scope is None:
        return q
    member_project_ids = db.session.query(ProjectMember.project_id).filter(ProjectMember.user_id == user.id)
    conds = [Project.owner_id == user.id, Project.created_by == user.id, Project.id.in_(member_project_ids)]
    if scope:
        conds.append(Project.department_id.in_(scope))
    return q.filter(or_(*conds))


def can_view_project(user, project):
    return project_query_for(user).filter(Project.id == project.id).first() is not None


def can_manage_project(user, project):
    if user.role in ("admin", "director"):
        return True
    if project.owner_id == user.id or project.created_by == user.id:
        return True
    scope = scope_department_ids(user)
    return bool(scope) and project.department_id in scope and user.rank >= 3


def project_departments_for(user):
    scope = scope_department_ids(user)
    q = Department.query.order_by(Department.id)
    if scope is None:
        return q.all()
    return q.filter(Department.id.in_(scope or {user.department_id})).all()
