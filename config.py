import os
from pathlib import Path

import time

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Giờ Việt Nam cho mọi phép tính "hôm nay", "quá hạn"
os.environ.setdefault("TZ", "Asia/Ho_Chi_Minh")
if hasattr(time, "tzset"):
    time.tzset()

# Railway tự cung cấp đường dẫn ổ lưu trữ (Volume) qua biến này
DATA_DIR = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or os.environ.get("DATA_DIR") or str(BASE_DIR / "instance")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or f"sqlite:///{Path(DATA_DIR) / 'zhipat_work.db'}"
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 15}}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DATA_DIR = DATA_DIR
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or str(Path(DATA_DIR) / "uploads")
    ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "0") == "1"
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB / tệp
    ALLOWED_EXTENSIONS = {
        "png", "jpg", "jpeg", "gif", "webp", "pdf", "doc", "docx", "xls", "xlsx",
        "ppt", "pptx", "txt", "csv", "zip", "ai", "psd", "mp4", "mov",
    }

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    REMEMBER_COOKIE_HTTPONLY = True

    # Đăng nhập
    LOGIN_MAX_FAILS = 5
    LOGIN_LOCK_MINUTES = 15

    # Telegram bot (để trống = chỉ thông báo trong app)
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "")  # không có @
    TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

    # Phê duyệt ngân sách: Trưởng phòng duyệt đến hạn mức này, cao hơn chuyển Giám đốc Khối
    BUDGET_LIMIT_MANAGER = int(os.environ.get("BUDGET_LIMIT_MANAGER", "10000000"))

    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
    APP_NAME = "ZHI.PAT Work"


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    ENABLE_SCHEDULER = False
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test"
