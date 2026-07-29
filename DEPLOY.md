# 👗 Samantha的衣橱 — 部署指南

## 🚀 一键部署（Docker Compose）

### 前提条件
- 一台服务器（腾讯云/阿里云轻量服务器，2C2G 就够）
- 服务器已安装 Docker 和 Docker Compose

### 步骤

**1. 把项目文件传到服务器**
```bash
tar -czf wardrobe-app.tar.gz wardrobe-app/
scp wardrobe-app.tar.gz root@你的服务器IP:/root/
ssh root@你的服务器IP
cd /root && tar -xzf wardrobe-app.tar.gz
```

**2. 配置环境变量**
```bash
cd /root/wardrobe-app

# 创建 .env 文件
cp .env.example .env

# 编辑 .env，修改 SECRET_KEY 为随机字符串
nano .env
# 如果要用腾讯云AI识别，填入 TENCENT_SECRET_ID / TENCENT_SECRET_KEY
```

**3. 启动服务**
```bash
docker compose up -d
```

**4. 访问**
```
http://你的服务器IP:3000
```

首次访问会跳转到注册页面，第一个注册的用户自动成为管理员。

---

## 👥 多用户功能

- 每个用户拥有独立的衣橱空间，数据完全隔离
- 首次注册的用户自动成为管理员
- 管理员可访问 `/admin` 管理所有用户（重置密码、设为管理员、模拟登录）
- 默认管理员账号：`admin` / `admin`（首次启动自动创建）

---

## 📱 iPhone 使用

1. Safari 打开网站 → 底部「分享」→「添加到主屏幕」
2. **智能录入**：点右下角 📷 按钮 → 拍照 → AI 自动识别颜色和类别 → 自动匹配已有衣物
3. **拍照找衣**：点首页「找衣物」→ 拍照 → 指纹匹配找到存放位置
4. **状态管理**：详情页切换「在库/取出/待归位」状态

---

## 🔐 绑定域名 + HTTPS

如果你有域名，建议配置 HTTPS：
```bash
apt install nginx certbot python3-certbot-nginx -y
# 然后按提示配置 Nginx 反代 + Let's Encrypt 证书
```

---

## 🛠️ 更新/重建

```bash
cd /root/wardrobe-app
docker compose down
docker compose up -d --build
```

数据存储在 `./data` 目录（bind mount），不会因重建丢失。

---

## 🔑 环境变量说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SECRET_KEY` | Flask 会话密钥 | 必须修改 |
| `DATA_PATH` | 数据存储路径 | `/app/data` |
| `TENCENT_SECRET_ID` | 腾讯云 API ID | 可选 |
| `TENCENT_SECRET_KEY` | 腾讯云 API Key | 可选 |

> 不配置腾讯云密钥时，智能录入的颜色识别仍可用（基于 Pillow），仅服装类别 AI 识别不可用。
