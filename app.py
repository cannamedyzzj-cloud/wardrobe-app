#!/usr/bin/env python3
"""Samantha的衣橱"""
import json, io, zipfile, os, uuid, base64
from datetime import datetime
from collections import Counter
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, Response
from flask_sqlalchemy import SQLAlchemy
from PIL import Image

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.environ.get('DATA_PATH', './data')}/wardrobe.db"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(os.environ.get('DATA_PATH', './data'), 'uploads')
db = SQLAlchemy(app)

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(10), default='\U0001f454')
    sort_order = db.Column(db.Integer, default=0)
    garments = db.relationship('Garment', backref='category', lazy='dynamic')

class Brand(db.Model):
    __tablename__ = 'brands'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    garments = db.relationship('Garment', backref='brand_rel', lazy='dynamic')

class ColorPreset(db.Model):
    __tablename__ = 'color_presets'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    sort_order = db.Column(db.Integer, default=0)

class LocationPreset(db.Model):
    __tablename__ = 'location_presets'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    room = db.Column(db.String(100))
    position = db.Column(db.String(100))
    sort_order = db.Column(db.Integer, default=0)
    garments = db.relationship('Garment', backref='location_preset', lazy='dynamic')

class Garment(db.Model):
    __tablename__ = 'garments'
    id = db.Column(db.Integer, primary_key=True)
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

DEFAULT_CATEGORIES = [('\U0001f455','\u4e0a\u8863',1),('\U0001f456','\u88e4\u5b50',2),('\U0001f457','\u88d9\u5b50',3),('\U0001f9e5','\u5916\u5957',4),('\U0001f9e3','\u914d\u9970',5)]
DEFAULT_BRANDS = [('\u4f18\u8863\u5e93',1),('ZARA',2),('H&M',3),('\u65e0\u54c1\u724c',4)]

def init_db():
    db.create_all()
    if Category.query.count() == 0:
        for icon, name, order in DEFAULT_CATEGORIES:
            db.session.add(Category(name=name, icon=icon, sort_order=order))
    if Brand.query.count() == 0:
        for name, order in DEFAULT_BRANDS:
            db.session.add(Brand(name=name, sort_order=order))
    db.session.commit()

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

# ========== Routes ==========

@app.route('/')
def index():
    categories = Category.query.order_by(Category.sort_order).all()
    total = Garment.query.filter_by(archived=False).count()
    cat_counts = {c.id: Garment.query.filter_by(category_id=c.id, archived=False).count() for c in categories}
    season_stats = {sg: Garment.query.filter_by(archived=False, season_group=sg).count() for sg in ['\u590f\u5b63','\u51ac\u5b63','\u6625\u79cb\u5b63']}
    out_count = Garment.query.filter_by(archived=False).filter(Garment.status != '\u5728\u5e93').count()
    m = datetime.utcnow().month
    current_season = '\u590f\u5b63' if m in [5,6,7,8,9] else ('\u51ac\u5b63' if m in [12,1,2] else '\u6625\u79cb\u5b63')
    recent = Garment.query.filter_by(archived=False).order_by(Garment.created_at.desc()).limit(8).all()
    return render_template('index.html', categories=categories, total=total, out_count=out_count,
                          cat_counts=cat_counts, season_stats=season_stats, current_season=current_season,
                          recent=recent, format_location=format_storage_location)

@app.route('/garments')
def garment_list():
    query = Garment.query.filter_by(archived=False)
    if cid := request.args.get('category', type=int): query = query.filter_by(category_id=cid)
    if sg := request.args.get('season'): query = query.filter_by(season_group=sg)
    if lid := request.args.get('location', type=int): query = query.filter_by(location_preset_id=lid)
    if bid := request.args.get('brand', type=int): query = query.filter_by(brand_id=bid)
    if st := request.args.get('status'): query = query.filter_by(status=st)
    if s := request.args.get('search', ''): query = query.filter(
        db.or_(Garment.name.ilike(f'%{s}%'), Garment.color.ilike(f'%{s}%'), Garment.notes.ilike(f'%{s}%')))
    garments = query.order_by(Garment.created_at.desc()).all()
    return render_template('list.html', garments=garments,
                          categories=Category.query.order_by(Category.sort_order).all(),
                          location_presets=LocationPreset.query.order_by(LocationPreset.sort_order).all(),
                          brands=Brand.query.order_by(Brand.sort_order).all(),
                          current_category=cid, current_season=sg, current_location=lid, current_brand=bid,
                          current_search=s or '', format_location=format_storage_location)

