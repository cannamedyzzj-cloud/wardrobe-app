FROM python:3.11-slim

WORKDIR /app

# 安装依赖（离线模式，wheel包预下载在wheels目录）
# (在线安装)
RUN pip install --no-cache-dir flask flask-sqlalchemy pillow gunicorn

# 复制代码
COPY . .

# 创建数据和上传目录
RUN mkdir -p /app/data/uploads

ENV DATA_PATH=/app/data

EXPOSE 3000

# 初始化数据库并启动
CMD ["sh", "-c", "python -c 'from app import app, init_db; app.app_context().push(); init_db()' && gunicorn --bind 0.0.0.0:3000 --workers 2 --timeout 120 app:app"]
