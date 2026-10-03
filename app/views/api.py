"""API JSON cho thao tác nhanh (Kanban kéo-thả, đổi người/hạn/ưu tiên) và webhook Telegram."""
import hmac

from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required

from .. import permissions as perm
from ..extensions import csrf, db
from ..models import PRIORITIES, Task, User
from ..notify import notify, send_telegram
from ..services import get_user, log_activity, parse_date, task_link
from ..workflow import WorkflowError, transition

bp = Blueprint("api", __name__, url_prefix="/api")


def _task(task_id):
    t = db.session.get(Task, task_id)
    if not t or not perm.can_view_task(current_user, t):
        abort(404)
    return t


@bp.route("/tasks/<int:task_id>/move", methods=["POST"])
@login_required
def move(task_id):
    """Kéo-thả Kanban: đổi trạng thái (qua workflow) và/hoặc vị trí."""
    t = _task(task_id)
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    try:
        if status and status != t.status:
            transition(t, status, current_user, data.get("note"))
        if "position" in data and perm.can_edit_task(current_user, t):
            t.position = float(data["position"])
        db.session.commit()
    except WorkflowError as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e), status=t.status), 400
    return jsonify(ok=True, status=t.status, label=t.status_label)


@bp.route("/tasks/<int:task_id>/quick", methods=["POST"])
@login_required
def quick(task_id):
    """Thao tác nhanh trên danh sách: priority, due_date, assignee_id."""
    t = _task(task_id)
    if not perm.can_edit_task(current_user, t):
        return jsonify(ok=False, error="Bạn không có quyền sửa việc này."), 403
    data = request.get_json(silent=True) or {}
    field, value = data.get("field"), data.get("value")
    if field == "priority" and value in PRIORITIES:
        t.priority = value
    elif field == "due_date":
        d = parse_date(value)
        if not d:
            return jsonify(ok=False, error="Ngày không hợp lệ."), 400
        if t.due_changes >= 1 and not (data.get("reason") or "").strip():
            return jsonify(ok=False, need_reason=True,
                           error="Lần dời hạn thứ 2 trở lên cần ghi lý do."), 400
        log_activity("task", t.id, current_user, "updated",
                     {"due_date": {"from": t.due_date, "to": d, "reason": data.get("reason", "")}})
        t.due_changes = (t.due_changes or 0) + 1
        t.due_date = d
    elif field == "assignee_id":
        if not perm.is_task_manager(current_user, t):
            return jsonify(ok=False, error="Chỉ người giao việc hoặc quản lý được đổi người phụ trách."), 403
        u = get_user(value)
        if not u or not perm.can_assign_to(current_user, u, t.project):
            return jsonify(ok=False, error="Bạn không được giao việc cho người này."), 403
        t.assignee_id, t.department_id = u.id, u.department_id or t.department_id
        log_activity("task", t.id, current_user, "updated", {"assignee": u.full_name})
        notify(u, "task_assigned", f"Việc mới: {t.title}", f"Giao bởi {current_user.full_name}",
               task_link(t), push=True, actor=current_user)
    else:
        return jsonify(ok=False, error="Trường không hợp lệ."), 400
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/telegram/webhook/<secret>", methods=["POST"])
@csrf.exempt
def telegram_webhook(secret):
    """Nhận /start <mã> từ Telegram để gắn chat_id vào tài khoản."""
    expected = current_app.config.get("TELEGRAM_WEBHOOK_SECRET") or ""
    if not expected or not hmac.compare_digest(secret, expected):
        abort(404)
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(header, expected):
        abort(403)
    upd = request.get_json(silent=True) or {}
    msg = upd.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = str((msg.get("chat") or {}).get("id") or "")
    if not chat_id:
        return jsonify(ok=True)
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        token = parts[1].strip() if len(parts) > 1 else ""
        user = User.query.filter_by(telegram_link_token=token).first() if token else None
        if user:
            user.telegram_chat_id = chat_id
            user.telegram_link_token = None
            db.session.commit()
            send_telegram(chat_id, f"Xin chào <b>{user.full_name}</b>! Bạn sẽ nhận thông báo công việc tại đây.")
        else:
            send_telegram(chat_id, "Mã kết nối không hợp lệ hoặc đã hết hạn. "
                                   "Hãy bấm \"Kết nối Telegram\" trong Hồ sơ cá nhân trên hệ thống.")
    return jsonify(ok=True)
