"""Dữ liệu khởi tạo: cơ cấu Khối Kinh doanh, nhân sự, tài khoản quản trị, 4 mẫu dự án (Mục 2, 4.1)."""
import csv
import json
import os
import secrets
from pathlib import Path
from datetime import date, timedelta

from flask import current_app

from .extensions import db
from .models import Department, ProjectTemplate, User

STRUCTURE = [
    ("KKD", "Khối Kinh doanh", "division", None),
    ("PKD", "Phòng Kinh doanh", "department", "KKD"),
    ("PKD-SM", "Sales & Marketing", "team", "PKD"),
    ("PKD-EC", "e-Commerce", "team", "PKD"),
    ("PKD-SA", "Sales Admin", "team", "PKD"),
    ("PMKT", "Phòng Marketing", "department", "KKD"),
    ("PMKT-TK", "Thiết kế", "team", "PMKT"),
]

# (tên đăng nhập, họ tên, vai trò, mã phòng, chức danh)
STAFF = [
    ("thinh.lv", "Lê Vương Thịnh", "director", "KKD", "Giám đốc Khối Kinh doanh"),
    ("tien.nm", "Nguyễn Minh Tiến", "manager", "PKD", "Trưởng phòng Kinh doanh"),
    ("vy.nmt", "Nguyễn Mộng Tường Vy", "staff", "PKD-SM", "Chuyên viên Sales & Marketing"),
    ("huy.nm", "Nguyễn Minh Huy", "staff", "PKD-EC", "Chuyên viên e-Commerce"),
    ("qui.nmn", "Nguyễn Mai Như Quí", "staff", "PKD-SA", "Chuyên viên Sales Admin"),
    ("diep.mtn", "Mai Thị Ngọc Diệp", "staff", "PKD-SA", "Chuyên viên Sales Admin"),
    ("tien.htq", "Hà Thanh Quốc Tiến", "manager", "PMKT", "Trưởng phòng Marketing"),
    ("vu.th", "Trần Hùng Vũ", "staff", "PMKT-TK", "Chuyên viên Thiết kế"),
]


def T(title, s, d, review=False, priority="normal", checklist=None):
    return {"title": title, "offset_start": s, "offset_due": d, "needs_review": review,
            "priority": priority, "checklist": checklist or []}


