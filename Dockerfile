FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖：sqlite3（备份/验证）
RUN apt-get update -qq && apt-get install -y -qq sqlite3 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    flask==3.1.0 flask-sqlalchemy==3.1.1 flask-migrate==4.1.0 flask-login==0.6.3 \
    sqlalchemy==2.0.36 pillow==11.1.0 gunicorn==23.0.0 tencentcloud-sdk-python==3.0.1353

# 复制应用代码（.dockerignore 排除 data/ .git/ __pycache__/）
COPY . .

# 创建运行时数据目录（挂载点占位）
RUN mkdir -p /app/data/db /app/data/media /app/data/tmp /app/data/backups /app/data/migration_reports

# 数据路径 — 必须使用绝对路径
ENV DATA_PATH=/app/data
ENV DATABASE_URL=sqlite:////app/data/db/wardrobe.sqlite3
ENV FLASK_APP=app.py

EXPOSE 3000

# 启动脚本
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]
