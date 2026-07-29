FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    flask==3.1.0 flask-sqlalchemy==3.1.1 flask-migrate==4.1.0 flask-login==0.6.3 \
    sqlalchemy==2.0.36 pillow==11.1.0 gunicorn==23.0.0 tencentcloud-sdk-python==3.0.1353

COPY . .

RUN mkdir -p /app/data/db /app/data/media /app/data/tmp /app/data/backups /app/data/migration_reports

ENV DATA_PATH=/app/data
ENV DATABASE_URL=sqlite:////app/data/db/wardrobe.sqlite3
ENV FLASK_APP=app.py

EXPOSE 3000

# 启动脚本：创建目录 → 迁移DB → 启动服务
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]