@app.route('/garments/<int:id>')
def garment_detail(id):
    return render_template('detail.html', garment=Garment.query.get_or_404(id), format_location=format_storage_location)

def _save_garment(garment):
    garment.name = request.form.get('name','')
    # 分类：支持输入新分类
    cname = request.form.get('category_text', '').strip()
    if cname:
        cat = Category.query.filter_by(name=cname).first()
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
        brand = Brand.query.filter_by(name=bname).first()
        if not brand:
            mo = db.session.query(db.func.max(Brand.sort_order)).scalar() or 0
            brand = Brand(name=bname, sort_order=mo+1)
            db.session.add(brand)
            db.session.flush()
        garment.brand_id = brand.id
    else:
        garment.brand_id = request.form.get('brand_id', type=int)
    # 自动保存颜色预设
    if garment.color and garment.color.strip():
        cn = garment.color.strip()
        if not ColorPreset.query.filter_by(name=cn).first():
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
    return render_template('form.html', garment=None, color_presets=ColorPreset.query.order_by(ColorPreset.sort_order).all(),
                          categories=Category.query.order_by(Category.sort_order).all(),
                          location_presets=LocationPreset.query.order_by(LocationPreset.sort_order).all(),
                          brands=Brand.query.order_by(Brand.sort_order).all(), mode='new')

@app.route('/garments/<int:id>/edit', methods=['GET','POST'])
def garment_edit(id):
    g = Garment.query.get_or_404(id)
    if request.method == 'POST':
        _save_garment(g); g.updated_at = datetime.utcnow(); db.session.commit()
        return redirect(url_for('garment_detail', id=g.id))
    return render_template('form.html', garment=g, color_presets=ColorPreset.query.order_by(ColorPreset.sort_order).all(),
                          categories=Category.query.order_by(Category.sort_order).all(),
                          location_presets=LocationPreset.query.order_by(LocationPreset.sort_order).all(),
                          brands=Brand.query.order_by(Brand.sort_order).all(), mode='edit')

@app.route('/garments/<int:id>/delete', methods=['POST'])
def garment_delete(id):
    db.session.delete(Garment.query.get_or_404(id)); db.session.commit()
    return redirect(url_for('garment_list'))

@app.route('/garments/<int:id>/clone', methods=['POST'])
def garment_clone(id):
    o = Garment.query.get_or_404(id)
    c = Garment(name=f"{o.name} (\u526f\u672c)", category_id=o.category_id, brand_id=o.brand_id,
                location_preset_id=o.location_preset_id, color=o.color, material=o.material,
                season_group=o.season_group, price=o.price, size_label=o.size_label, notes=o.notes)
    db.session.add(c); db.session.commit()
    return redirect(url_for('garment_edit', id=c.id))

