#!/usr/bin/env python3
"""Samantha的衣橱"""
import json, io, zipfile, os, uuid, base64, hashlib
from datetime import datetime
from collections import Counter
from urllib.parse import urlsplit
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, Response, session, abort, flash, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from pathlib import Path
from PIL import Image

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me')

# P0: 生产环境 SECRET_KEY 安全检查
_key = app.config['SECRET_KEY']
if not _key or _key in ('change-me', 'change-me-to-a-random-string') or len(_key) < 16:
    if os.environ.get('FLASK_ENV') != 'development':
        raise RuntimeError("生产环境必须设置安全的 SECRET_KEY（至少16字符），不可使用默认值")

# CSRF 保护
csrf = CSRFProtect(app)

# Session Cookie 固定配置（防止 Safari 多 Cookie 冲突）
app.config['SESSION_COOKIE_NAME'] = 'samantha_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_PATH'] = '/'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FORCE_HTTPS', '').lower() == 'true'

_data_path = os.environ.get('DATA_PATH', '/app/data')
_db_url = os.environ.get('DATABASE_URL')
if not _db_url:
    _db_url = f"sqlite:///{_data_path}/db/wardrobe.sqlite3"
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

app.config['UPLOAD_FOLDER'] = os.path.join(_data_path, 'media')
app.config['TMP_FOLDER'] = os.path.join(_data_path, 'tmp')
app.config['BACKUP_FOLDER'] = os.path.join(_data_path, 'backups')
app.config['REPORT_FOLDER'] = os.path.join(_data_path, 'migration_reports')
app.config['DATA_PATH'] = _data_path

db = SQLAlchemy(app)

# Flask-Migrate（数据库迁移）
from flask_migrate import Migrate, stamp as migrate_stamp
migrate = Migrate(app, db)

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.context_processor
def inject_user_context():
    """向所有模板注入用户和衣橱上下文"""
    ctx = {}
    if current_user.is_authenticated:
        ctx['user_wardrobes'] = [m.wardrobe for m in WardrobeMember.query.filter_by(user_id=current_user.id).all() if m.wardrobe and m.wardrobe.is_active]
        ctx['current_w'] = current_wardrobe()
    return ctx

# ============================================================
# v1.1.0 新增：多用户模型
# ============================================================

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_system_admin = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)
    # v1.3: 会话版本（改密码/撤销登录时递增）
    session_version = db.Column(db.Integer, default=0)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Wardrobe(db.Model):
    __tablename__ = 'wardrobes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    owner = db.relationship('User', backref='owned_wardrobes')

