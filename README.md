# ZHI.PAT Work – Hệ thống giao việc Khối Kinh doanh

Giai đoạn 1: đăng nhập & phân quyền, dự án (tạo từ mẫu), giao việc, việc con, checklist, bình luận @nhắc tên,
tệp đính kèm, quy trình duyệt, Kanban kéo-thả, Timeline, dashboard, thông báo trong app + Telegram, quản trị.

Stack: Python 3.11+, Flask 3, SQLAlchemy, SQLite (đổi sang PostgreSQL bằng `DATABASE_URL`).

## Chạy trên máy

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # sửa SECRET_KEY, để FLASK_ENV=development khi chạy thử
flask --app wsgi seed            # tạo cơ cấu, 8 nhân sự, tài khoản admin, 4 mẫu dự án
flask --app wsgi seed --demo     # (tùy chọn) thêm 2 dự án mẫu để dùng thử
flask --app wsgi run
```

Mở http://localhost:5000. Mật khẩu tạm của từng người nằm ở `instance/mat_khau_ban_dau.csv`;
mỗi người phải đổi mật khẩu ở lần đăng nhập đầu. Xóa tệp này sau khi đã phát mật khẩu.

| Tên đăng nhập | Họ tên | Vai trò |
| --- | --- | --- |
| thinh.lv | Lê Vương Thịnh | Giám đốc Khối |
| tien.nm | Nguyễn Minh Tiến | Trưởng phòng Kinh doanh |
| vy.nmt | Nguyễn Mộng Tường Vy | Nhân viên |
| huy.nm | Nguyễn Minh Huy | Nhân viên |
| qui.nmn | Nguyễn Mai Như Quí | Nhân viên |
| diep.mtn | Mai Thị Ngọc Diệp | Nhân viên |
| tien.htq | Hà Thanh Quốc Tiến | Trưởng phòng Marketing |
| vu.th | Trần Hùng Vũ | Nhân viên |
| admin | Quản trị hệ thống | Quản trị |

## Kiểm thử

```bash
pytest -q
```

20 bài test bao phủ tiêu chí nghiệm thu GĐ1: phân quyền theo phạm vi, chặn chuyển trạng thái sai quy trình
(kể cả kéo-thả Kanban), chu trình duyệt, lý do dời hạn, nhắc quá hạn, kết nối Telegram, tạo dự án từ mẫu.

## Triển khai Railway

1. Tạo service từ repo, thêm **Volume** mount tại `/data`.
2. Đặt biến môi trường theo `.env.example` (`SECRET_KEY`, `APP_BASE_URL` = tên miền riêng,
   `DATABASE_URL=sqlite:////data/zhipat_work.db`, `UPLOAD_FOLDER=/data/uploads`, `SESSION_COOKIE_SECURE=1`).
3. Sau lần deploy đầu: `railway run flask --app wsgi seed`.
4. Thêm 2 Cron job (giờ UTC, Việt Nam = UTC+7):
   - `0 1 * * *` → `flask --app wsgi jobs daily` (8:00 sáng: nhắc sắp đến hạn, quá hạn)
   - `0 10 * * 5` → `flask --app wsgi jobs weekly` (17:00 thứ Sáu: tổng hợp tuần)
5. Trỏ tên miền riêng vào service (Settings → Domains).

## Kết nối Telegram

1. Chat với **@BotFather** trên Telegram → `/newbot` → đặt tên (ví dụ `ZHIPAT Work Bot`) → nhận token.
2. Đặt biến `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` (không có @), `TELEGRAM_WEBHOOK_SECRET`
   (chuỗi ngẫu nhiên chỉ gồm chữ, số, gạch dưới).
3. Chạy một lần: `flask --app wsgi telegram-setup` để đăng ký webhook.
4. Mỗi nhân viên vào **Hồ sơ → Kết nối Telegram**, bấm Start trong bot. Xong.

Chưa cấu hình bot thì hệ thống vẫn chạy, chỉ có thông báo trong app.

## Cấu trúc mã

```
app/
  models.py        12 bảng GĐ1
  permissions.py   phạm vi dữ liệu theo vai trò (mọi truy vấn đi qua đây)
  workflow.py      quy tắc chuyển trạng thái (nơi duy nhất đổi Task.status)
  notify.py        thông báo trong app + Telegram
  services.py      sinh mã, tạo việc, tạo dự án từ mẫu, nhắc tên
  jobs.py          tác vụ nền daily / weekly
  seed.py          cơ cấu, nhân sự, mẫu dự án
  views/           auth, main, tasks, projects, admin, api
  templates/ static/
tests/
```

## Việc tiếp theo (GĐ2)

Yêu cầu liên phòng, Phê duyệt ngân sách (Trưởng phòng ≤ 10 triệu, cao hơn Giám đốc Khối – tham số
`BUDGET_LIMIT_MANAGER` đã có sẵn), Công việc định kỳ, Lịch, Kho tài liệu.
