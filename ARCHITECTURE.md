# 👗 Samantha的衣橱 — 系统架构文档 v1.2.0

> 最后更新：2026-08-02 | 版本：v1.2.0 多用户管理系统

---

## 目录

1. [技术栈](#1-技术栈)
2. [项目结构](#2-项目结构)
3. [数据模型](#3-数据模型)
4. [认证与权限](#4-认证与权限)
5. [路由总览](#5-路由总览)
6. [核心功能实现](#6-核心功能实现)
7. [数据库迁移](#7-数据库迁移)
8. [部署架构](#8-部署架构)
9. [CLI 命令](#9-cli-命令)
10. [安全设计](#10-安全设计)

---

## 1. 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| **Web 框架** | Flask | 3.1.0 |
| **ORM** | SQLAlchemy + Flask-SQLAlchemy | 2.0.36 / 3.1.1 |
| **数据库** | SQLite | — |
| **迁移** | Flask-Migrate (Alembic) | 4.1.0 |
| **认证** | Flask-Login | 0.6.3 |
| **密码哈希** | Werkzeug Security | 3.1.8 |
| **图像处理** | Pillow | 11.1.0 |
| **AI 识别** | 腾讯云 TIIA API | 3.0.1353 |
| **前端 CSS** | Tailwind CSS (CDN) | — |
| **PWA** | Service Worker + Web Manifest | — |
| **部署** | Docker Compose + Gunicorn | 23.0.0 |
| **语言** | Python 3.11 | — |

---

## 2. 项目结构

```
wardrobe-app/
├── app.py                          # 主应用（~1290行），所有路由+模型+业务逻辑
├── Dockerfile                      # Docker 构建文件
├── docker-compose.yml              # Docker Compose 编排
├── entrypoint.sh                   # 容器启动脚本（迁移+初始化+启动）
├── requirements.txt                # Python 依赖
├── .env.example                    # 环境变量模板
├── .gitignore
│
├── migrations/                     # Alembic 数据库迁移
│   ├── alembic.ini
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 92824743f327_initial_schema.py           # v1.0 初始表
│       ├── 0c5f4679eeb1_add_multi_user_models.py    # v1.1 多用户模型
│       └── 8a3f1c02d4e5_make_wardrobe_id_not_null.py # v1.2 NOT NULL
│
├── static/                         # 静态资源
│   ├── sw.js                       # Service Worker v1.1.0
│   ├── manifest.json               # PWA Manifest
│   └── img/
│       ├── icon-192.png
│       └── icon-512.png
│
├── templates/                      # Jinja2 模板（17个）
│   ├── base.html                   # 基础布局（导航栏+用户菜单+FAB）
│   ├── login.html                  # 登录页（独立布局，粉色渐变背景）
│   ├── account.html                # 账号设置（信息+改密码）
│   ├── index.html                  # 首页仪表盘
│   ├── list.html                   # 衣物列表（筛选+搜索）
│   ├── detail.html                 # 衣物详情
│   ├── form.html                   # 衣物编辑表单
│   ├── smart.html                  # 智能录入（AI识别+指纹匹配）
│   ├── find.html                   # 找衣物（拍照匹配）
│   ├── locations.html              # 位置总览
│   ├── manage.html                 # 管理主页
│   ├── manage_categories.html      # 分类管理
│   ├── manage_brands.html          # 品牌管理
│   ├── manage_colors.html          # 颜色管理
│   ├── manage_locations.html       # 位置管理
│   ├── admin_users.html            # [管理员] 用户管理
│   ├── admin_wardrobes.html        # [管理员] 衣橱管理
│   ├── admin_members.html          # [管理员] 成员管理
│   └── register.html               # 注册（预留，默认关闭）
│
├── data/                           # 持久化数据（Docker volume 挂载）
│   ├── db/wardrobe.sqlite3         # SQLite 数据库
│   ├── media/                      # 照片文件
│   ├── tmp/                        # 临时文件
│   ├── backups/                    # 系统备份
│   └── migration_reports/          # 迁移报告
│
└── docs/
    ├── ARCHITECTURE.md              # 本文档
    ├── IMPLEMENTATION.md            # v1.0.0 实现细节
    └── DEPLOY.md                    # 部署指南
```

---

## 3. 数据模型

### 3.1 ER 图概览

```
┌──────────┐       ┌─────────────────┐       ┌──────────────┐
│   User   │1────*│ WardrobeMember  │*────1│   Wardrobe   │
│          │      │ - role (owner/  │      │              │
│ - username│      │   member/viewer)│      │ - name       │
│ - admin? │      │ - created_at    │      │ - is_active  │
│ - active?│      └─────────────────┘      └──────┬───────┘
└──────────┘                                       │ 1
                                                   │
                          ┌────────────────────────┼──────────────┐
                          │                        │              │
                          *                        *              *
                   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
                   │ Category │  │  Brand   │  │ColorPrst │  │LocationPr│
                   └────┬─────┘  └────┬─────┘  └──────────┘  └────┬─────┘
                        │             │                            │
                        *             *                            *
                   ┌──────────────────────────────────────────────────┐
                   │                    Garment                       │
                   │ - name, color, material, season, price, notes    │
                   │ - photo, thumbnail, fingerprint                  │
                   │ - status (在库/穿搭中/已清洗/已出借)              │
                   │ - size_label, shoulder, bust, waist, hip...      │
                   │ - archived (软删除)                              │
                   │ - created_by_user_id / updated_by_user_id        │
                   └──────────────────────────────────────────────────┘
```

### 3.2 User（用户）

```python
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id              # Integer PK
    username        # String(80) UNIQUE INDEX  — 登录名
    display_name    # String(100)              — 显示名
    password_hash   # String(255)              — Werkzeug 哈希
    is_system_admin # Boolean default=False    — 是否系统管理员
    is_active       # Boolean default=True     — 是否启用
    created_at      # DateTime
    updated_at      # DateTime (onupdate)
    last_login_at   # DateTime                 — 最后登录时间
```

**方法：**
- `set_password(password)` — 使用 `generate_password_hash` 哈希密码
- `check_password(password)` — 使用 `check_password_hash` 验证

### 3.3 Wardrobe（衣橱 / 租户隔离单元）

```python
class Wardrobe(db.Model):
    __tablename__ = 'wardrobes'

    id              # Integer PK
    name            # String(100)              — 衣橱名称
    owner_user_id   # FK → users.id           — 拥有者
    is_active       # Boolean default=True     — 是否启用
    created_at / updated_at

    # Relationships
    owner           # → User (backref='owned_wardrobes')
    members         # → [WardrobeMember]
```

### 3.4 WardrobeMember（衣橱成员）

```python
class WardrobeMember(db.Model):
    __tablename__ = 'wardrobe_members'

    id              # Integer PK
    wardrobe_id     # FK → wardrobes.id (CASCADE)
    user_id         # FK → users.id (CASCADE)
    role            # String(20): 'owner' | 'member' | 'viewer'
    created_at

    # Constraints
    __table_args__ = (UniqueConstraint('wardrobe_id', 'user_id'),)

    # Relationships
    wardrobe        # → Wardrobe
    user            # → User
```

**角色语义：**
| 角色 | 权限 |
|------|------|
| `owner` | 完全控制（读写+管理成员） |
| `member` | 读写衣物数据 |
| `viewer` | 只读（当前版本未强制视图限制） |

### 3.5 业务表（5张 — 均带 wardrobe_id）

| 表名 | 关键字段 | 说明 |
|------|---------|------|
| **categories** | id, wardrobe_id, name, icon, sort_order | 衣物分类 |
| **brands** | id, wardrobe_id, name, sort_order | 品牌 |
| **color_presets** | id, wardrobe_id, name, sort_order | 颜色预设 |
| **location_presets** | id, wardrobe_id, name, room, position, sort_order | 存储位置 |
| **garments** | id, wardrobe_id, category_id, brand_id, location_preset_id, color, material, season_group, status, price, photo, thumbnail, fingerprint, size_label, shoulder/bust/waist/hip/length/sleeve, notes, archived, created_by_user_id, updated_by_user_id | 衣物主表 |

**软删除：** `garments.archived = True`，所有查询默认过滤 `archived=False`

---

## 4. 认证与权限

### 4.1 认证流程

```
用户访问任意页面
    │
    ▼
@before_request 守卫
    │
    ├── endpoint 在白名单？（login/logout/static/healthz/sw.js/manifest）
    │   ├── 是 → 放行
    │   └── 否 → 检查 current_user.is_authenticated
    │           ├── 是 → 放行
    │           └── 否 → 302 重定向到 /login?next=<原URL>
    │
    ▼
/login 页面（独立布局，不继承 base.html）
    │
    ├── GET  → 渲染登录表单
    └── POST → 验证用户名密码
              ├── 成功 → login_user(u, remember=True) → 记录 last_login_at → 302 跳转
              └── 失败 → 显示 "用户名或密码错误"
```

### 4.2 衣橱隔离

```python
def current_wardrobe():
    """获取当前用户所在的衣橱"""
    # 1. 尝试从 session 读取
    wid = session.get('current_wardrobe_id')
    if wid:
        w = db.session.get(Wardrobe, wid)
        if w and w.is_active:
            if WardrobeMember.query.filter_by(wardrobe_id=wid, user_id=current_user.id).first():
                return w

    # 2. 自动选择第一个衣橱
    if current_user.is_authenticated:
        m = WardrobeMember.query.filter_by(user_id=current_user.id).first()
        if m and m.wardrobe and m.wardrobe.is_active:
            session['current_wardrobe_id'] = m.wardrobe_id
            return m.wardrobe

    return None  # 无衣橱 → 重定向到登录

def wq(model):
    """衣橱隔离查询 — 所有业务查询通过此函数"""
    w = current_wardrobe()
    if w is None:
        return model.query.filter(False)  # 空查询，安全返回零结果
    return model.query.filter_by(wardrobe_id=w.id)
```

**使用方式：** 所有业务路由中，`Model.query` 已全部替换为 `wq(Model)`。

### 4.3 管理员权限

```python
def admin_required(f):
    """系统管理员权限检查"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_system_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated
```

**使用：** `/admin/*` 路由同时使用 `@login_required` + `@admin_required` 双重保护。

### 4.4 上下文注入

```python
@app.context_processor
def inject_user_context():
    """向所有模板注入用户和衣橱上下文"""
    ctx = {}
    if current_user.is_authenticated:
        ctx['user_wardrobes'] = [...]  # 用户的所有活跃衣橱
        ctx['current_w'] = current_wardrobe()  # 当前选中衣橱
    return ctx
```

模板中可直接使用 `current_user`（Flask-Login 提供）、`current_w`、`user_wardrobes`。

---

## 5. 路由总览

### 5.1 认证路由

| 路由 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/login` | GET/POST | 登录 | 公开 |
| `/logout` | GET | 登出（清除 session） | @login_required |
| `/account` | GET | 账号设置页 | @login_required |
| `/account/password` | POST | 修改密码 | @login_required |
| `/wardrobe/switch` | POST | 切换衣橱 | @login_required |

### 5.2 管理员路由

| 路由 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/admin/users` | GET/POST | 用户管理（新建/禁用/重置密码） | @login_required + @admin_required |
| `/admin/wardrobes` | GET/POST | 衣橱管理（新建/编辑/启禁） | @login_required + @admin_required |
| `/admin/wardrobes/<id>/members` | GET/POST | 成员管理（添加/移除/角色变更） | @login_required + @admin_required |

### 5.3 业务路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 首页仪表盘（统计+最近衣物） |
| `/garments` | GET | 衣物列表（category/season/location/brand/status/search 筛选） |
| `/garments/<id>` | GET | 衣物详情 |
| `/garments/new` | GET/POST | 新增衣物 |
| `/garments/<id>/edit` | GET/POST | 编辑衣物 |
| `/garments/<id>/delete` | POST | 删除衣物 |
| `/garments/<id>/clone` | POST | 克隆衣物 |
| `/garments/<id>/status` | POST | 快速修改状态 |
| `/garments/smart` | GET/POST | 智能录入（AI识别+指纹匹配） |
| `/api/smart-analyze` | POST | 智能分析 API（JSON 返回） |
| `/find` | GET/POST | 找衣物（拍照匹配定位） |
| `/locations` | GET | 位置总览 |
| `/manage` | GET | 管理主页 |
| `/manage/categories` | GET/POST | 分类 CRUD |
| `/manage/brands` | GET/POST | 品牌 CRUD |
| `/manage/colors` | GET/POST | 颜色预设 CRUD |
| `/manage/locations` | GET/POST | 位置预设 CRUD |
| `/export` | GET | 数据导出（ZIP：JSON+照片） |

### 5.4 基础设施路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/healthz` | GET | 健康检查（DB连接+写入+数据路径） |
| `/uploads/<fn>` | GET | 照片访问（需登录+衣橱验证） |
| `/manifest.json` | GET | PWA Manifest |
| `/sw.js` | GET | Service Worker |

---

## 6. 核心功能实现

### 6.1 照片处理流水线

```
上传照片
    │
    ├── save_photo(file)
    │   ├── 生成唯一文件名: YYYYMMDDHHMMSSffff.ext
    │   ├── 保存原始照片 → UPLOAD_FOLDER/
    │   └── 生成缩略图: thumb_*.webp (400x400, quality=80)
    │
    ├── generate_fingerprint(path)
    │   ├── 中心裁剪（裁掉20%边缘）
    │   ├── 缩放到 80×80
    │   ├── RGB → HSV（每像素）
    │   ├── 量化：H/45° × S×4 × V×4 → 8×4×4 = 128维直方图
    │   └── 归一化 → JSON 存储
    │
    └── extract_colors(path)
        ├── 中心裁剪 + 缩放 120×120
        ├── 遍历 13 种预设颜色范围
        ├── 统计每个范围的像素占比（>10% 阈值）
        └── 返回 Top-N 颜色（名称+hex+占比）
```

### 6.2 AI 服装识别

```
recognize_clothing(path)
    │
    ├── 读取图片 → Base64 编码
    ├── 调用腾讯云 TIIA DetectProduct API
    │   ├── Endpoint: tiia.tencentcloudapi.com
    │   ├── Region: ap-shanghai
    │   └── 返回: [{name, parents, confidence}, ...]
    │
    └── match_category(ai_results, user_categories)
        ├── 为每个用户分类构建关键词映射
        │   e.g. "上衣" → ["上衣","t恤","衬衫","卫衣","雪纺","top","shirt"]
        ├── 遍历 AI 结果，子串匹配关键词
        └── 返回最高置信度匹配 (id, score)
```

### 6.3 衣物指纹匹配

```
garment_smart (POST)
    │
    ├── 上传照片
    ├── 计算指纹 + 提取颜色 + AI 识别
    ├── 在同衣橱内匹配候选衣物：
    │   ├── 按 AI 识别分类筛选（如有）
    │   ├── 对每个候选计算：
    │   │   score = compare_fingerprints(query_fp, candidate_fp)
    │   │          + 0.10 (颜色名匹配加分)
    │   ├── 过滤 score < 0.40
    │   └── 按 score 降序排列，取 Top 5
    │
    └── 返回匹配结果 + 智能录入数据
```

`compare_fingerprints` 使用**直方图交集**算法：
```python
score = sum(min(a, b) for a, b in zip(hist1, hist2))
# 范围 [0, 1]，越接近 1 越相似
```

### 6.4 数据导出

`/export` 生成 ZIP 包含：
- `数据.json` — 所有衣物的结构化数据（UTF-8, indent=2）
- `照片/` — 原始照片和缩略图文件

### 6.5 Service Worker

```javascript
CACHE_NAME = 'samantha-static-v1.1.0'

// 静态资源：Cache First（CSS/JS/图标）
// 私密页面：Network Only（所有 HTML 页面）
NETWORK_ONLY_PATTERNS = ['/', '/garments', '/manage', '/admin', '/account', '/find', '/locations']

// activate: 清理旧版本缓存
```

### 6.6 导航栏用户菜单

```
┌─────────────────────────────────┐
│ 👗 Samantha    [首页][位置][衣物][管理][🅢] │  ← 导航栏
└─────────────────────────────────┘
                           │ 点击头像
                           ▼
               ┌───────────────────┐
               │ Samantha          │
               │ @Samantha         │
               ├───────────────────┤
               │ 👗 Wardrobe    ✓  │  ← 衣橱切换（多衣橱时显示）
               ├───────────────────┤
               │ 👤 账号设置       │
               │ ⚙️ 系统管理       │  ← 仅管理员可见
               ├───────────────────┤
               │ 退出登录          │
               └───────────────────┘
```

---

## 7. 数据库迁移

### 迁移历史

| 版本 | Revision ID | 说明 |
|------|------------|------|
| v1.0.0 | `92824743f327` | 初始 schema：categories, brands, color_presets, location_presets, garments |
| v1.1.0 | `0c5f4679eeb1` | 多用户：users, wardrobes, wardrobe_members + 所有业务表加 wardrobe_id / created_by_user_id |
| v1.2.0 | `8a3f1c02d4e5` | 第二阶段：所有业务表 wardrobe_id → NOT NULL |

### 迁移执行

容器启动时 `entrypoint.sh` 自动执行：
```bash
flask db upgrade   # 自动运行所有未执行的迁移
```

### SQLite 兼容处理

- 所有外键使用**命名约束**（`fk_brands_wardrobe` 等）
- `ALTER TABLE ADD COLUMN` 手动执行（SQLite batch_alter_table 限制）
- `NOT NULL` 迁移使用 `op.execute(UPDATE ... WHERE IS NULL)` 预填充

---

## 8. 部署架构

### Docker Compose

```yaml
# docker-compose.yml
services:
  wardrobe:
    build: .
    image: samantha-wardrobe:${APP_VERSION:-1.0.0}
    ports:
      - "3000:3000"
    volumes:
      - /samantha-wardrobe/shared/data:/app/data   # 数据持久化（绝对路径）
    env_file:
      - /samantha-wardrobe/shared/.env             # 环境变量
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 数据路径分离

```
/samantha-wardrobe/          ← 宿主机永久路径
├── shared/
│   ├── data/                ← 挂载到容器 /app/data
│   │   ├── db/              ← SQLite 数据库
│   │   ├── media/           ← 照片文件
│   │   ├── tmp/             ← 临时文件
│   │   ├── backups/         ← 系统备份
│   │   └── migration_reports/
│   └── .env                 ← 环境变量
│
└── wardrobe-app/            ← 代码（每次部署覆盖）
    ├── app.py, templates/, static/, ...
    └── docker-compose.yml
```

### 容器启动流程

```
entrypoint.sh
    │
    ├── mkdir -p data/{db,media,tmp,backups,migration_reports}
    ├── flask db upgrade                    # 运行迁移
    ├── [初次] flask bootstrap-multiuser    # v1.0→v1.1 数据迁移（交互式）
    └── gunicorn -w 2 -b 0.0.0.0:3000 app:app
```

---

## 9. CLI 命令

| 命令 | 说明 |
|------|------|
| `flask db upgrade` | 执行数据库迁移 |
| `flask db migrate -m "..."` | 生成新迁移脚本 |
| `flask bootstrap-multiuser` | v1.0 → v1.1 数据迁移（交互式：创建管理员+衣橱+迁移数据） |
| `flask seed-defaults` | 为指定衣橱初始化默认分类和品牌（交互式输入衣橱ID） |
| `flask backup-system` | 系统备份：数据库 + 所有媒体文件 → tar.gz（含 manifest.json + SHA256） |
| `flask verify-backup` | 验证最新备份的完整性 |

---

## 10. 安全设计

### 防护措施

| 层面 | 措施 |
|------|------|
| **认证** | Flask-Login session + Werkzeug 密码哈希（pbkdf2:sha256） |
| **授权** | `wq()` 衣橱隔离 + `admin_required` 装饰器 + `@before_request` 全局守卫 |
| **数据隔离** | 所有业务查询强制 `filter_by(wardrobe_id=w.id)` |
| **照片保护** | `/uploads/<fn>` 需登录 + 验证照片归属衣橱 |
| **CSRF** | 所有状态变更使用 POST（当前无 CSRF Token，适用于局域网场景） |
| **Service Worker** | 私密页面 Network Only（不缓存用户数据） |
| **会话安全** | SECRET_KEY 从环境变量注入，登出时清除 `current_wardrobe_id` |
| **防篡改** | 不能修改/禁用自己（admin → toggle_active 跳过 self） |
| **Owner 保护** | 不能移除/降级衣橱最后一个 owner 角色 |
| **输入校验** | 密码 ≥ 4 字符，用户名去空白，文件上传限制 16MB |

### 安全边界

当前版本设计用于**局域网部署**，默认关闭公开注册。如需公网部署，建议增加：
- CSRF Token（Flask-WTF）
- 速率限制（Flask-Limiter）
- HTTPS（Nginx 反代）
- 更严格的密码策略

---

## 附录：技术指标

| 指标 | 数值 |
|------|------|
| 总代码行数（app.py） | ~1290 行 |
| 模板数量 | 17 个 |
| 路由数量 | 30+ 个 |
| 数据表 | 8 张（users, wardrobes, wardrobe_members + 5 业务表） |
| 迁移脚本 | 3 个 |
| Docker 镜像大小 | ~180 MB (python:3.11-slim base) |
| 内存占用 | Gunicorn 2 workers，~100-200 MB |
