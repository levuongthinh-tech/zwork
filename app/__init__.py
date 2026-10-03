import os
from datetime import date, datetime

from flask import Flask, render_template

from config import Config
from .extensions import csrf, db, login_manager
from .models import PRIORITIES, PROJECT_STATUSES, PROJECT_TYPES, ROLES, TASK_STATUSES, Notification, User


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    if app.config.get("DATA_DIR"):
        os.makedirs(app.config["DATA_DIR"], exist_ok=True)

    if not app.config.get("TESTING") and app.config["SECRET_KEY"] == "dev-only-change-me" \
            and os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("Chưa đặt SECRET_KEY cho môi trường production.")

    db.init_app(app)
    with app.app_context():
        if db.engine.url.get_backend_name() == "sqlite":
            from sqlalchemy import event

            @event.listens_for(db.engine, "connect")
            def _sqlite_pragmas(conn, _):
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA busy_timeout=15000")
                cur.close()
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        u = db.session.get(User, int(user_id))
        return u if u and u.is_active else None

    from .views.admin import bp as admin_bp
    from .views.api import bp as api_bp
    from .views.auth import bp as auth_bp
    from .views.main import bp as main_bp
    from .views.projects import bp as projects_bp
    from .views.tasks import bp as tasks_bp

    for bp in (auth_bp, main_bp, tasks_bp, projects_bp, admin_bp, api_bp):
        app.register_blueprint(bp)

    register_template_helpers(app)
    register_cli(app)

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="Bạn không có quyền truy cập nội dung này."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Không tìm thấy trang hoặc dữ liệu."), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("error.html", code=413, message="Tệp quá lớn (tối đa 20 MB)."), 413

    @app.route("/healthz")
    def healthz():
        db.session.execute(db.text("SELECT 1"))
        return {"ok": True, "local_time": datetime.now().strftime("%Y-%m-%d %H:%M"), "tz": os.environ.get("TZ")}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    with app.app_context():
        db.create_all()
    return app


def register_template_helpers(app):
    @app.template_filter("d")
    def fmt_date(value):
        if not value:
            return ""
        return value.strftime("%d/%m/%Y") if isinstance(value, (date, datetime)) else str(value)

    @app.template_filter("dt")
    def fmt_datetime(value):
        return value.strftime("%H:%M %d/%m/%Y") if value else ""

    @app.template_filter("money")
    def fmt_money(value):
        try:
            return f"{float(value or 0):,.0f}".replace(",", ".") + " ₫"
        except (TypeError, ValueError):
            return ""

    @app.template_filter("iso")
    def fmt_iso(value):
        return value.isoformat() if value else ""

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        unread = 0
        if current_user.is_authenticated:
            unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        return dict(
            APP_NAME=app.config["APP_NAME"], TASK_STATUSES=TASK_STATUSES, PRIORITIES=PRIORITIES,
            PROJECT_TYPES=PROJECT_TYPES, PROJECT_STATUSES=PROJECT_STATUSES, ROLES=ROLES,
            unread_count=unread, today=date.today(),
        )


def register_cli(app):
    import click

    @app.cli.command("seed")
    @click.option("--demo", is_flag=True, help="Tạo thêm nhân sự và dự án mẫu để dùng thử.")
    def seed_cmd(demo):
        """Khởi tạo cơ cấu, tài khoản quản trị, mẫu dự án."""
        from .seed import run_seed
        run_seed(demo=demo)

    @app.cli.command("jobs")
    @click.argument("name", type=click.Choice(["daily", "weekly"]))
    def jobs_cmd(name):
        """Tác vụ nền: daily = nhắc hạn & quá hạn (8:00), weekly = tổng hợp tuần (17:00 thứ Sáu)."""
        from .jobs import run_daily, run_weekly
        with app.test_request_context(base_url=app.config["APP_BASE_URL"]):
            result = run_daily() if name == "daily" else run_weekly()
        click.echo(result)

    @app.cli.command("create-user")
    @click.option("--username", required=True)
    @click.option("--name", required=True)
    @click.option("--role", default="staff", type=click.Choice(list(ROLES)))
    @click.password_option()
    def create_user_cmd(username, name, role, password):
        u = User(username=username.lower().strip(), full_name=name, role=role, must_change_password=False)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Đã tạo {username}")

    @app.cli.command("telegram-setup")
    def telegram_setup_cmd():
        """Đăng ký webhook Telegram: {APP_BASE_URL}/api/telegram/webhook/{TELEGRAM_WEBHOOK_SECRET}."""
        from .notify import telegram_api
        secret = app.config.get("TELEGRAM_WEBHOOK_SECRET")
        if not (app.config.get("TELEGRAM_BOT_TOKEN") and secret):
            raise click.ClickException("Cần đặt TELEGRAM_BOT_TOKEN và TELEGRAM_WEBHOOK_SECRET.")
        url = f"{app.config['APP_BASE_URL'].rstrip('/')}/api/telegram/webhook/{secret}"
        click.echo(telegram_api("setWebhook", {"url": url, "secret_token": secret,
                                               "allowed_updates": ["message"]}))
