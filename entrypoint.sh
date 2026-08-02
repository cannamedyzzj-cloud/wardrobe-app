#!/bin/sh
set -e

echo "=== Samantha的衣橱 v1.2.0 启动 ==="

# 1. 创建运行时目录（不创建数据库）
mkdir -p /app/data/db /app/data/media /app/data/tmp /app/data/backups /app/data/migration_reports

# 2. Storage ID — 首次启动生成，之后验证
if [ ! -f /app/data/.wardrobe-storage-id ]; then
    if [ -n "$EXPECTED_STORAGE_ID" ]; then
        echo "$EXPECTED_STORAGE_ID" > /app/data/.wardrobe-storage-id
        echo "Storage ID 已设置: $(echo "$EXPECTED_STORAGE_ID" | cut -c1-8)..."
    else
        python3 -c "import uuid; print(uuid.uuid4())" > /app/data/.wardrobe-storage-id
        echo "Storage ID 已生成: $(head -c 8 /app/data/.wardrobe-storage-id)..."
    fi
else
    SID=$(cat /app/data/.wardrobe-storage-id)
    SID_SHORT=$(echo "$SID" | cut -c1-8)
    if [ -n "$EXPECTED_STORAGE_ID" ] && [ "$SID" != "$EXPECTED_STORAGE_ID" ]; then
        EXPECTED_SHORT=$(echo "$EXPECTED_STORAGE_ID" | cut -c1-8)
        echo "Storage ID 不匹配！可能挂载了错误的数据目录。"
        echo "   期望: ${EXPECTED_SHORT}..."
        echo "   实际: ${SID_SHORT}..."
        echo "   已拒绝启动以防止数据损坏。"
        exit 1
    fi
    echo "Storage ID 验证通过: ${SID_SHORT}..."
fi

# 3. 数据库迁移（仅在数据库已存在时执行）
echo "--- 数据库检查 ---"
DB_PATH="/app/data/db/wardrobe.sqlite3"

if [ -f "$DB_PATH" ]; then
    echo "数据库存在，运行迁移..."
    flask db upgrade
    echo "迁移完成"
else
    echo ""
    echo "生产数据库不存在于: $DB_PATH"
    echo "如果是全新安装，请运行: flask install-new-instance"
    echo "如果数据应该已存在，请检查挂载的数据目录是否正确。"
    echo "为防止创建空数据库，应用已停止启动。"
    exit 1
fi

echo "--- 启动 Gunicorn ---"
exec gunicorn --bind 0.0.0.0:3000 --workers 2 --timeout 120 app:app
