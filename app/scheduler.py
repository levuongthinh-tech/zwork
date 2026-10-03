"""Bộ hẹn giờ chạy ngay trong ứng dụng (thay cho cron riêng, vì SQLite nằm trên Volume chỉ gắn được 1 service).

- daily:  8:00 sáng mỗi ngày (giờ Việt Nam) – nhắc sắp đến hạn, quá hạn
- weekly: 17:00 thứ Sáu – tổng hợp tuần cho Trưởng phòng, Giám đốc Khối

Khóa tệp (fcntl) đảm bảo chỉ một tiến trình chạy bộ hẹn giờ; bảng job_runs đảm bảo mỗi mốc chỉ chạy một lần,
kể cả khi ứng dụng khởi động lại sau giờ hẹn trong cùng ngày.
"""
import logging
import os
import threading
import time
from datetime import datetime

log = logging.getLogger(__name__)

SCHEDULE = [
    # (key, kiểm tra thời điểm, tên hàm)
    ("daily", lambda now: now.hour >= 8, "run_daily"),
    ("weekly", lambda now: now.weekday() == 4 and now.hour >= 17, "run_weekly"),
]

_started = False


def _acquire_lock(path):
    try:
        import fcntl
    except ImportError:  # Windows khi chạy thử trên máy
        return object()
    fh = open(path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def tick(app, now=None):
    """Chạy các tác vụ đã đến giờ mà hôm nay chưa chạy. Trả về danh sách key đã chạy."""
    from . import jobs
    from .extensions import db
    from .models import JobRun

    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    ran = []
    with app.app_context(), app.test_request_context(base_url=app.config["APP_BASE_URL"]):
        for key, due, fn in SCHEDULE:
            if not due(now):
                continue
            row = db.session.get(JobRun, key)
            if row and row.last_run_on == today:
                continue
            try:
                result = getattr(jobs, fn)()
                row = row or JobRun(key=key)
                row.last_run_on = today
                db.session.add(row)
                db.session.commit()
                ran.append(key)
                log.info("Đã chạy tác vụ %s: %s", key, result)
            except Exception:
                db.session.rollback()
                log.exception("Tác vụ %s lỗi", key)
    return ran


def start_scheduler(app, interval=60):
    global _started
    if _started:
        return
    lock = _acquire_lock(os.path.join(app.config["DATA_DIR"], ".scheduler.lock"))
    if lock is None:
        return  # tiến trình khác đã giữ bộ hẹn giờ
    _started = True

    def loop():
        app._scheduler_lock = lock  # giữ tham chiếu để khóa không bị giải phóng
        while True:
            try:
                tick(app)
            except Exception:
                log.exception("Bộ hẹn giờ lỗi")
            time.sleep(interval)

    threading.Thread(target=loop, name="zhipat-scheduler", daemon=True).start()
    log.info("Đã bật bộ hẹn giờ tác vụ nền")