@app.route('/garments/<int:id>/status', methods=['POST'])
def garment_status(id):
    g = Garment.query.get_or_404(id)
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
        cats = Category.query.order_by(Category.sort_order).all()
        cid, score = match_category(ai_result, cats)
        if cid and score > 10:
            cat = Category.query.get(cid)
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
            cats = Category.query.order_by(Category.sort_order).all()
            cid = None
            ai_name = ''
            if ai_result and len(ai_result) > 0:
                cid, _ = match_category(ai_result, cats)
                ai_name = ai_result[0]['name']
            candidates = Garment.query.filter_by(archived=False)
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
                           'box': g.location_preset.position if g.location_preset else ''}
                })
            
            # 准备智能录入数据（不管是否匹配都准备好）
            matched_cat = None
            if ai_result and len(ai_result) > 0:
                cid2, score2 = match_category(ai_result, cats)
                if cid2 and score2 > 10:
                    cat = Category.query.get(cid2)
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
        g.name = request.form.get('name', '未命名')
        g.category_id = request.form.get('category_id', type=int) or (Category.query.first().id if Category.query.first() else None)
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
            brand = Brand.query.filter_by(name=bn).first()
            if not brand:
                mo = db.session.query(db.func.max(Brand.sort_order)).scalar() or 0
                brand = Brand(name=bn, sort_order=mo+1)
                db.session.add(brand)
                db.session.flush()
            g.brand_id = brand.id
        else:
            g.brand_id = request.form.get('brand_id', type=int)
        # 自动保存颜色预设
        if g.color and g.color.strip():
            cn = g.color.strip()
            if not ColorPreset.query.filter_by(name=cn).first():
                mo = db.session.query(db.func.max(ColorPreset.sort_order)).scalar() or 0
                db.session.add(ColorPreset(name=cn, sort_order=mo+1))
        db.session.add(g); db.session.commit()
        return redirect(url_for('garment_detail', id=g.id))
    
    categories = Category.query.order_by(Category.sort_order).all()
    location_presets = LocationPreset.query.order_by(LocationPreset.sort_order).all()
    brands = Brand.query.order_by(Brand.sort_order).all()
    return render_template('smart.html', color_presets=ColorPreset.query.order_by(ColorPreset.sort_order).all(), 
                          categories=categories, location_presets=location_presets, brands=brands,
                          matched_garments=matched_garments, smart_data=smart_data)
    categories = Category.query.order_by(Category.sort_order).all()
    location_presets = LocationPreset.query.order_by(LocationPreset.sort_order).all()
    brands = Brand.query.order_by(Brand.sort_order).all()
    if request.method == 'POST':
        g = Garment()
        g.name = request.form.get('name', '\u672a\u547d\u540d')
        cname = request.form.get('category_text', '').strip()
    if cname:
        cat = Category.query.filter_by(name=cname).first()
        if not cat:
            mo = db.session.query(db.func.max(Category.sort_order)).scalar() or 0
            cat = Category(name=cname, icon='📦', sort_order=mo+1)
            db.session.add(cat)
            db.session.flush()
        g.category_id = cat.id
    else:
        g.category_id = request.form.get('category_id', type=int) or (categories[0].id if categories else None)
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
            brand = Brand.query.filter_by(name=bn).first()
            if not brand:
                mo = db.session.query(db.func.max(Brand.sort_order)).scalar() or 0
                brand = Brand(name=bn, sort_order=mo+1)
                db.session.add(brand)
                db.session.flush()
            g.brand_id = brand.id
        else:
            g.brand_id = request.form.get('brand_id', type=int)
        # 自动保存颜色预设
        if g.color and g.color.strip():
            cn = g.color.strip()
            if not ColorPreset.query.filter_by(name=cn).first():
                mo = db.session.query(db.func.max(ColorPreset.sort_order)).scalar() or 0
                db.session.add(ColorPreset(name=cn, sort_order=mo+1))
        db.session.add(g); db.session.commit()
        return redirect(url_for('garment_detail', id=g.id))
    return render_template('smart.html', color_presets=ColorPreset.query.order_by(ColorPreset.sort_order).all(), categories=categories, location_presets=location_presets, brands=brands)

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
        cats = Category.query.order_by(Category.sort_order).all()
        cid = None
        ai_name = ''
        ai_category = ''
        if ai_result and len(ai_result) > 0:
            cid, _ = match_category(ai_result, cats)
            ai_name = ai_result[0]['name']
            ai_category = ai_result[0]['category']
        candidates = Garment.query.filter_by(archived=False)
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
    presets = LocationPreset.query.order_by(LocationPreset.sort_order).all()
    data = [{'preset': p, 'count': Garment.query.filter_by(location_preset_id=p.id, archived=False).count()} for p in presets]
    return render_template('locations.html', preset_data=data)

@app.route('/manage')
def manage():
    return render_template('manage.html', cat_count=Category.query.count(),
                          brand_count=Brand.query.count(), loc_count=LocationPreset.query.count(), color_count=ColorPreset.query.count())

