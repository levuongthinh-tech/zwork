from app import create_app

app = create_app()

# Bộ hẹn giờ chỉ bật trong tiến trình web (không bật khi chạy lệnh `flask seed`, `flask jobs`...)
if app.config.get("ENABLE_SCHEDULER"):
    from app.scheduler import start_scheduler
    start_scheduler(app)

if __name__ == "__main__":
    app.run(debug=True)
