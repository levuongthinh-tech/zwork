"""Thông báo trong app + Telegram bot (Mục 4.3 tài liệu đặc tả).

Khi chưa cấu hình TELEGRAM_BOT_TOKEN, hệ thống vẫn chạy và chỉ tạo thông báo trong app.
Nhân viên kết nối Telegram một lần qua nút trong Hồ sơ cá nhân (xem views/telegram.py).
"""
import html
import logging

import requests
from flask import current_app

from .extensions import db
from .models import Notification

log = logging.getLogger(__name__)


def telegram_api(method, payload):
    token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    resp = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=8)
    return resp.json() if resp.content else {}


def send_telegram(chat_id, text):
    """Trả về 'sent' | 'failed' | 'skipped'."""
    if not current_app.config.get("TELEGRAM_BOT_TOKEN") or not chat_id:
        return "skipped"
    try:
        data = telegram_api("sendMessage", {
            "chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        if data and data.get("ok"):
            return "sent"
        log.warning("Telegram lỗi: %s", data)
        return "failed"
    except Exception as exc:  # lỗi mạng không được làm hỏng thao tác chính
        log.warning("Không gửi được Telegram: %s", exc)
        return "failed"


def format_message(title, body="", link=""):
    app_name = current_app.config["APP_NAME"]
    text = f"<b>{html.escape(title)}</b>"
    if body:
        text += f"\n{html.escape(body)}"
    if link:
        url = current_app.config.get("APP_BASE_URL", "").rstrip("/") + link
        text += f'\n<a href="{html.escape(url, quote=True)}">Mở trong {html.escape(app_name)}</a>'
    return text


def notify(user, type_, title, body="", link="", push=False, actor=None):
    """Tạo thông báo cho user. Không tự gửi cho chính người thao tác."""
    if user is None or not user.is_active:
        return None
    if actor is not None and actor.id == user.id:
        return None
    n = Notification(user_id=user.id, type=type_, title=title, body=body or "", link=link or "")
    if push:
        n.push_status = send_telegram(user.telegram_chat_id, format_message(title, body, link))
    db.session.add(n)
    return n


def notify_many(users, *args, **kwargs):
    seen = set()
    for u in users:
        if u is not None and u.id not in seen:
            seen.add(u.id)
            notify(u, *args, **kwargs)