@app.route('/manage/categories', methods=['GET','POST'])
def manage_categories():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            n = request.form.get('name','').strip()
            if n:
                mo = db.session.query(db.func.max(Category.sort_order)).scalar() or 0
                db.session.add(Category(name=n, icon=request.form.get('icon','\U0001f4e6').strip(), sort_order=mo+1))
                db.session.commit()
        elif a == 'edit':
            cat = Category.query.get(request.form.get('id', type=int))
            if cat: cat.name = request.form.get('name','').strip(); cat.icon = request.form.get('icon','\U0001f4e6').strip(); db.session.commit()
        elif a == 'delete':
            cat = Category.query.get(request.form.get('id', type=int))
            if cat and cat.garments.filter_by(archived=False).count()==0: db.session.delete(cat); db.session.commit()
        return redirect(url_for('manage_categories'))
    cats = Category.query.order_by(Category.sort_order).all()
    for c in cats: c.garment_count = Garment.query.filter_by(category_id=c.id, archived=False).count()
    return render_template('manage_categories.html', categories=cats)

@app.route('/manage/brands', methods=['GET','POST'])
def manage_brands():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            n = request.form.get('name','').strip()
            if n:
                mo = db.session.query(db.func.max(Brand.sort_order)).scalar() or 0
                db.session.add(Brand(name=n, sort_order=mo+1)); db.session.commit()
        elif a == 'edit':
            b = Brand.query.get(request.form.get('id', type=int))
            if b: b.name = request.form.get('name','').strip(); db.session.commit()
        elif a == 'delete':
            b = Brand.query.get(request.form.get('id', type=int))
            if b and b.garments.filter_by(archived=False).count()==0: db.session.delete(b); db.session.commit()
        return redirect(url_for('manage_brands'))
    brands = Brand.query.order_by(Brand.sort_order).all()
    for b in brands: b.garment_count = Garment.query.filter_by(brand_id=b.id, archived=False).count()
    return render_template('manage_brands.html', brands=brands)

@app.route('/manage/colors', methods=['GET','POST'])
def manage_colors():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            n = request.form.get('name','').strip()
            if n:
                mo = db.session.query(db.func.max(ColorPreset.sort_order)).scalar() or 0
                db.session.add(ColorPreset(name=n, sort_order=mo+1)); db.session.commit()
        elif a == 'edit':
            c = ColorPreset.query.get(request.form.get('id', type=int))
            if c: c.name = request.form.get('name','').strip(); db.session.commit()
        elif a == 'delete':
            c = ColorPreset.query.get(request.form.get('id', type=int))
            if c: db.session.delete(c); db.session.commit()
        return redirect(url_for('manage_colors'))
    colors = ColorPreset.query.order_by(ColorPreset.sort_order).all()
    for c in colors: c.garment_count = Garment.query.filter(Garment.color == c.name, Garment.archived == False).count()
    return render_template('manage_colors.html', colors=colors)

@app.route('/manage/locations', methods=['GET','POST'])
def manage_locations():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            room = request.form.get('room','').strip()
            if room:
                cab, shelf, box = [request.form.get(x,'').strip() for x in ['cabinet','shelf','box']]
                mo = db.session.query(db.func.max(LocationPreset.sort_order)).scalar() or 0
                display = ' \u2192 '.join(filter(None, [room, cab, shelf, box]))
                db.session.add(LocationPreset(name=display, room=room, cabinet=cab, shelf=shelf, box=box, sort_order=mo+1))
                db.session.commit()
        elif a == 'edit':
            lp = LocationPreset.query.get(request.form.get('id', type=int))
            if lp:
                for f in ['room','cabinet','shelf','box']: setattr(lp, f, request.form.get(f,'').strip())
                lp.name = ' \u2192 '.join(filter(None, [lp.room, lp.cabinet, lp.shelf, lp.position]))
                db.session.commit()
        elif a == 'delete':
            lp = LocationPreset.query.get(request.form.get('id', type=int))
            if lp and lp.garments.filter_by(archived=False).count()==0: db.session.delete(lp); db.session.commit()
        return redirect(url_for('manage_locations'))
    presets = LocationPreset.query.order_by(LocationPreset.sort_order).all()
    for p in presets: p.garment_count = Garment.query.filter_by(location_preset_id=p.id, archived=False).count()
    return render_template('manage_locations.html', presets=presets)

@app.route('/export')
def export_data():
    garments = Garment.query.filter_by(archived=False).order_by(Garment.created_at.desc()).all()
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
def uploaded_file(fn):
    return send_from_directory(app.config['UPLOAD_FOLDER'], fn)

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js')

if __name__ == '__main__':
    with app.app_context(): init_db()
    app.run(host='0.0.0.0', port=3000, debug=True)