class WardrobeMember(db.Model):
    __tablename__ = 'wardrobe_members'
    id = db.Column(db.Integer, primary_key=True)
    wardrobe_id = db.Column(db.Integer, db.ForeignKey('wardrobes.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default='member')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('wardrobe_id', 'user_id', name='uq_wardrobe_member'),)
    wardrobe = db.relationship('Wardrobe', backref='members')
    user = db.relationship('User', backref='wardrobe_memberships')

# ============================================================
# v1.0.0 现有模型（增加 wardrobe_id）
# ============================================================

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    wardrobe_id = db.Column(db.Integer, db.ForeignKey('wardrobes.id'), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(10), default='\U0001f454')
    sort_order = db.Column(db.Integer, default=0)
    garments = db.relationship('Garment', backref='category', lazy='dynamic')

class Brand(db.Model):
    __tablename__ = 'brands'
    id = db.Column(db.Integer, primary_key=True)
    wardrobe_id = db.Column(db.Integer, db.ForeignKey('wardrobes.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    garments = db.relationship('Garment', backref='brand_rel', lazy='dynamic')

class ColorPreset(db.Model):
    __tablename__ = 'color_presets'
    id = db.Column(db.Integer, primary_key=True)
    wardrobe_id = db.Column(db.Integer, db.ForeignKey('wardrobes.id'), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)
    sort_order = db.Column(db.Integer, default=0)

class LocationPreset(db.Model):
    __tablename__ = 'location_presets'
    id = db.Column(db.Integer, primary_key=True)
    wardrobe_id = db.Column(db.Integer, db.ForeignKey('wardrobes.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    room = db.Column(db.String(100))
    position = db.Column(db.String(100))
    sort_order = db.Column(db.Integer, default=0)
    garments = db.relationship('Garment', backref='location_preset', lazy='dynamic')

class Garment(db.Model):
    __tablename__ = 'garments'
    id = db.Column(db.Integer, primary_key=True)
    wardrobe_id = db.Column(db.Integer, db.ForeignKey('wardrobes.id'), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'))
    location_preset_id = db.Column(db.Integer, db.ForeignKey('location_presets.id'))
    color = db.Column(db.String(100))
    material = db.Column(db.String(200))
    season_group = db.Column(db.String(50))
    status = db.Column(db.String(20), default='\u5728\u5e93')
    fingerprint = db.Column(db.Text)
    price = db.Column(db.Float)
    purchase_date = db.Column(db.Date)
    photo = db.Column(db.String(500))
    thumbnail = db.Column(db.String(500))
    notes = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    size_label = db.Column(db.String(50))
    shoulder = db.Column(db.Float); bust = db.Column(db.Float)
    waist = db.Column(db.Float); hip = db.Column(db.Float)
    length = db.Column(db.Float); sleeve = db.Column(db.Float)
    custom_size = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # v1.3: 回收站
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)


# ============================================================
# v1.3 新增：审计日志
# ============================================================

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    wardrobe_id = db.Column(db.Integer, db.ForeignKey('wardrobes.id'), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    summary = db.Column(db.String(500), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)

    actor = db.relationship('User')

    @classmethod
    def log(cls, action, actor_id=None, wardrobe_id=None, target_type=None, target_id=None, summary='', meta=None):
        try:
            aid = actor_id or (current_user.id if current_user.is_authenticated else None)
        except Exception:
            aid = None
        entry = cls(
            actor_user_id=aid,
            wardrobe_id=wardrobe_id,
            action=action, target_type=target_type,
            target_id=target_id, summary=summary,
            metadata_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        )
        db.session.add(entry)
        return entry

DEFAULT_CATEGORIES = [('\U0001f455','\u4e0a\u8863',1),('\U0001f456','\u88e4\u5b50',2),('\U0001f457','\u88d9\u5b50',3),('\U0001f9e5','\u5916\u5957',4),('\U0001f9e3','\u914d\u9970',5)]
DEFAULT_BRANDS = [('\u4f18\u8863\u5e93',1),('ZARA',2),('H&M',3),('\u65e0\u54c1\u724c',4)]

def ensure_data_dirs():
    """仅创建运行时目录，不创建数据库"""
    for d in [app.config['UPLOAD_FOLDER'], app.config['TMP_FOLDER'],
              app.config['BACKUP_FOLDER'], app.config['REPORT_FOLDER']]:
        os.makedirs(d, exist_ok=True)

def verify_storage_id():
    """验证持久化目录身份，防止挂载到空目录"""
    storage_id_file = os.path.join(_data_path, '.wardrobe-storage-id')
    expected = os.environ.get('EXPECTED_STORAGE_ID', '')
    if os.path.exists(storage_id_file):
        with open(storage_id_file) as f:
            actual = f.read().strip()
        if expected and actual != expected:
            return False, f"Storage ID 不匹配: 期望 {expected[:8]}..., 实际 {actual[:8]}..."
        return True, actual
    else:
        # 首次安装 — 创建 storage ID
        sid = str(uuid.uuid4())
        if expected:
            sid = expected
        with open(storage_id_file, 'w') as f:
            f.write(sid)
        return True, sid

def _read_storage_id():
    """只读获取 storage ID"""
    sf = os.path.join(_data_path, '.wardrobe-storage-id')
    if os.path.exists(sf):
        with open(sf) as f:
            return f.read().strip()
    return 'unknown'

def _get_alembic_rev():
    try:
        return db.session.execute(db.text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return 'unknown'

def preflight_check():
    """
    启动前检查。返回 (ok, message)。
    如果数据库不存在，拒绝启动（防止空挂载自动创建新库）。
    """
    errors = []
    # 1. DATA_PATH 必须是绝对路径
    if not os.path.isabs(_data_path):
        errors.append(f"DATA_PATH 必须是绝对路径: {_data_path}")
    # 2. 数据库文件必须存在
    db_path = os.path.join(_data_path, 'db', 'wardrobe.sqlite3')
    if not os.path.exists(db_path):
        errors.append(
            f"生产数据库不存在: {db_path}\n"
            f"可能挂载了错误的数据目录。为防止创建空数据库，应用已停止启动。"
        )
    # 3. storage ID
    ok, sid = verify_storage_id()
    if not ok:
        errors.append(sid)
    if errors:
        return False, '; '.join(errors)
    return True, f"OK (storage={sid[:8]}...)"

def save_photo(file):
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    ext = file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else 'jpg'
    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}.{ext}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    thumb_filename = f"thumb_{filename.rsplit('.',1)[0]}.webp"
    thumb_path = os.path.join(app.config['UPLOAD_FOLDER'], thumb_filename)
    img = Image.open(filepath).convert('RGB')
    img.thumbnail((400, 400), Image.LANCZOS)
    img.save(thumb_path, 'WEBP', quality=80)
    return filename, thumb_filename

def generate_fingerprint(image_path):
    """Extract fingerprint: center-crop first, then HSV histogram"""
    try:
        img = Image.open(image_path).convert('RGB')
        w, h = img.size
        cw, ch = int(w * 0.2), int(h * 0.2)
        img = img.crop((cw, ch, w - cw, h - ch))
        img = img.resize((80, 80))
        pixels = list(img.getdata())
        hist = [0] * 128
        for r, g, b in pixels:
            rn, gn, bn = r/255, g/255, b/255
            cmx, cmn = max(rn,gn,bn), min(rn,gn,bn)
            delta = cmx - cmn
            if delta == 0: h = 0
            elif cmx == rn: h = 60 * (((gn - bn) / delta) % 6)
            elif cmx == gn: h = 60 * (((bn - rn) / delta) + 2)
            else: h = 60 * (((rn - gn) / delta) + 4)
            s = 0 if cmx == 0 else delta / cmx
            v = cmx
            hi = min(int(h / 45), 7)
            si = min(int(s * 4), 3)
            vi = min(int(v * 4), 3)
            idx = hi * 16 + si * 4 + vi
            if idx < 128: hist[idx] += 1
        total = sum(hist) or 1
        hist = [h/total for h in hist]
        return json.dumps({'hist': hist, 'version': 1})
    except:
        return None

def compare_fingerprints(fp1, fp2):
    try:
        if not fp1 or not fp2: return 0
        h1 = json.loads(fp1).get('hist',[])
        h2 = json.loads(fp2).get('hist',[])
        if len(h1) != 128 or len(h2) != 128: return 0
        return round(sum(min(a,b) for a,b in zip(h1,h2)), 3)
    except:
        return 0

def format_storage_location(garment):
    lp = garment.location_preset
    if not lp: return '\u672a\u6807\u8bb0\u4f4d\u7f6e'
    parts = [lp.room, lp.position]
    return ' \u2192 '.join(filter(None, parts))

# Color extraction
COLOR_RANGES = [
    ((0,0,0),(45,45,45),'\u9ed1\u8272'), ((200,200,200),(255,255,255),'\u767d\u8272'),
    ((80,80,80),(180,180,180),'\u7070\u8272'), ((150,0,0),(255,80,80),'\u7ea2\u8272'),
    ((200,80,0),(255,160,60),'\u6a59\u8272'), ((180,160,0),(255,240,80),'\u9ec4\u8272'),
    ((0,100,0),(120,220,80),'\u7eff\u8272'), ((0,100,120),(80,200,220),'\u9752\u8272'),
    ((0,0,120),(80,100,255),'\u84dd\u8272'), ((100,0,100),(200,80,220),'\u7d2b\u8272'),
    ((200,120,150),(255,180,210),'\u7c89\u8272'), ((100,50,20),(180,130,80),'\u68d5\u8272'),
    ((200,180,140),(255,230,200),'\u7c73\u8272'),
]

def extract_colors(image_path, top_n=1):
    try:
        img = Image.open(image_path).convert('RGB')
        w, h = img.size
        cw, ch = int(w * 0.2), int(h * 0.2)
        img = img.crop((cw, ch, w - cw, h - ch))
        img = img.resize((120, 120))
        pixels = list(img.getdata())
        total = len(pixels)
        results = []
        for (r1,g1,b1),(r2,g2,b2),name in COLOR_RANGES:
            count = sum(1 for r,g,b in pixels if r1<=r<=r2 and g1<=g<=g2 and b1<=b<=b2)
            if count > total * 0.10:
                mr,mg,mb = (r1+r2)//2,(g1+g2)//2,(b1+b2)//2
                results.append({'name': name, 'hex': '#%02x%02x%02x'%(mr,mg,mb), 'pct': round(count/total*100)})
        results.sort(key=lambda x: x['pct'], reverse=True)
        return results[:top_n]
    except:
        return []

def recognize_clothing(image_path):
    try:
        sid = os.environ.get('TENCENT_SECRET_ID','')
        skey = os.environ.get('TENCENT_SECRET_KEY','')
        if not sid or not skey: return None
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.tiia.v20190529 import tiia_client, models
        with open(image_path,'rb') as f: img_b64 = base64.b64encode(f.read()).decode()
        cred = credential.Credential(sid, skey)
        hp = HttpProfile(); hp.endpoint = 'tiia.tencentcloudapi.com'
        cp = ClientProfile(); cp.httpProfile = hp
        client = tiia_client.TiiaClient(cred, 'ap-shanghai', cp)
        req = models.DetectProductRequest(); req.ImageBase64 = img_b64
        resp = client.DetectProduct(req)
        return [{'name': p.Name, 'category': p.Parents, 'confidence': p.Confidence} for p in resp.Products]
    except Exception as e:
        print(f'AI: {e}')
        return None

def match_category(ai_results, user_categories):
    if not ai_results or not user_categories: return None, 0
    kmap = {}
    for cat in user_categories:
        n = cat.name.lower()
        kmap[cat.id] = [n]
        if '\u4e0a\u8863' in n: kmap[cat.id] += ['\u4e0a\u8863','t\u6064','\u886c\u886b','\u536b\u8863','\u96ea\u7eba','top','shirt']
        if '\u88e4\u5b50' in n: kmap[cat.id] += ['\u88e4\u5b50','\u725b\u4ed4\u88e4','\u4f11\u95f2\u88e4','\u77ed\u88e4','pants','jeans']
        if '\u88d9\u5b50' in n: kmap[cat.id] += ['\u88d9\u5b50','\u8fde\u8863\u88d9','\u534a\u8eab\u88d9','dress','skirt']
        if '\u5916\u5957' in n: kmap[cat.id] += ['\u5916\u5957','\u5927\u8863','\u5939\u514b','\u7fbd\u7ed2','jacket','coat']
        if '\u914d\u9970' in n: kmap[cat.id] += ['\u914d\u9970','\u56f4\u5dfe','\u5e3d\u5b50','accessory']
        if '\u6bdb\u8863' in n: kmap[cat.id] += ['\u6bdb\u8863','\u9488\u7ec7','sweater']
        if '\u8fd0\u52a8' in n: kmap[cat.id] += ['\u8fd0\u52a8','sport']
        if '\u978b' in n: kmap[cat.id] += ['\u978b','shoes','sneaker']
        if '\u5305' in n: kmap[cat.id] += ['\u5305','bag']
    best_id, best_score = None, 0
    for prod in ai_results:
        text = (prod.get('name','') + ' ' + prod.get('category','')).lower()
        for cid, kws in kmap.items():
            for kw in kws:
                if kw.lower() in text:
                    s = prod.get('confidence', 50)
                    if s > best_score: best_score, best_id = s, cid
    return best_id, best_score

# ========== 权限与查询辅助 ==========

def current_wardrobe():
    """获取当前用户所在的衣橱"""
    wid = session.get('current_wardrobe_id')
    if wid:
        w = db.session.get(Wardrobe, wid)
        if w and w.is_active:
            # 验证用户仍是成员
            if WardrobeMember.query.filter_by(wardrobe_id=wid, user_id=current_user.id).first():
                return w
        # 衣橱已失效或用户已不是成员 → 清除
        session.pop('current_wardrobe_id', None)
    # 自动选择第一个衣橱
    if current_user.is_authenticated:
        m = WardrobeMember.query.filter_by(user_id=current_user.id).order_by(WardrobeMember.id).first()
        if m and m.wardrobe and m.wardrobe.is_active:
            session['current_wardrobe_id'] = m.wardrobe_id
            return m.wardrobe
    return None

def _select_initial_wardrobe():
    """登录后选择初始衣橱。返回 Wardrobe / 'choose' / None"""
    session.pop('current_wardrobe_id', None)
    if not current_user.is_authenticated:
        return None
    memberships = WardrobeMember.query.filter_by(user_id=current_user.id).all()
    active = [m for m in memberships if m.wardrobe and m.wardrobe.is_active]
    if len(active) == 0:
        return None
    if len(active) == 1:
        session['current_wardrobe_id'] = active[0].wardrobe_id
        return active[0].wardrobe
    # 多个衣橱 → 选第一个（用户后续可切换）
    session['current_wardrobe_id'] = active[0].wardrobe_id
    return active[0].wardrobe

def wq(model):
    """衣橱隔离查询"""
    w = current_wardrobe()
    if w is None:
        return model.query.filter(False)  # 空查询
    return model.query.filter_by(wardrobe_id=w.id)

# v1.3: 统一查询服务
def active_garments():
    w = current_wardrobe()
    if not w: return Garment.query.filter(False)
    return Garment.query.filter_by(wardrobe_id=w.id, archived=False, deleted_at=None)

def trashed_garments():
    w = current_wardrobe()
    if not w: return Garment.query.filter(False)
    return Garment.query.filter_by(wardrobe_id=w.id, archived=False).filter(Garment.deleted_at.isnot(None))

def get_active_garment_or_404(gid):
    w = current_wardrobe()
    if not w: abort(404)
    return Garment.query.filter_by(id=gid, wardrobe_id=w.id, deleted_at=None).first_or_404()

# v1.3: 维护模式
_MAINTENANCE_FILE = os.path.join(_data_path, '.maintenance')

def is_maintenance_mode():
    return os.path.exists(_MAINTENANCE_FILE)

@app.before_request
def maintenance_guard():
    if is_maintenance_mode() and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        pub = ('login', 'logout', 'healthz', 'static', 'uploaded_file',
               'maintenance_status', 'maintenance_enable', 'maintenance_disable')
        if request.endpoint not in pub:
            abort(503)
@app.before_request
def check_auth():
    """登录守卫"""
    public = ['login', 'logout', 'static', 'uploaded_file', 'manifest', 'service_worker', 'healthz']
    if request.endpoint not in public and not request.path.startswith('/uploads/') and not request.path.startswith('/static/'):
        if not current_user.is_authenticated:
            return redirect(url_for('login', next=request.path))

def get_safe_next():
    """安全校验 next 参数，防止重定向循环"""
    target = request.args.get('next') or request.form.get('next')
    if not target:
        return None
    parsed = urlsplit(target)
    # 拒绝外部 URL
    if parsed.scheme or parsed.netloc:
        return None
    if not parsed.path.startswith('/'):
        return None
    # 禁止跳转到登录/登出（会形成循环）
    blocked = {'/login', '/logout', url_for('login'), url_for('logout')}
    if parsed.path in blocked or parsed.path.rstrip('/') in blocked:
        return None
    # 禁止多层嵌套 next
    if '/login?next=' in target or '/logout?next=' in target:
        return None
    return target

@app.after_request
def add_private_cache_headers(response):
    """私有页面统一禁止缓存"""
    private_prefixes = (
        '/', '/login', '/logout', '/account', '/wardrobes',
        '/garments', '/manage', '/admin', '/api', '/media',
        '/uploads', '/export', '/find', '/locations', '/smart',
    )
    path = request.path.rstrip('/') or '/'
    if path == '/' or any(path.startswith(p) for p in private_prefixes):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        # 保留已有的 Vary 头
        existing_vary = response.headers.get('Vary', '')
        if 'Cookie' not in existing_vary:
            response.headers['Vary'] = f"{existing_vary}, Cookie".strip(', ')
    return response

def admin_required(f):
    """系统管理员权限检查"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_system_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated

# ========== 认证路由 ==========

@app.route('/login', methods=['GET', 'POST'])
@csrf.exempt
def login():
    if current_user.is_authenticated:
        # 已登录 → 根据衣橱情况决定去向
        w = _select_initial_wardrobe()
        if w is None:
            return render_template('no_wardrobe.html'), 200
        if w == 'choose':
            return redirect(url_for('index'))
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form.get('username','').strip()).first()
        if u and u.check_password(request.form.get('password','')) and u.is_active:
            # 登录前清除旧账号上下文
            session.pop('current_wardrobe_id', None)
            login_user(u, remember=True)
            u.last_login_at = datetime.utcnow()
            AuditLog.log('user.login', summary=f'{u.username} 登录成功')
            db.session.commit()
            # 安全 next 参数
            nxt = get_safe_next()
            if nxt:
                return redirect(nxt)
            return redirect(url_for('index'))
        error = '用户名或密码错误'
        AuditLog.log('user.login_failed', summary=f"登录失败: {request.form.get('username','')[:20]}")
        db.session.commit()
    return render_template('login.html', error=error)

@app.route('/logout', methods=['POST'])
@csrf.exempt
@login_required
def logout():
    AuditLog.log('user.logout', summary=f'{current_user.username} 登出')
    db.session.commit()
    logout_user()
    session.clear()
    response = make_response(redirect(url_for('login')))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.delete_cookie(app.config['SESSION_COOKIE_NAME'], path=app.config['SESSION_COOKIE_PATH'])
    response.delete_cookie('remember_token', path='/')
    return response

@app.route('/account')
@login_required
def account():
    w = current_wardrobe()
    return render_template('account.html', wardrobe=w)

@app.route('/account/password', methods=['POST'])
@login_required
def change_password():
    old = request.form.get('old_password','')
    new = request.form.get('new_password','')
    if not current_user.check_password(old):
        flash('原密码错误')
    elif len(new) < 4:
        flash('新密码至少4个字符')
    else:
        current_user.set_password(new)
        db.session.commit()
        flash('密码已更新')
    return redirect(url_for('account'))

@app.route('/wardrobe/switch', methods=['POST'])
@login_required
def wardrobe_switch():
    wid = request.form.get('wardrobe_id', type=int)
    if wid:
        w = db.session.get(Wardrobe, wid)
        if w and w.is_active:
            m = WardrobeMember.query.filter_by(wardrobe_id=wid, user_id=current_user.id).first()
            if m:
                session['current_wardrobe_id'] = wid
                flash(f'已切换到：{w.name}')
    return redirect(request.referrer or url_for('index'))

# ========== 管理员路由 ==========

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_users():
    error = success = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            uname = request.form.get('username','').strip()
            pw = request.form.get('password','')
            if not uname or len(pw) < 4:
                error = '用户名不能为空，密码至少4个字符'
            elif User.query.filter_by(username=uname).first():
                error = f'用户名 {uname} 已存在'
            else:
                u = User(
                    username=uname,
                    display_name=request.form.get('display_name','').strip() or uname,
                    password_hash=generate_password_hash(pw),
                    is_system_admin=bool(request.form.get('is_system_admin')),
                )
                db.session.add(u); db.session.commit()
                success = f'用户 {uname} 已创建'
        elif action == 'toggle_active':
            uid = request.form.get('user_id', type=int)
            u = db.session.get(User, uid)
            if u and u.id != current_user.id:
                u.is_active = not u.is_active
                db.session.commit()
                success = f'{u.username} 已{"启用" if u.is_active else "禁用"}'
        elif action == 'reset_password':
            uid = request.form.get('user_id', type=int)
            pw = request.form.get('new_password','')
            u = db.session.get(User, uid)
            if u and len(pw) >= 4:
                u.set_password(pw); db.session.commit()
                success = f'{u.username} 密码已重置'
    users = User.query.order_by(User.id).all()
    return render_template('admin_users.html', users=users, error=error, success=success)

@app.route('/admin/wardrobes', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_wardrobes():
    error = success = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            name = request.form.get('name','').strip()
            oid = request.form.get('owner_user_id', type=int)
            if not name or not oid:
                error = '名称和拥有者不能为空'
            else:
                w = Wardrobe(name=name, owner_user_id=oid)
                db.session.add(w); db.session.flush()
                db.session.add(WardrobeMember(wardrobe_id=w.id, user_id=oid, role='owner'))
                db.session.commit()
                success = f'衣橱 {name} 已创建'
        elif action == 'edit':
            wid = request.form.get('wardrobe_id', type=int)
            w = db.session.get(Wardrobe, wid)
            if w:
                w.name = request.form.get('name','').strip()
                oid = request.form.get('owner_user_id', type=int)
                if oid:
                    w.owner_user_id = oid
                    if not WardrobeMember.query.filter_by(wardrobe_id=wid, user_id=oid).first():
                        db.session.add(WardrobeMember(wardrobe_id=wid, user_id=oid, role='owner'))
                db.session.commit()
                success = f'{w.name} 已更新'
        elif action == 'toggle_active':
            wid = request.form.get('wardrobe_id', type=int)
            w = db.session.get(Wardrobe, wid)
            if w:
                w.is_active = not w.is_active
                db.session.commit()
                success = f'{w.name} 已{"启用" if w.is_active else "禁用"}'
    wardrobes = Wardrobe.query.order_by(Wardrobe.id).all()
    for w in wardrobes:
        w.member_count = WardrobeMember.query.filter_by(wardrobe_id=w.id).count()
    all_users = User.query.filter_by(is_active=True).order_by(User.id).all()
    return render_template('admin_wardrobes.html', wardrobes=wardrobes, all_users=all_users, error=error, success=success)

@app.route('/admin/wardrobes/<int:id>/members', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_members(id):
    wardrobe = db.session.get(Wardrobe, id)
    if not wardrobe:
        abort(404)
    error = success = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            uid = request.form.get('user_id', type=int)
            role = request.form.get('role', 'member')
            if uid and not WardrobeMember.query.filter_by(wardrobe_id=id, user_id=uid).first():
                db.session.add(WardrobeMember(wardrobe_id=id, user_id=uid, role=role))
                db.session.commit()
                success = '成员已添加'
            else:
                error = '用户已是成员或无效'
        elif action == 'remove':
            mid = request.form.get('member_id', type=int)
            m = db.session.get(WardrobeMember, mid)
            if m and m.wardrobe_id == id:
                # 检查是否是最后一个 owner
                owners = WardrobeMember.query.filter_by(wardrobe_id=id, role='owner').count()
                if m.role == 'owner' and owners <= 1:
                    error = '不能移除最后一个Owner'
                else:
                    db.session.delete(m); db.session.commit()
                    success = '成员已移除'
        elif action == 'changerole':
            mid = request.form.get('member_id', type=int)
            role = request.form.get('role', 'member')
            m = db.session.get(WardrobeMember, mid)
            if m and m.wardrobe_id == id:
                # 不能把最后一个 owner 改成其他角色
                if m.role == 'owner' and role != 'owner':
                    owners = WardrobeMember.query.filter_by(wardrobe_id=id, role='owner').count()
                    if owners <= 1:
                        error = '不能移除最后一个Owner的角色'
                        return render_template('admin_members.html', wardrobe=wardrobe, members=members, available_users=available_users, error=error, success=success)
                m.role = role; db.session.commit()
                success = '角色已更新'
    members = WardrobeMember.query.filter_by(wardrobe_id=id).order_by(WardrobeMember.id).all()
    member_ids = [m.user_id for m in members]
    available_users = User.query.filter(User.is_active == True, User.id.notin_(member_ids)).order_by(User.id).all()
    return render_template('admin_members.html', wardrobe=wardrobe, members=members, available_users=available_users, error=error, success=success)

# ========== 业务路由 ==========

@app.route('/')
def index():
    w = current_wardrobe()
    if not w:
        return render_template('no_wardrobe.html'), 200
    categories = wq(Category).order_by(Category.sort_order).all()
    total = wq(Garment).filter_by(archived=False).count()
    cat_counts = {c.id: wq(Garment).filter_by(category_id=c.id, archived=False).count() for c in categories}
    season_stats = {sg: wq(Garment).filter_by(archived=False, season_group=sg).count() for sg in ['\u590f\u5b63','\u51ac\u5b63','\u6625\u79cb\u5b63']}
    out_count = wq(Garment).filter_by(archived=False).filter(Garment.status != '\u5728\u5e93').count()
    m = datetime.utcnow().month
    current_season = '\u590f\u5b63' if m in [5,6,7,8,9] else ('\u51ac\u5b63' if m in [12,1,2] else '\u6625\u79cb\u5b63')
    recent = wq(Garment).filter_by(archived=False).order_by(Garment.created_at.desc()).limit(8).all()
    return render_template('index.html', categories=categories, total=total, out_count=out_count,
                          cat_counts=cat_counts, season_stats=season_stats, current_season=current_season,
                          recent=recent, format_location=format_storage_location)

@app.route('/garments')
def garment_list():
    query = wq(Garment).filter_by(archived=False)
    if cid := request.args.get('category', type=int): query = query.filter_by(category_id=cid)
    if sg := request.args.get('season'): query = query.filter_by(season_group=sg)
    if lid := request.args.get('location', type=int): query = query.filter_by(location_preset_id=lid)
    if bid := request.args.get('brand', type=int): query = query.filter_by(brand_id=bid)
    if st := request.args.get('status'): query = query.filter_by(status=st)
    if s := request.args.get('search', ''): query = query.filter(
        db.or_(Garment.name.ilike(f'%{s}%'), Garment.color.ilike(f'%{s}%'), Garment.notes.ilike(f'%{s}%')))
    garments = query.order_by(Garment.created_at.desc()).all()
    return render_template('list.html', garments=garments,
                          categories=wq(Category).order_by(Category.sort_order).all(),
                          location_presets=wq(LocationPreset).order_by(LocationPreset.sort_order).all(),
                          brands=wq(Brand).order_by(Brand.sort_order).all(),
                          current_category=cid, current_season=sg, current_location=lid, current_brand=bid,
                          current_search=s or '', format_location=format_storage_location)

@app.route('/garments/<int:id>')
def garment_detail(id):
    return render_template('detail.html', garment=wq(Garment).filter_by(id=id).first_or_404(), format_location=format_storage_location)

def _save_garment(garment):
    w = current_wardrobe()
    if w:
        garment.wardrobe_id = w.id
    garment.created_by_user_id = current_user.id
    garment.name = request.form.get('name','')
    # 分类：支持输入新分类
    cname = request.form.get('category_text', '').strip()
    if cname:
        cat = wq(Category).filter_by(name=cname).first()
        if not cat:
            mo = db.session.query(db.func.max(Category.sort_order)).scalar() or 0
            cat = Category(name=cname, icon='📦', sort_order=mo+1)
            db.session.add(cat)
            db.session.flush()
        garment.category_id = cat.id
    else:
        garment.category_id = request.form.get('category_id', type=int)
    garment.brand_id = request.form.get('brand_id', type=int)
    garment.location_preset_id = request.form.get('location_preset_id', type=int)
    garment.color = request.form.get('color_text','').strip()
    garment.material = request.form.get('material','')
    garment.season_group = request.form.get('season_group','')
    garment.price = request.form.get('price', type=float)
    garment.notes = request.form.get('notes','')
    garment.size_label = request.form.get('size_label','')
    if pd := request.form.get('purchase_date',''): garment.purchase_date = datetime.strptime(pd, '%Y-%m-%d').date()
    # 品牌：新文字 > 下拉选择 > 空
    bname = request.form.get('brand_text', '').strip()
    if bname:
        brand = wq(Brand).filter_by(name=bname).first()
        if not brand:
            w = current_wardrobe()
            mo = db.session.query(db.func.max(Brand.sort_order)).filter(Brand.wardrobe_id == w.id).scalar() or 0
            brand = Brand(name=bname, sort_order=mo+1)
            db.session.add(brand)
            db.session.flush()
        garment.brand_id = brand.id
    else:
        garment.brand_id = request.form.get('brand_id', type=int)
    # 自动保存颜色预设
    if garment.color and garment.color.strip():
        cn = garment.color.strip()
        if not wq(ColorPreset).filter_by(name=cn).first():
            mo = db.session.query(db.func.max(ColorPreset.sort_order)).scalar() or 0
            db.session.add(ColorPreset(name=cn, sort_order=mo+1))
    else: garment.purchase_date = None
    if 'photo' in request.files and request.files['photo'].filename:
        garment.photo, garment.thumbnail = save_photo(request.files['photo'])
        fp = generate_fingerprint(os.path.join(app.config['UPLOAD_FOLDER'], garment.photo))
        if fp: garment.fingerprint = fp

@app.route('/garments/new', methods=['GET','POST'])
def garment_new():
    if request.method == 'POST':
        g = Garment(); _save_garment(g); db.session.add(g); db.session.commit()
        return redirect(url_for('garment_detail', id=g.id))
    return render_template('form.html', garment=None, color_presets=wq(ColorPreset).order_by(ColorPreset.sort_order).all(),
                          categories=wq(Category).order_by(Category.sort_order).all(),
                          location_presets=wq(LocationPreset).order_by(LocationPreset.sort_order).all(),
                          brands=wq(Brand).order_by(Brand.sort_order).all(), mode='new')

@app.route('/garments/<int:id>/edit', methods=['GET','POST'])
def garment_edit(id):
    g = wq(Garment).filter_by(id=id).first_or_404()
    if request.method == 'POST':
        _save_garment(g); g.updated_at = datetime.utcnow(); db.session.commit()
        return redirect(url_for('garment_detail', id=g.id))
    return render_template('form.html', garment=g, color_presets=wq(ColorPreset).order_by(ColorPreset.sort_order).all(),
                          categories=wq(Category).order_by(Category.sort_order).all(),
                          location_presets=wq(LocationPreset).order_by(LocationPreset.sort_order).all(),
                          brands=wq(Brand).order_by(Brand.sort_order).all(), mode='edit')

@app.route('/garments/<int:id>/delete', methods=['POST'])
def garment_delete(id):
    g = wq(Garment).filter_by(id=id).first_or_404()
    g.deleted_at = datetime.utcnow()
    g.deleted_by_user_id = current_user.id
    AuditLog.log('garment.trash', wardrobe_id=(current_wardrobe().id if current_wardrobe() else None),
                 target_type='Garment', target_id=g.id, summary=f'删除衣物: {g.name}')
    db.session.commit()
    return redirect(url_for('garment_list'))

# ========== v1.3 回收站 ==========

@app.route('/trash')
def trash_list():
    garments = trashed_garments().order_by(Garment.deleted_at.desc()).all()
    return render_template('trash.html', garments=garments)

@app.route('/trash/garments/<int:id>/restore', methods=['POST'])
def trash_restore(id):
    g = wq(Garment).filter_by(id=id).first_or_404()
    if not g.deleted_at: abort(404)
    g.deleted_at = None; g.deleted_by_user_id = None
    AuditLog.log('garment.restore', target_type='Garment', target_id=g.id, summary=f'恢复衣物: {g.name}')
    db.session.commit()
    return redirect(url_for('trash_list'))

@app.route('/trash/garments/<int:id>/purge', methods=['POST'])
def trash_purge(id):
    g = wq(Garment).filter_by(id=id).first_or_404()
    if not g.deleted_at: abort(404)
    name = g.name
    photo = g.photo; thumb = g.thumbnail
    db.session.delete(g)
    AuditLog.log('garment.purge', target_type='Garment', target_id=id, summary=f'永久删除衣物: {name}')
    db.session.commit()
    # 数据库提交成功后再删文件
    if photo:
        fp = os.path.join(app.config['UPLOAD_FOLDER'], photo)
        if os.path.exists(fp): os.remove(fp)
    if thumb:
        fp = os.path.join(app.config['UPLOAD_FOLDER'], thumb)
        if os.path.exists(fp): os.remove(fp)
    return redirect(url_for('trash_list'))

@app.route('/trash/empty', methods=['POST'])
def trash_empty():
    w = current_wardrobe()
    if not w: abort(404)
    garments = trashed_garments().all()
    count = len(garments)
    for g in garments:
        db.session.delete(g)
    AuditLog.log('trash.empty', target_type='Garment', summary=f'清空回收站: {count}件')
    db.session.commit()
    return redirect(url_for('trash_list'))

@app.route('/garments/<int:id>/clone', methods=['POST'])
def garment_clone(id):
    o = wq(Garment).filter_by(id=id).first_or_404()
    c = Garment(name=f"{o.name} (\u526f\u672c)", category_id=o.category_id, brand_id=o.brand_id,
                location_preset_id=o.location_preset_id, color=o.color, material=o.material,
                season_group=o.season_group, price=o.price, size_label=o.size_label, notes=o.notes)
    w = current_wardrobe()
    if w: c.wardrobe_id = w.id
    c.created_by_user_id = current_user.id
    # 不复制照片——进入编辑页让用户重新确认
    db.session.add(c); db.session.commit()
    return redirect(url_for('garment_edit', id=c.id))

@app.route('/garments/<int:id>/status', methods=['POST'])
def garment_status(id):
    g = wq(Garment).filter_by(id=id).first_or_404()
    g.status = request.form.get('status', '\u5728\u5e93')
    db.session.commit()
    return redirect(url_for('garment_detail', id=id))

@app.route('/api/smart-analyze', methods=['POST'])
def smart_analyze():
    if 'photo' not in request.files or not request.files['photo'].filename:
        return {'error': '\u8bf7\u4e0a\u4f20\u7167\u7247'}, 400
    file = request.files['photo']
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    tmp_name = f'tmp_{uuid.uuid4().hex}.jpg'
    tmp_path = os.path.join(app.config['UPLOAD_FOLDER'], tmp_name)
    file.save(tmp_path)
    colors = extract_colors(tmp_path)
    color_str = colors[0]['name'] if colors else ''
    ai_result = recognize_clothing(tmp_path)
    matched_cat = None
    if ai_result:
        cats = wq(Category).order_by(Category.sort_order).all()
        cid, score = match_category(ai_result, cats)
        if cid and score > 10:
            cat = wq(Category).get(cid)
            matched_cat = {'id': cid, 'name': cat.name, 'icon': cat.icon, 'score': score}
    fp = generate_fingerprint(tmp_path)
    return {
        'tmp_file': tmp_name,
        'colors': colors, 'color_display': color_str,
        'ai_products': ai_result, 'matched_category': matched_cat,
        'fingerprint': fp,
    }

@app.route('/garments/smart', methods=['GET','POST'])
def garment_smart():
    # POST 时先做指纹匹配
    matched_garments = None
    smart_data = None
    if request.method == 'POST' and 'photo' in request.files and request.files['photo'].filename:
        # 先分析照片
        from_smart = request.form.get('from_smart', '')
        if from_smart == 'confirm':
            # 用户确认录入，执行原逻辑
            pass
        else:
            # 刚上传照片，做匹配
            file = request.files['photo']
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            tmp_name = f'tmp_{uuid.uuid4().hex}.jpg'
            tmp_path = os.path.join(app.config['UPLOAD_FOLDER'], tmp_name)
            file.save(tmp_path)
            
            query_fp = generate_fingerprint(tmp_path)
            colors = extract_colors(tmp_path)
            color_str = colors[0]['name'] if colors else ''
            ai_result = recognize_clothing(tmp_path)
            
            # 匹配已有衣物
            cats = wq(Category).order_by(Category.sort_order).all()
            cid = None
            ai_name = ''
            if ai_result and len(ai_result) > 0:
                cid, _ = match_category(ai_result, cats)
                ai_name = ai_result[0]['name']
            candidates = wq(Garment).filter_by(archived=False)
            if cid: candidates = candidates.filter_by(category_id=cid)
            scored = []
            for g in candidates.all():
                score = 0
                if g.fingerprint and query_fp:
                    score = compare_fingerprints(g.fingerprint, query_fp)
                if g.color and colors:
                    for c in colors:
                        if c['name'] in (g.color or ''): score += 0.10; break
                scored.append((score, g))
            scored.sort(key=lambda x: x[0], reverse=True)
            
            matched_garments = []
            for score, g in scored[:5]:
                if score < 0.40: continue
                matched_garments.append({
                    'id': g.id, 'name': g.name,
                    'photo': g.thumbnail or g.photo,
                    'category': g.category.name if g.category else '',
                    'color': g.color or '',
                    'status': g.status or '在库',
                    'score': int(score * 100),
                    'location': format_storage_location(g),
                    'lp': {'room': g.location_preset.room if g.location_preset else '',
                           'position': g.location_preset.position if g.location_preset else ''}
                })
            
            # 准备智能录入数据（不管是否匹配都准备好）
            matched_cat = None
            if ai_result and len(ai_result) > 0:
                cid2, score2 = match_category(ai_result, cats)
                if cid2 and score2 > 10:
                    cat = wq(Category).get(cid2)
                    matched_cat = {'id': cid2, 'name': cat.name, 'icon': cat.icon, 'score': score2}
            
            smart_data = {
                'tmp_file': tmp_name,
                'color_display': color_str,
                'colors': colors,
                'ai_name': ai_name,
                'matched_category': matched_cat,
                'fingerprint': query_fp,
            }
    
    if request.method == 'POST' and request.form.get('from_smart') == 'confirm':
        # 确认录入
        g = Garment()
        w = current_wardrobe()
        if w:
            g.wardrobe_id = w.id
        g.created_by_user_id = current_user.id
        g.name = request.form.get('name', '未命名')
        g.category_id = request.form.get('category_id', type=int) or (wq(Category).first().id if wq(Category).first() else None)
        g.brand_id = request.form.get('brand_id', type=int)
        g.location_preset_id = request.form.get('location_preset_id', type=int)
        g.color = request.form.get('color_text','').strip()
        g.season_group = request.form.get('season_group', '')
        g.notes = request.form.get('notes', '')
        g.fingerprint = request.form.get('fingerprint', '')
        tmp_file = request.form.get('tmp_file', '')
        if tmp_file:
            tmp_path = os.path.join(app.config['UPLOAD_FOLDER'], tmp_file)
            if os.path.exists(tmp_path):
                ext = tmp_file.rsplit('.', 1)[-1]
                final_name = f'{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}.{ext}'
                final_path = os.path.join(app.config['UPLOAD_FOLDER'], final_name)
                os.rename(tmp_path, final_path)
                g.photo = final_name
                thumb_name = f'thumb_{final_name.rsplit(".",1)[0]}.webp'
                thumb_path = os.path.join(app.config['UPLOAD_FOLDER'], thumb_name)
                img = Image.open(final_path).convert('RGB')
                img.thumbnail((400, 400), Image.LANCZOS)
                img.save(thumb_path, 'WEBP', quality=80)
                g.thumbnail = thumb_name
        # 品牌：新文字 > 下拉选择 > 空
        bn = request.form.get('brand_text', '').strip()
        if bn:
            brand = wq(Brand).filter_by(name=bn).first()
            if not brand:
                w = current_wardrobe()
                mo = db.session.query(db.func.max(Brand.sort_order)).filter(Brand.wardrobe_id == w.id).scalar() or 0
                brand = Brand(name=bn, sort_order=mo+1)
                db.session.add(brand)
                db.session.flush()
            g.brand_id = brand.id
        else:
            g.brand_id = request.form.get('brand_id', type=int)
        # 自动保存颜色预设
        if g.color and g.color.strip():
            cn = g.color.strip()
            if not wq(ColorPreset).filter_by(name=cn).first():
                mo = db.session.query(db.func.max(ColorPreset.sort_order)).filter(ColorPreset.wardrobe_id == w.id).scalar() or 0
                db.session.add(ColorPreset(name=cn, sort_order=mo+1))
        db.session.add(g); db.session.commit()
        return redirect(url_for('garment_detail', id=g.id))
    
    categories = wq(Category).order_by(Category.sort_order).all()
    location_presets = wq(LocationPreset).order_by(LocationPreset.sort_order).all()
    brands = wq(Brand).order_by(Brand.sort_order).all()
    return render_template('smart.html', color_presets=wq(ColorPreset).order_by(ColorPreset.sort_order).all(), 
                          categories=categories, location_presets=location_presets, brands=brands,
                          matched_garments=matched_garments, smart_data=smart_data)

@app.route('/find', methods=['GET','POST'])
def find_location():
    result = None
    if request.method == 'POST' and 'photo' in request.files and request.files['photo'].filename:
        file = request.files['photo']
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        tmp = f'tmp_find_{uuid.uuid4().hex}.jpg'
        tmp_path = os.path.join(app.config['UPLOAD_FOLDER'], tmp)
        file.save(tmp_path)
        query_fp = generate_fingerprint(tmp_path)
        colors = extract_colors(tmp_path)
        ai_result = recognize_clothing(tmp_path)
        cats = wq(Category).order_by(Category.sort_order).all()
        cid = None
        ai_name = ''
        ai_category = ''
        if ai_result and len(ai_result) > 0:
            cid, _ = match_category(ai_result, cats)
            ai_name = ai_result[0]['name']
            ai_category = ai_result[0]['category']
        candidates = wq(Garment).filter_by(archived=False)
        if cid:
            candidates = candidates.filter_by(category_id=cid)
        scored = []
        for g in candidates.all():
            score = 0
            if g.fingerprint and query_fp:
                score = compare_fingerprints(g.fingerprint, query_fp)
            if g.color and colors:
                for c in colors:
                    if c['name'] in (g.color or ''):
                        score += 0.15
                        break
            scored.append((score, g))
        scored.sort(key=lambda x: x[0], reverse=True)
        matches = []
        for score, g in scored[:10]:
            if score < 0.3:
                continue
            matches.append({
                'id': g.id, 'name': g.name,
                'photo': g.thumbnail or g.photo,
                'category': g.category.name if g.category else '',
                'color': g.color or '',
                'status': g.status or '在库',
                'score': int(score * 100),
                'location': format_storage_location(g),
            })
        result = {'ai_name': ai_name, 'ai_category': ai_category, 'garments': matches}
    return render_template('find.html', result=result)

@app.route('/locations')
def locations():
    presets = wq(LocationPreset).order_by(LocationPreset.sort_order).all()
    data = [{'preset': p, 'count': wq(Garment).filter_by(location_preset_id=p.id, archived=False).count()} for p in presets]
    return render_template('locations.html', preset_data=data)

@app.route('/manage')
def manage():
    return render_template('manage.html', cat_count=wq(Category).count(),
                          brand_count=wq(Brand).count(), loc_count=wq(LocationPreset).count(), color_count=wq(ColorPreset).count())

@app.route('/manage/categories', methods=['GET','POST'])
def manage_categories():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            n = request.form.get('name','').strip()
            if n:
                w = current_wardrobe()
                mo = db.session.query(db.func.max(Category.sort_order)).filter(Category.wardrobe_id == w.id).scalar() or 0
                db.session.add(Category(name=n, icon=request.form.get('icon','\U0001f4e6').strip(), sort_order=mo+1))
                db.session.commit()
        elif a == 'edit':
            cat = wq(Category).get(request.form.get('id', type=int))
            if cat: cat.name = request.form.get('name','').strip(); cat.icon = request.form.get('icon','\U0001f4e6').strip(); db.session.commit()
        elif a == 'delete':
            cat = wq(Category).get(request.form.get('id', type=int))
            if cat and cat.garments.filter_by(archived=False).count()==0: db.session.delete(cat); db.session.commit()
        return redirect(url_for('manage_categories'))
    cats = wq(Category).order_by(Category.sort_order).all()
    for c in cats: c.garment_count = wq(Garment).filter_by(category_id=c.id, archived=False).count()
    return render_template('manage_categories.html', categories=cats)

@app.route('/manage/brands', methods=['GET','POST'])
def manage_brands():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            n = request.form.get('name','').strip()
            if n:
                w = current_wardrobe()
                mo = db.session.query(db.func.max(Brand.sort_order)).filter(Brand.wardrobe_id == w.id).scalar() or 0
                db.session.add(Brand(name=n, sort_order=mo+1)); db.session.commit()
        elif a == 'edit':
            b = wq(Brand).get(request.form.get('id', type=int))
            if b: b.name = request.form.get('name','').strip(); db.session.commit()
        elif a == 'delete':
            b = wq(Brand).get(request.form.get('id', type=int))
            if b and b.garments.filter_by(archived=False).count()==0: db.session.delete(b); db.session.commit()
        return redirect(url_for('manage_brands'))
    brands = wq(Brand).order_by(Brand.sort_order).all()
    for b in brands: b.garment_count = wq(Garment).filter_by(brand_id=b.id, archived=False).count()
    return render_template('manage_brands.html', brands=brands)

@app.route('/manage/colors', methods=['GET','POST'])
def manage_colors():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            n = request.form.get('name','').strip()
            if n:
                mo = db.session.query(db.func.max(ColorPreset.sort_order)).filter(ColorPreset.wardrobe_id == w.id).scalar() or 0
                db.session.add(ColorPreset(name=n, sort_order=mo+1)); db.session.commit()
        elif a == 'edit':
            c = wq(ColorPreset).get(request.form.get('id', type=int))
            if c: c.name = request.form.get('name','').strip(); db.session.commit()
        elif a == 'delete':
            c = wq(ColorPreset).get(request.form.get('id', type=int))
            if c: db.session.delete(c); db.session.commit()
        return redirect(url_for('manage_colors'))
    colors = wq(ColorPreset).order_by(ColorPreset.sort_order).all()
    for c in colors: c.garment_count = wq(Garment).filter(Garment.color == c.name, Garment.archived == False).count()
    return render_template('manage_colors.html', colors=colors)

@app.route('/manage/locations', methods=['GET','POST'])
def manage_locations():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            room = request.form.get('room','').strip()
            if room:
                pos = request.form.get('position','').strip()
                w = current_wardrobe()
                mo = db.session.query(db.func.max(LocationPreset.sort_order)).filter_by(wardrobe_id=w.id).scalar() or 0
                display = ' → '.join(filter(None, [room, pos]))
                lp = LocationPreset(name=display, room=room, position=pos, sort_order=mo+1)
                if w: lp.wardrobe_id = w.id
                db.session.add(lp)
                db.session.commit()
        elif a == 'edit':
            lp = wq(LocationPreset).get(request.form.get('id', type=int))
            if lp:
                for f in ['room','position']: setattr(lp, f, request.form.get(f,'').strip())
                lp.name = ' → '.join(filter(None, [lp.room, lp.position]))
                db.session.commit()
        elif a == 'delete':
            lp = wq(LocationPreset).get(request.form.get('id', type=int))
            if lp and lp.garments.filter_by(archived=False).count()==0: db.session.delete(lp); db.session.commit()
        return redirect(url_for('manage_locations'))
    presets = wq(LocationPreset).order_by(LocationPreset.sort_order).all()
    for p in presets: p.garment_count = wq(Garment).filter_by(location_preset_id=p.id, archived=False).count()
    return render_template('manage_locations.html', presets=presets)

@app.route('/export')
def export_data():
    garments = wq(Garment).filter_by(archived=False).order_by(Garment.created_at.desc()).all()
    data = []
    for g in garments:
        data.append({
            "\u540d\u79f0": g.name, "\u5206\u7c7b": g.category.name if g.category else "",
            "\u54c1\u724c": g.brand_rel.name if g.brand_rel else "", "\u989c\u8272": g.color or "",
            "\u6750\u8d28": g.material or "", "\u5b63\u8282": g.season_group or "", "\u5c3a\u7801": g.size_label or "",
            "\u4ef7\u683c": g.price or "", "\u8d2d\u4e70\u65e5\u671f": str(g.purchase_date) if g.purchase_date else "",
            "\u4f4d\u7f6e": format_storage_location(g),
            "\u5907\u6ce8": g.notes or "",
        })
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("\u6570\u636e.json", json.dumps(data, ensure_ascii=False, indent=2))
        uploads = app.config['UPLOAD_FOLDER']
        for g in garments:
            for fn in [g.photo, g.thumbnail]:
                if fn:
                    fp = os.path.join(uploads, fn)
                    if os.path.exists(fp): zf.write(fp, f"\u7167\u7247/{fn}")
    buf.seek(0)
    date_str = datetime.utcnow().strftime("%Y%m%d")
    return Response(buf.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=wardrobe_backup_{date_str}.zip"})

@app.route('/uploads/<path:fn>')
@login_required
def uploaded_file(fn):
    # 权限检查：通过照片文件名查找衣物，验证衣橱归属
    w = current_wardrobe()
    if w:
        g = wq(Garment).filter(
            db.or_(Garment.photo == fn, Garment.thumbnail == fn)
        ).first()
        if g:
            return send_from_directory(app.config['UPLOAD_FOLDER'], fn)
    abort(404)

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js')

@app.route('/healthz')
def healthz():
    status = {"status": "ok", "app_version": "1.3.0"}
    try:
        db.session.execute(db.text("SELECT 1"))
        status["database"] = "ok"
        status["database_writable"] = True
        # 尝试读取 schema revision
        try:
            rev = db.session.execute(db.text("SELECT version_num FROM alembic_version")).scalar()
            status["schema"] = rev
        except Exception:
            status["schema"] = "unknown"
    except Exception as e:
        status["database"] = str(e)
        status["database_writable"] = False
        return status, 500
    data_path = app.config.get('DATA_PATH', '')
    status["data_path"] = "ok" if data_path and os.path.isdir(data_path) else "missing"
    # Storage ID
    try:
        ok, sid = verify_storage_id()
        status["storage"] = "ok" if ok else "mismatch"
    except Exception:
        status["storage"] = "error"
    return status

# ========== v1.3 维护模式 ==========

@app.route('/maintenance/status')
@login_required
@admin_required
def maintenance_status():
    return {'maintenance': is_maintenance_mode()}

@app.route('/maintenance/enable', methods=['POST'])
@login_required
@admin_required
def maintenance_enable():
    open(_MAINTENANCE_FILE, 'w').close()
    return redirect(url_for('manage_system'))

@app.route('/maintenance/disable', methods=['POST'])
@login_required
@admin_required
def maintenance_disable():
    if os.path.exists(_MAINTENANCE_FILE):
        os.remove(_MAINTENANCE_FILE)
    return redirect(url_for('manage_system'))

# ========== v1.3 管理员系统状态页面 ==========

@app.route('/manage/system')
@login_required
@admin_required
def manage_system():
    db_path = os.path.join(_data_path, 'db', 'wardrobe.sqlite3')
    media_dir = app.config['UPLOAD_FOLDER']
    
    # 统计
    total_garments = Garment.query.count()
    active_g = active_garments().count()
    trashed_g = trashed_garments().count()
    
    # 媒体文件
    originals = thumbnails = orphans = missing = 0
    if os.path.isdir(media_dir):
        for root, dirs, files in os.walk(media_dir):
            for fn in files:
                if fn.startswith('thumb_'): thumbnails += 1
                elif not fn.startswith('tmp_'): originals += 1
    
    # 最近备份
    bdir = app.config['BACKUP_FOLDER']
    latest_backup = None
    if os.path.isdir(bdir):
        backups = sorted([f for f in os.listdir(bdir) if f.startswith('system_backup_') and f.endswith('.tar.gz')], reverse=True)
        if backups:
            latest_backup = {'name': backups[0], 'mtime': datetime.fromtimestamp(os.path.getmtime(os.path.join(bdir, backups[0])))}
    
    # 磁盘空间
    import shutil
    disk = shutil.disk_usage(_data_path)
    
    # maintenance
    maint = is_maintenance_mode()
    
    # schema
    try:
        rev = db.session.execute(db.text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        rev = 'unknown'
    
    return render_template('manage_system.html',
        total_garments=total_garments, active_g=active_g, trashed_g=trashed_g,
        user_count=User.query.count(), wardrobe_count=Wardrobe.query.count(),
        originals=originals, thumbnails=thumbnails,
        orphans=orphans, missing=missing,
        latest_backup=latest_backup, disk=disk,
        maintenance=maint, schema_rev=rev)

# ========== v1.3 审计日志 ==========

@app.route('/manage/audit')
@login_required
@admin_required
def manage_audit():
    page = request.args.get('page', 1, type=int)
    action_filter = request.args.get('action', '')
    uid_filter = request.args.get('user_id', type=int)
    
    query = AuditLog.query
    if action_filter:
        query = query.filter_by(action=action_filter)
    if uid_filter:
        query = query.filter_by(actor_user_id=uid_filter)
    
    logs = query.order_by(AuditLog.created_at.desc()).limit(100).offset((page-1)*100).all()
    actions = [r[0] for r in db.session.query(AuditLog.action).distinct().all()]
    return render_template('manage_audit.html', logs=logs, actions=actions,
                          action_filter=action_filter, uid_filter=uid_filter, page=page)

# ========== v1.3 衣橱选择页 ==========

@app.route('/wardrobes/switch', methods=['GET', 'POST'])
@login_required
def wardrobe_switch_page():
    if request.method == 'POST':
        return _do_wardrobe_switch()
    memberships = WardrobeMember.query.filter_by(user_id=current_user.id).all()
    wardrobes = [m.wardrobe for m in memberships if m.wardrobe and m.wardrobe.is_active]
    return render_template('switch.html', wardrobes=wardrobes)

@app.route('/wardrobe/switch', methods=['POST'])
@login_required
def _do_wardrobe_switch():
    wid = request.form.get('wardrobe_id', type=int)
    if wid:
        w = db.session.get(Wardrobe, wid)
        if w and w.is_active:
            m = WardrobeMember.query.filter_by(wardrobe_id=wid, user_id=current_user.id).first()
            if m:
                session.pop('current_wardrobe_id', None)
                # 清除旧筛选
                for k in list(session.keys()):
                    if k.startswith('filter_') or k.startswith('page_'):
                        session.pop(k, None)
                session['current_wardrobe_id'] = wid
                AuditLog.log('wardrobe.switch', wardrobe_id=wid, summary=f'切换到: {w.name}')
                flash(f'已切换到：{w.name}')
    return redirect(request.referrer or url_for('index'))

# ========== v1.3 账号安全 ==========

@app.route('/account/sessions')
@login_required
def account_sessions():
    return render_template('account_sessions.html')

@app.route('/account/sessions/revoke-others', methods=['POST'])
@login_required
def revoke_other_sessions():
    current_user.session_version = (current_user.session_version or 0) + 1
    AuditLog.log('user.sessions_revoked', summary=f'{current_user.username} 撤销其他会话')
    db.session.commit()
    flash('其他设备会话已失效')
    return redirect(url_for('account_sessions'))

# ========== v1.3 批量操作 ==========

@app.route('/garments/batch', methods=['POST'])
@login_required
def garment_batch():
    w = current_wardrobe()
    if not w: abort(404)
    ids = [int(x) for x in request.form.get('ids', '').split(',') if x.strip().isdigit()]
    action = request.form.get('batch_action', '')
    if not ids or not action:
        flash('请选择衣物和操作')
        return redirect(url_for('garment_list'))
    
    # 全部属于当前衣橱
    valid = Garment.query.filter(Garment.id.in_(ids), Garment.wardrobe_id == w.id, Garment.deleted_at == None).all()
    if len(valid) != len(ids):
        flash('部分衣物不属于当前衣橱，已拒绝')
        return redirect(url_for('garment_list'))
    
    count = 0
    field_map = {
        'category': ('category_id', int), 'brand': ('brand_id', int),
        'season': ('season_group', str), 'status': ('status', str),
        'location': ('location_preset_id', int),
    }
    
    if action in field_map:
        field, cast = field_map[action]
        val = request.form.get(f'batch_{action}')
        if val is not None and val != '':
            val = cast(val)
            for g in valid:
                setattr(g, field, val)
                count += 1
    elif action == 'archive':
        for g in valid: g.archived = True; count += 1
    elif action == 'trash':
        for g in valid: g.deleted_at = datetime.utcnow(); g.deleted_by_user_id = current_user.id; count += 1
    
    if count:
        AuditLog.log('garment.batch', wardrobe_id=w.id, target_type='Garment',
                     summary=f'批量{action}: {count}件', meta={'ids': ids, 'action': action})
    db.session.commit()
    flash(f'成功修改 {count} 件衣物')
    return redirect(url_for('garment_list'))

# ========== v1.3 purge-trash CLI ==========

@app.cli.command("purge-trash")
def purge_trash():
    """清理超过N天的回收站记录"""
    days = 30
    import sys as _sys
    for a in _sys.argv:
        if a.startswith('--older-than-days='):
            days = int(a.split('=')[1])
    cutoff = datetime.utcnow() - __import__('datetime').timedelta(days=days)
    count = 0
    for g in Garment.query.filter(Garment.deleted_at.isnot(None), Garment.deleted_at < cutoff).all():
        db.session.delete(g); count += 1
    if count:
        db.session.commit()
        print(f"已永久删除 {count} 件超过 {days} 天的回收站衣物")
    else:
        print(f"没有超过 {days} 天的回收站记录")

@app.cli.command("check-data-integrity")
def check_data_integrity():
    """只读检查数据一致性"""
    import sys as _sys
    as_json = '--json' in _sys.argv
    report = {'database': {}, 'media': {}}
    
    # DB 检查
    report['database']['garments'] = Garment.query.count()
    report['database']['active'] = Garment.query.filter_by(deleted_at=None).count()
    report['database']['trashed'] = Garment.query.filter(Garment.deleted_at.isnot(None)).count()
    
    # 外键检查
    orphan_cats = Garment.query.filter(Garment.category_id.isnot(None)).filter(~Garment.category_id.in_(db.session.query(Category.id))).count()
    orphan_brands = Garment.query.filter(Garment.brand_id.isnot(None)).filter(~Garment.brand_id.in_(db.session.query(Brand.id))).count()
    report['database']['orphan_category_refs'] = orphan_cats
    report['database']['orphan_brand_refs'] = orphan_brands
    
    # 媒体检查
    media_dir = app.config['UPLOAD_FOLDER']
    db_photos = set()
    for g in Garment.query.all():
        if g.photo: db_photos.add(g.photo)
        if g.thumbnail: db_photos.add(g.thumbnail)
    
    disk_files = set()
    if os.path.isdir(media_dir):
        for root, dirs, files in os.walk(media_dir):
            for fn in files:
                disk_files.add(os.path.relpath(os.path.join(root, fn), media_dir))
    
    missing = db_photos - disk_files
    orphaned = disk_files - db_photos
    tmp_files = {f for f in disk_files if f.startswith('tmp_')}
    
    report['media']['total_db_refs'] = len(db_photos)
    report['media']['total_disk_files'] = len(disk_files)
    report['media']['missing_files'] = len(missing)
    report['media']['orphan_files'] = len(orphaned)
    report['media']['tmp_files'] = len(tmp_files)
    
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("数据一致性检查报告")
        print(f"  数据库: {report['database']['garments']} 衣物 ({report['database']['active']}活跃, {report['database']['trashed']}回收站)")
        print(f"  外键: 孤立分类引用={orphan_cats}, 孤立品牌引用={orphan_brands}")
        print(f"  媒体: 引用{len(db_photos)}文件, 磁盘{len(disk_files)}文件")
        print(f"  缺失: {len(missing)} 引用文件不存在")
        print(f"  孤立: {len(orphaned)} 磁盘文件无引用")
        print(f"  临时: {len(tmp_files)} tmp文件")
        if missing:
            print(f"  ⚠️ 缺失文件: {' '.join(sorted(list(missing))[:10])}")
        if orphaned:
            print(f"  ⚠️ 孤立文件: {' '.join(sorted(list(orphaned))[:10])}")

@app.cli.command("repair-thumbnails")
def repair_thumbnails():
    """根据原图重新生成缺失的缩略图"""
    media_dir = app.config['UPLOAD_FOLDER']
    fixed = 0
    for g in Garment.query.filter(Garment.photo.isnot(None)).all():
        if g.photo and (not g.thumbnail or not os.path.exists(os.path.join(media_dir, g.thumbnail))):
            src = os.path.join(media_dir, g.photo)
            if os.path.exists(src):
                try:
                    img = Image.open(src).convert('RGB')
                    img.thumbnail((400, 400), Image.LANCZOS)
                    thumb_fn = f"thumb_{os.path.splitext(g.photo)[0]}.webp"
                    tmp_path = os.path.join(app.config['TMP_FOLDER'], thumb_fn)
                    final_path = os.path.join(media_dir, thumb_fn)
                    img.save(tmp_path, 'WEBP', quality=80)
                    os.rename(tmp_path, final_path)
                    g.thumbnail = thumb_fn
                    fixed += 1
                except Exception as e:
                    print(f"  ❌ {g.photo}: {e}")
    if fixed:
        db.session.commit()
        print(f"✅ 已修复 {fixed} 个缩略图")
    else:
        print("所有缩略图正常，无需修复")

# ========== CLI 命令 ==========

@app.cli.command("preflight")
def preflight_cmd():
    """启动前检查：验证数据目录、数据库、Storage ID"""
    ensure_data_dirs()
    ok, msg = preflight_check()
    if ok:
        print(f"✅ 预检通过: {msg}")
    else:
        print(f"❌ 预检失败: {msg}")
        raise SystemExit(1)

@app.cli.command("install-new-instance")
def install_new_instance():
    """全新安装：创建数据库、运行迁移、初始化默认数据。仅在数据库不存在时可用。"""
    db_path = os.path.join(_data_path, 'db', 'wardrobe.sqlite3')
    if os.path.exists(db_path):
        print(f"❌ 数据库已存在: {db_path}")
        print("   如需重新安装，请先备份并手动删除数据库文件。")
        raise SystemExit(1)
    # 确认
    print(f"将在以下位置创建新数据库:")
    print(f"   {db_path}")
    print(f"   DATA_PATH: {_data_path}")
    confirm = input("确认创建？(yes/no): ").strip().lower()
    if confirm != 'yes':
        print("已取消")
        return
    # 创建目录
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    ensure_data_dirs()
    # 创建 storage ID
    ok, sid = verify_storage_id()
    print(f"Storage ID: {sid[:8]}...")
    # 创建所有表
    db.create_all()
    # 初始化 Alembic 版本
    with app.app_context():
        migrate_stamp(revision='head')
    # 初始化默认数据
    for icon, name, order in DEFAULT_CATEGORIES:
        db.session.add(Category(name=name, icon=icon, sort_order=order))
    for name, order in DEFAULT_BRANDS:
        db.session.add(Brand(name=name, sort_order=order))
    db.session.commit()
    print(f"✅ 新实例已创建: {db_path}")
    print(f"   请设置环境变量 EXPECTED_STORAGE_ID={sid}")

@app.cli.command("backup-system")
def backup_system():
    """系统级备份：数据库(SQLite Backup API) + 媒体文件 → tar.gz"""
    import tarfile, shutil
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_name = f"system_backup_{ts}.tar.gz"
    tmp_path = os.path.join(app.config['BACKUP_FOLDER'], f".tmp_{backup_name}")
    final_path = os.path.join(app.config['BACKUP_FOLDER'], backup_name)
    os.makedirs(app.config['BACKUP_FOLDER'], exist_ok=True)

    db_path = os.path.join(_data_path, 'db', 'wardrobe.sqlite3')
    media_dir = app.config['UPLOAD_FOLDER']

    # 统计
    with app.app_context():
        garment_count = Garment.query.count()
        user_count = User.query.count()
        wardrobe_count = Wardrobe.query.count()
        cat_count = Category.query.count()
        brand_count = Brand.query.count()

    # 媒体文件统计
    originals = []
    thumbnails = []
    if os.path.isdir(media_dir):
        for root, dirs, files in os.walk(media_dir):
            for fn in files:
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, media_dir)
                if fn.startswith('thumb_'):
                    thumbnails.append(rel)
                elif not fn.startswith('tmp_'):
                    originals.append(rel)

    manifest = {
        "backup_version": 1,
        "backup_type": "system",
        "created_at": datetime.utcnow().isoformat(),
        "app_version": "1.3.0",
        "schema_revision": _get_alembic_rev(),
        "installation_id": _read_storage_id(),
        "database_sha256": "",
        "user_count": user_count,
        "wardrobe_count": wardrobe_count,
        "garment_count": garment_count,
        "category_count": cat_count,
        "brand_count": brand_count,
        "original_count": len(originals),
        "thumbnail_count": len(thumbnails),
        "files": {},
    }

    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            # 1. SQLite 一致性备份（使用 Backup API）
            tmp_db = os.path.join(app.config['TMP_FOLDER'], f"backup_db_{ts}.sqlite3")
            os.makedirs(app.config['TMP_FOLDER'], exist_ok=True)
            if os.path.exists(db_path):
                import sqlite3
                src = sqlite3.connect(db_path)
                dst = sqlite3.connect(tmp_db)
                src.backup(dst)
                src.close(); dst.close()
                # 校验备份数据库
                vconn = sqlite3.connect(tmp_db)
                integrity = vconn.execute("PRAGMA integrity_check").fetchone()[0]
                vconn.close()
                if integrity != 'ok':
                    raise RuntimeError(f"数据库完整性检查失败: {integrity}")
                # 加入 tar
                tar.add(tmp_db, arcname="database/wardrobe.sqlite3")
                with open(tmp_db, "rb") as f:
                    manifest["database_sha256"] = hashlib.sha256(f.read()).hexdigest()
                os.remove(tmp_db)

            # 2. 媒体文件
            if os.path.isdir(media_dir):
                for root, dirs, files in os.walk(media_dir):
                    for fn in files:
                        fp = os.path.join(root, fn)
                        rel = os.path.relpath(fp, media_dir)
                        if rel.startswith('tmp_'):
                            continue  # 跳过临时文件
                        arc = os.path.join("media", rel)
                        tar.add(fp, arcname=arc)
                        with open(fp, "rb") as f:
                            manifest["files"][arc] = {
                                "sha256": hashlib.sha256(f.read()).hexdigest(),
                                "size": os.path.getsize(fp),
                            }

            # 3. Manifest
            manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)
            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(manifest_json.encode("utf-8"))
            tar.addfile(info, io.BytesIO(manifest_json.encode("utf-8")))

        # 原子重命名
        if os.path.exists(final_path):
            os.remove(final_path)
        os.rename(tmp_path, final_path)

        size_mb = os.path.getsize(final_path) / (1024 * 1024)
        print(f"✅ 系统备份完成: {backup_name}")
        print(f"   大小: {size_mb:.1f} MB")
        print(f"   数据库: {garment_count} 衣物, {user_count} 用户, {wardrobe_count} 衣橱")
        print(f"   媒体: {len(originals) + len(thumbnails)} 文件")
        print(f"   ⚠️  提醒: 同盘备份无法抵御磁盘损坏，请定期复制到其他设备。")
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        print(f"❌ 备份失败: {e}")
        raise SystemExit(1)

@app.cli.command("list-backups")
def list_backups():
    """列出所有系统备份"""
    bdir = app.config['BACKUP_FOLDER']
    if not os.path.isdir(bdir):
        print("暂无备份")
        return
    files = sorted([f for f in os.listdir(bdir) if f.startswith('system_backup_') and f.endswith('.tar.gz')], reverse=True)
    if not files:
        print("暂无备份")
        return
    print(f"{'备份文件':<45} {'大小':>8} {'创建时间':<22}")
    print("-" * 80)
    for f in files:
        fp = os.path.join(bdir, f)
        size = os.path.getsize(fp)
        mtime = datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S")
        unit = "KB"
        sz = size / 1024
        if sz > 1024:
            sz /= 1024; unit = "MB"
        print(f"{f:<45} {sz:>7.1f}{unit} {mtime:<22}")
    print(f"\n共 {len(files)} 个备份，位于 {bdir}")

@app.cli.command("verify-backup")
def verify_backup():
    """验证备份文件完整性（默认最新，可指定文件名）"""
    import tarfile as tf, sys as _sys
    bdir = app.config['BACKUP_FOLDER']
    target = _sys.argv[-1] if len(_sys.argv) > 2 and _sys.argv[-2] == 'verify-backup' else None
    if target and not target.endswith('.tar.gz'):
        target = None
    if target:
        bp = os.path.join(bdir, target) if not os.path.isabs(target) else target
    else:
        files = sorted([f for f in os.listdir(bdir) if f.startswith('system_backup_') and f.endswith('.tar.gz')])
        if not files:
            print("❌ 没有找到备份文件"); return
        bp = os.path.join(bdir, files[-1])
    if not os.path.exists(bp):
        print(f"❌ 备份文件不存在: {bp}"); return

    print(f"验证: {os.path.basename(bp)}")
    ok = 0; fail = 0
    try:
        with tf.open(bp, "r:gz") as tar:
            # 读取 manifest
            try:
                mf = tar.extractfile("manifest.json")
                manifest = json.loads(mf.read().decode('utf-8'))
            except Exception:
                print("❌ 无法读取 manifest.json"); return

            print(f"   版本: {manifest.get('app_version','?')}  衣橱: {manifest.get('wardrobe_count','?')}")
            print(f"   衣物: {manifest.get('garment_count','?')}  用户: {manifest.get('user_count','?')}")

            files_entry = manifest.get('files', {})
            names = tar.getnames()

            # 校验 manifest 中的 SHA256
            for arc, info in files_entry.items():
                expected = info.get('sha256', '') if isinstance(info, dict) else info
                if arc not in names:
                    print(f"   ❌ 缺失: {arc}"); fail += 1; continue
                fobj = tar.extractfile(arc)
                if fobj:
                    actual = hashlib.sha256(fobj.read()).hexdigest()
                    fobj.close()
                    if actual != expected:
                        print(f"   ❌ 校验失败: {arc}")
                        fail += 1
                    else:
                        ok += 1

            # 校验数据库文件
            if 'database/wardrobe.sqlite3' in names:
                expected_db = manifest.get('database_sha256', '')
                if expected_db:
                    fobj = tar.extractfile('database/wardrobe.sqlite3')
                    actual = hashlib.sha256(fobj.read()).hexdigest()
                    fobj.close()
                    if actual == expected_db:
                        print(f"   ✅ 数据库 SHA256 通过")
                        ok += 1
                    else:
                        print(f"   ❌ 数据库 SHA256 不匹配"); fail += 1

        if fail > 0:
            print(f"\n❌ 验证失败: {ok} 通过, {fail} 失败")
            raise SystemExit(1)
        else:
            print(f"\n✅ 验证通过: {ok} 文件校验一致")
    except Exception as e:
        print(f"❌ 验证异常: {e}")
        raise SystemExit(1)

@app.cli.command("restore-system")
def restore_system():
    """从备份恢复系统（破坏性操作，需确认）"""
    import tarfile as tf, sys as _sys, shutil
    bdir = app.config['BACKUP_FOLDER']
    target = _sys.argv[-1] if len(_sys.argv) > 2 and _sys.argv[-2] == 'restore-system' else None
    if target and not target.endswith('.tar.gz'):
        target = None
    if target:
        bp = os.path.join(bdir, target) if not os.path.isabs(target) else target
    else:
        files = sorted([f for f in os.listdir(bdir) if f.startswith('system_backup_') and f.endswith('.tar.gz')])
        if not files:
            print("❌ 没有找到备份文件"); return
        bp = os.path.join(bdir, files[-1])
    if not os.path.exists(bp):
        print(f"❌ 备份文件不存在: {bp}"); return

    print(f"⚠️  即将从备份恢复: {os.path.basename(bp)}")
    print(f"   这将覆盖当前数据库和所有媒体文件！")

    # 1. 校验备份
    print("\n--- 校验备份 ---")
    try:
        with tf.open(bp, "r:gz") as tar:
            names = tar.getnames()
            if 'manifest.json' not in names:
                print("❌ 备份中无 manifest.json，拒绝恢复"); return
            mf = tar.extractfile("manifest.json")
            manifest = json.loads(mf.read().decode('utf-8'))
            mf.close()

            # 校验所有文件
            files_entry = manifest.get('files', {})
            all_ok = True
            for arc, info in files_entry.items():
                expected = info.get('sha256', '') if isinstance(info, dict) else info
                fobj = tar.extractfile(arc)
                if fobj:
                    actual = hashlib.sha256(fobj.read()).hexdigest()
                    fobj.close()
                    if actual != expected:
                        print(f"   ❌ {arc}"); all_ok = False
            if not all_ok:
                print("❌ 备份校验失败，拒绝恢复"); return
            print("   ✅ 全部文件校验通过")
    except Exception as e:
        print(f"❌ 校验异常: {e}"); return

    # 2. 先备份当前状态
    print("\n--- 备份当前状态 ---")
    rescue_name = f"pre_restore_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.tar.gz"
    rescue_path = os.path.join(bdir, rescue_name)
    try:
        import tarfile as _tar
        with _tar.open(rescue_path, "w:gz") as rt:
            db_path = os.path.join(_data_path, 'db', 'wardrobe.sqlite3')
            if os.path.exists(db_path):
                rt.add(db_path, arcname="database/wardrobe.sqlite3")
            media_dir = app.config['UPLOAD_FOLDER']
            if os.path.isdir(media_dir):
                for root, dirs, files in os.walk(media_dir):
                    for fn in files:
                        fp = os.path.join(root, fn)
                        rt.add(fp, arcname=os.path.join("media", os.path.relpath(fp, media_dir)))
        print(f"   ✅ 当前状态已保存到: {rescue_name}")
    except Exception as e:
        print(f"   ⚠️  备份当前状态失败: {e}")
        if input("继续恢复? (yes/no): ").strip().lower() != 'yes':
            return

    # 3. 确认
    print(f"\n恢复后数据库将有:")
    print(f"   衣物: {manifest.get('garment_count','?')}")
    print(f"   用户: {manifest.get('user_count','?')}")
    confirm = input("\n确认恢复？输入 yes 继续: ").strip().lower()
    if confirm != 'yes':
        print("已取消"); return

    # 4. 恢复到临时目录
    print("\n--- 恢复中 ---")
    tmp_restore = os.path.join(app.config['TMP_FOLDER'], f"restore_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    os.makedirs(tmp_restore, exist_ok=True)
    try:
        with tf.open(bp, "r:gz") as tar:
            tar.extractall(tmp_restore)

        # 校验恢复后的数据库
        tmp_db = os.path.join(tmp_restore, "database", "wardrobe.sqlite3")
        if os.path.exists(tmp_db):
            import sqlite3
            vconn = sqlite3.connect(tmp_db)
            integrity = vconn.execute("PRAGMA integrity_check").fetchone()[0]
            vconn.close()
            if integrity != 'ok':
                raise RuntimeError(f"恢复后数据库校验失败: {integrity}")
            print(f"   ✅ 数据库 integrity_check: ok")

        # 5. 原子替换
        db_dest = os.path.join(_data_path, 'db', 'wardrobe.sqlite3')
        reserved_db = os.path.join(_data_path, 'db', f".replaced_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.sqlite3")
        if os.path.exists(db_dest):
            os.rename(db_dest, reserved_db)
            print(f"   📦 旧数据库保留为: {os.path.basename(reserved_db)}")

        # 复制数据库
        if os.path.exists(tmp_db):
            shutil.copy2(tmp_db, db_dest)

        # 复制媒体文件
        tmp_media = os.path.join(tmp_restore, "media")
        if os.path.isdir(tmp_media):
            for root, dirs, files in os.walk(tmp_media):
                for fn in files:
                    src = os.path.join(root, fn)
                    rel = os.path.relpath(src, tmp_media)
                    dst = os.path.join(app.config['UPLOAD_FOLDER'], rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)

    except Exception as e:
        print(f"❌ 恢复失败: {e}")
        raise SystemExit(1)
    finally:
        if os.path.isdir(tmp_restore):
            shutil.rmtree(tmp_restore, ignore_errors=True)

    print(f"\n✅ 恢复完成！")
    print(f"   请重启应用以加载恢复的数据。")
    print(f"   如需回滚，旧数据库位于: {os.path.basename(reserved_db) if os.path.exists(reserved_db) else 'N/A'}")

@app.cli.command("bootstrap-multiuser")
def bootstrap_multiuser():
    """v1.0 → v1.1 数据迁移：创建初始用户和默认衣橱，迁移现有数据"""
    import shutil, re
    print("=" * 60)
    print("Samantha的衣橱 — v1.0 → v1.1 多用户迁移")
    print("=" * 60)

    # 1. 检查是否已有用户
    if User.query.count() > 0:
        print("\n⚠️  已存在用户，迁移可能已执行过。")
        r = input("继续？(y/N): ").strip().lower()
        if r != 'y':
            print("已取消。")
            return

    # 2. 交互式创建管理员
    print("\n--- 创建初始管理员 ---")
    uname = input("用户名 [Samantha]: ").strip() or "Samantha"
    dname = input("显示名称 [Samantha]: ").strip() or uname
    while True:
        pw = input("密码: ").strip()
        if len(pw) < 4:
            print("密码至少 4 个字符")
            continue
        pw2 = input("确认密码: ").strip()
        if pw != pw2:
            print("两次密码不一致")
            continue
        break

    # 3. 创建 User
    admin = User(
        username=uname,
        display_name=dname,
        password_hash=generate_password_hash(pw),
        is_system_admin=True,
    )
    db.session.add(admin)
    db.session.flush()
    print(f"✅ 用户创建: {uname} (id={admin.id})")

    # 4. 创建默认 Wardrobe
    wardrobe = Wardrobe(
        name="Wardrobe",
        owner_user_id=admin.id,
    )
    db.session.add(wardrobe)
    db.session.flush()
    print(f"✅ 衣橱创建: {wardrobe.name} (id={wardrobe.id})")

    # 5. 创建 owner 成员关系
    member = WardrobeMember(
        wardrobe_id=wardrobe.id,
        user_id=admin.id,
        role='owner',
    )
    db.session.add(member)

    # 6. 迁移现有数据到默认衣橱
    print("\n--- 迁移现有数据 ---")
    wid = wardrobe.id

    # 6.1 分类
    cats = Category.query.filter(Category.wardrobe_id == None).all()
    for c in cats:
        c.wardrobe_id = wid
    print(f"   分类: {len(cats)} 条已归属")

    # 6.2 品牌
    brands = Brand.query.filter(Brand.wardrobe_id == None).all()
    for b in brands:
        b.wardrobe_id = wid
    print(f"   品牌: {len(brands)} 条已归属")

    # 6.3 颜色预设
    colors = ColorPreset.query.filter(ColorPreset.wardrobe_id == None).all()
    for c in colors:
        c.wardrobe_id = wid
    print(f"   颜色: {len(colors)} 条已归属")

    # 6.4 位置预设
    locs = LocationPreset.query.filter(LocationPreset.wardrobe_id == None).all()
    for l in locs:
        l.wardrobe_id = wid
    print(f"   位置: {len(locs)} 条已归属")

    # 6.5 衣物
    gs = Garment.query.filter(Garment.wardrobe_id == None).all()
    for g in gs:
        g.wardrobe_id = wid
        g.created_by_user_id = admin.id
    print(f"   衣物: {len(gs)} 条已归属")

    db.session.commit()

    # 7. 迁移照片到衣橱目录
    print("\n--- 迁移照片 ---")
    media_dir = app.config['UPLOAD_FOLDER']
    wardrobe_media = os.path.join(media_dir, 'wardrobes', str(wid))
    os.makedirs(os.path.join(wardrobe_media, 'originals'), exist_ok=True)
    os.makedirs(os.path.join(wardrobe_media, 'thumbnails'), exist_ok=True)

    photo_count = 0
    for g in Garment.query.filter_by(wardrobe_id=wid).all():
        # 直接移动旧文件到新目录
        for field, subdir in [('photo', 'originals'), ('thumbnail', 'thumbnails')]:
            old_fn = getattr(g, field)
            if not old_fn:
                continue
            old_path = os.path.join(media_dir, old_fn)
            if os.path.exists(old_path):
                new_path = os.path.join(wardrobe_media, subdir, old_fn)
                if not os.path.exists(new_path):
                    shutil.copy2(old_path, new_path)
                setattr(g, field, f"wardrobes/{wid}/{subdir}/{old_fn}")
                photo_count += 1
    db.session.commit()
    print(f"   照片/缩略图: {photo_count} 个已迁移")

    # 8. 输出迁移报告
    print("\n" + "=" * 60)
    print("✅ 迁移完成！")
    print(f"   管理员: {uname} (id={admin.id})")
    print(f"   衣橱: {wardrobe.name} (id={wardrobe.id})")
    print(f"   分类: {len(cats)} | 品牌: {len(brands)} | 颜色: {len(colors)} | 位置: {len(locs)}")
    print(f"   衣物: {len(gs)} | 照片: {photo_count}")
    print("=" * 60)

@app.cli.command("seed-defaults")
def seed_defaults():
    """为指定衣橱初始化默认分类和品牌"""
    wid = int(input("衣橱ID: ").strip())
    w = db.session.get(Wardrobe, wid)
    if not w:
        print(f"❌ 衣橱 {wid} 不存在")
        return
    
    # 默认分类
    exists = Category.query.filter_by(wardrobe_id=wid).count()
    if exists > 0:
        r = input(f"衣橱 '{w.name}' 已有 {exists} 个分类，继续添加默认数据？(y/N): ").strip().lower()
        if r != 'y':
            print("已取消")
            return
    
    for icon, name, order in DEFAULT_CATEGORIES:
        if not Category.query.filter_by(wardrobe_id=wid, name=name).first():
            db.session.add(Category(wardrobe_id=wid, name=name, icon=icon, sort_order=order))
    
    for name, order in DEFAULT_BRANDS:
        if not Brand.query.filter_by(wardrobe_id=wid, name=name).first():
            db.session.add(Brand(wardrobe_id=wid, name=name, sort_order=order))
    
    db.session.commit()
    print(f"✅ 已为衣橱 '{w.name}' (id={wid}) 初始化默认分类和品牌")

# 开发入口（仅本地调试使用，生产始终使用 Gunicorn）
if __name__ == '__main__':
    import sys
    if '--prod' in sys.argv:
        print("生产环境请使用 Gunicorn: gunicorn -b 0.0.0.0:3000 app:app")
    else:
        print("⚠️ 调试模式启动（仅开发使用）")
        app.run(host='127.0.0.1', port=5000, debug=False)