TEMPLATES = [
    {
        "name": "Ra mắt sản phẩm mới", "type": "launch",
        "description": "Từ chốt thông số đến báo cáo kết quả 60 ngày sau ra mắt.",
        "tasks": [
            T("Chốt thông số kỹ thuật, tên gọi và giá bán lẻ", 0, 5, True, "high"),
            T("Xây dựng chính sách giá & chiết khấu đại lý", 3, 10, True, "high"),
            T("Chụp ảnh và quay video sản phẩm", 3, 12, True,
              checklist=["Ảnh nền trắng", "Ảnh lắp trên xe", "Video test chiếu sáng ban đêm"]),
            T("Viết thông cáo báo chí", 5, 12, True),
            T("Thiết kế catalogue, tờ rơi và POSM", 5, 15, True),
            T("Cập nhật sản phẩm lên website và sàn TMĐT", 12, 18),
            T("Kế hoạch nội dung social 4 tuần", 10, 18, True),
            T("Đào tạo sản phẩm cho đội Sales và đại lý", 15, 20,
              checklist=["Slide đào tạo", "Bộ câu hỏi thường gặp", "Video hướng dẫn lắp đặt"]),
            T("Tổ chức sự kiện ra mắt", 18, 30, True, "high"),
            T("Báo cáo kết quả sau 60 ngày", 30, 60, True),
        ],
    },
    {
        "name": "Tham gia hội chợ / triển lãm", "type": "trade_show",
        "description": "Chuẩn bị, vận hành gian hàng và chăm sóc khách hàng tiềm năng sau hội chợ.",
        "tasks": [
            T("Đăng ký gian hàng và thanh toán phí", 0, 5, False, "high"),
            T("Thiết kế gian hàng", 5, 20, True),
            T("Sản xuất ấn phẩm, quà tặng, standee", 15, 30, True),
            T("Chuẩn bị hàng mẫu và bộ demo chiếu sáng", 20, 35),
            T("Hậu cần: vé, khách sạn, vận chuyển", 20, 35),
            T("Mời khách hàng, đại lý, nhà phân phối", 20, 38),
            T("Vận hành gian hàng và thu thập lead", 40, 43, False, "high"),
            T("Chăm sóc lead sau hội chợ", 43, 55),
            T("Báo cáo chi phí và hiệu quả", 50, 60, True),
        ],
    },
    {
        "name": "Chương trình khuyến mãi đại lý", "type": "dealer_program",
        "description": "Cơ chế thưởng, truyền thông đến đại lý, theo dõi và quyết toán.",
        "tasks": [
            T("Đề xuất cơ chế chương trình và ngân sách", 0, 5, True, "high"),
            T("Thiết kế thông báo và POSM chương trình", 5, 10, True),
            T("Gửi thông báo đến toàn bộ đại lý", 10, 12),
            T("Theo dõi doanh số tham gia hằng tuần", 12, 42),
            T("Quyết toán và trả thưởng", 42, 50, True),
            T("Đánh giá hiệu quả chương trình", 45, 55, True),
        ],
    },
    {
        "name": "Mở thị trường xuất khẩu mới", "type": "market_entry",
        "description": "Từ nghiên cứu thị trường đến đơn hàng thử và đánh giá 90 ngày.",
        "tasks": [
            T("Nghiên cứu thị trường, đối thủ và giá bán", 0, 14, True),
            T("Kiểm tra quy chuẩn, chứng nhận và thủ tục nhập khẩu", 0, 21, True, "high"),
            T("Tìm và đánh giá nhà phân phối", 14, 45, False, "high"),
            T("Bảng giá xuất khẩu và chính sách nhà phân phối", 21, 35, True),
            T("Bản địa hóa catalogue, website, video", 21, 45, True),
            T("Đàm phán và ký hợp đồng phân phối", 45, 60, True, "high"),
            T("Đơn hàng thử và giao hàng", 60, 75),
            T("Kế hoạch marketing tại thị trường", 60, 75, True),
            T("Đánh giá 90 ngày", 85, 90, True),
        ],
    },
]


