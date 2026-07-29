#!/bin/sh
set -e

echo "=== Samantha的衣橱启动 ==="

# 1. 创建必要目录
mkdir -p /app/data/db /app/data/media /app/data/tmp /app/data/backups /app/data/migration_reports

# 2. 数据库迁移
echo "--- 数据库检查 ---"
python3 -c "
import sqlite3, os
db_path = '/app/data/db/wardrobe.sqlite3'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')]
    has_alembic = 'alembic_version' in tables
    print(f'has_alembic={has_alembic}')
else:
    print('has_alembic=False')
" > /tmp/db_state.txt

if grep -q "has_alembic=False" /tmp/db_state.txt; then
    # 没有 alembic 版本记录 → 全新或旧版数据库
    echo "首次启动，运行数据库迁移..."
    flask db upgrade
else
    # 有 alembic → 升级到最新
    echo "已有迁移记录，升级..."
    flask db upgrade
fi

# 3. 默认数据
python3 -c "
from app import app, db, Category, Brand
with app.app_context():
    if Category.query.count() == 0:
        from app import DEFAULT_CATEGORIES, DEFAULT_BRANDS
        for icon, name, order in DEFAULT_CATEGORIES:
            db.session.add(Category(name=name, icon=icon, sort_order=order))
        for name, order in DEFAULT_BRANDS:
            db.session.add(Brand(name=name, sort_order=order))
        db.session.commit()
        print('默认数据已初始化')
"

echo "--- 启动 Gunicorn ---"
exec gunicorn --bind 0.0.0.0:3000 --workers 2 --timeout 120 app:app
