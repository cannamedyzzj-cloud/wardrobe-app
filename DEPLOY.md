# 👗 老婆的衣橱 — 部署指南

## 🚀 一键部署（推荐：Docker）

### 前提条件
- 一台服务器（腾讯云/阿里云轻量服务器，99元/年那种就够）
- 服务器已安装 Docker 和 Docker Compose

### 步骤

**1. 把项目文件传到服务器**
```bash
# 在本地电脑上打包
tar -czf wardrobe-app.tar.gz wardrobe-app/

# 上传到服务器
scp wardrobe-app.tar.gz root@你的服务器IP:/root/

# 在服务器上解压
ssh root@你的服务器IP
cd /root
tar -xzf wardrobe-app.tar.gz
```

**2. 启动服务**
```bash
cd /root/wardrobe-app

# 修改 SECRET_KEY（重要！）
sed -i 's/SECRET_KEY=test-secret-key/SECRET_KEY=你随便打一串乱码/' docker-compose.yml

# 启动
docker compose up -d
```

**3. 打开浏览器访问**
```
http://你的服务器IP:3000
```

**4. 把网站添加到 iPhone 主屏幕**
- Safari 打开 http://你的服务器IP:3000
- 点击底部中间的「分享」按钮
- 滑动找到「添加到主屏幕」
- 点击「添加」
- ✅ 主屏幕上就有了「老婆的衣橱」App 图标！

---

## 🔐 可选：绑定域名 + HTTPS（推荐）

如果你有域名，建议配置 HTTPS，这样更安全：

```bash
# 1. 域名解析到服务器 IP
# 2. 用 Nginx 反代 + Let's Encrypt 证书
apt install nginx certbot python3-certbot-nginx -y
# 然后按提示配置
```

---

## 📦 更简单的方式：直接用 Docker 命令

如果不想用 docker-compose：

```bash
docker run -d \
  --name wardrobe \
  -p 3000:3000 \
  -v wardrobe_data:/app/data \
  -e SECRET_KEY=你随便打一串乱码 \
  --restart unless-stopped \
  wardrobe-app:latest
```

---

## 🛠️ 更新/重新构建

代码改了以后：
```bash
cd /root/wardrobe-app
docker compose down
docker compose up -d --build
```

数据不会丢失（存在 Docker volume `wardrobe_data` 里）。

---

## 📱 iPhone 使用提示

1. **拍照录入**：打开 App → 点右下角 + 号 → 点「上传照片」→ 选「拍照」→ 直接拍衣服
2. **记录位置**：填写「存放位置」字段，支持 4 级位置（房间→柜子→层→收纳箱）
3. **记录尺寸**：填写尺寸信息（肩宽/胸围/腰围/臀围/衣长/袖长），单位都是 cm
4. **快速查找**：在列表页搜索框输入关键词（名称/品牌/位置/收纳箱编号）
5. **克隆**：同款不同色？点详情页的 📋 按钮一键克隆