def run_seed(demo=False):
    codes = {}
    for code, name, level, parent in STRUCTURE:
        d = Department.query.filter_by(code=code).first()
        if not d:
            d = Department(code=code, name=name, level=level, parent_id=codes[parent].id if parent else None)
            db.session.add(d)
            db.session.flush()
        codes[code] = d

    for tpl in TEMPLATES:
        if not ProjectTemplate.query.filter_by(name=tpl["name"]).first():
            db.session.add(ProjectTemplate(name=tpl["name"], type=tpl["type"], description=tpl["description"],
                                           tasks_json=json.dumps(tpl["tasks"], ensure_ascii=False)))

    created = []
    admin_user = (os.environ.get("ADMIN_USERNAME") or "admin").strip().lower()
    admin_pwd = (os.environ.get("ADMIN_PASSWORD") or "").strip()
    admin = User.query.filter_by(username=admin_user).first()
    if not admin:
        pwd = admin_pwd or secrets.token_urlsafe(9)
        admin = User(username=admin_user, full_name="Quản trị hệ thống", role="admin",
                     department_id=codes["KKD"].id, must_change_password=not admin_pwd)
        admin.set_password(pwd)
        db.session.add(admin)
        created.append((admin_user, admin.full_name, pwd))
    elif admin_pwd and (admin.last_login_at is None or os.environ.get("ADMIN_FORCE_RESET") == "1"):
        # Đồng bộ mật khẩu quản trị từ biến môi trường khi admin chưa đăng nhập lần nào,
        # hoặc khi cần khôi phục (ADMIN_FORCE_RESET=1, nhớ xóa biến này sau khi dùng).
        if not admin.check_password(admin_pwd):
            admin.set_password(admin_pwd)
            print(f"Đã đặt lại mật khẩu cho tài khoản quản trị '{admin_user}' theo ADMIN_PASSWORD.")
        admin.must_change_password = False
        admin.failed_logins = 0
        admin.locked_until = None
        admin.is_active_flag = True

    for username, name, role, dept, title in STAFF:
        if not User.query.filter_by(username=username).first():
            pwd = secrets.token_urlsafe(6)
            u = User(username=username, full_name=name, role=role, department_id=codes[dept].id, title=title,
                     must_change_password=True)
            u.set_password(pwd)
            db.session.add(u)
            created.append((username, name, pwd))
    db.session.flush()

    if demo:
        _seed_demo(codes)
    db.session.commit()

    if created and not current_app.config.get("TESTING"):
        out = Path(current_app.config.get("DATA_DIR") or current_app.instance_path) / "mat_khau_ban_dau.csv"
        with open(out, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if f.tell() == 0:
                w.writerow(["Tên đăng nhập", "Họ tên", "Mật khẩu tạm"])
            w.writerows(created)
        print(f"Đã tạo {len(created)} tài khoản. Mật khẩu tạm lưu tại: {out}")
        print("Mỗi người phải đổi mật khẩu ở lần đăng nhập đầu tiên. Xóa tệp này sau khi đã phát mật khẩu.")
    print("Đã khởi tạo cơ cấu, nhân sự và mẫu dự án.")


def _seed_demo(codes):
    """Dự án mẫu để dùng thử, giao cho nhân sự thật. Xóa được trong màn hình Dự án."""
    from .models import Project
    from .services import apply_template, create_project, create_task
    if Project.query.count():
        return
    u = {x.username: x for x in User.query.all()}
    mkt, kd = u["tien.htq"], u["tien.nm"]

    tpl = ProjectTemplate.query.filter_by(type="launch").first()
    p = create_project(mkt, name="Ra mắt dòng BI-LED PROJECTOR 2026", type_="launch",
                       department_id=codes["PMKT"].id, owner=mkt, budget=350_000_000,
                       members=[u["vu.th"], u["vy.nmt"], u["huy.nm"], kd])
    p.status = "active"
    tasks = apply_template(p, tpl, date.today() - timedelta(days=8), mkt)
    plan = [("tien.nm", "done"), ("tien.nm", "review"), ("vu.th", "in_progress"), ("vy.nmt", "in_progress"),
            ("vu.th", "new"), ("huy.nm", "new"), ("vy.nmt", "new"), ("vy.nmt", "new"),
            ("tien.htq", "new"), ("tien.htq", "new")]
    for t, (who, st) in zip(tasks, plan):
        t.assignee_id, t.department_id, t.reviewer_id, t.status = u[who].id, u[who].department_id, mkt.id, st

    tpl2 = ProjectTemplate.query.filter_by(type="market_entry").first()
    p2 = create_project(kd, name="Mở thị trường Campuchia", type_="market_entry",
                        department_id=codes["PKD"].id, owner=kd, budget=200_000_000,
                        members=[u["vy.nmt"], u["qui.nmn"], u["vu.th"]])
    p2.status = "active"
    for t in apply_template(p2, tpl2, date.today() - timedelta(days=20), kd):
        t.assignee_id, t.department_id = u["vy.nmt"].id, u["vy.nmt"].department_id

    create_task(kd, "Đối soát công nợ đại lý tháng 9", u["qui.nmn"], date.today() + timedelta(days=3),
                priority="high", notify_assignee=False)
    create_task(kd, "Cập nhật tồn kho và giá trên Shopee, Lazada", u["huy.nm"],
                date.today() - timedelta(days=2), notify_assignee=False)
    create_task(kd, "Xuất hóa đơn và giao hàng đơn đại lý miền Tây", u["diep.mtn"],
                date.today() + timedelta(days=1), notify_assignee=False)
