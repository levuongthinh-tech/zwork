FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Ho_Chi_Minh \
    FLASK_APP=wsgi.py

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Railway cấp biến PORT; seed chỉ tạo dữ liệu còn thiếu nên chạy lại mỗi lần khởi động là an toàn
CMD flask --app wsgi seed && gunicorn wsgi:app --workers 1 --threads 8 --timeout 60 --bind 0.0.0.0:${PORT:-8080}
