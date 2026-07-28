#!/usr/bin/env python3
"""Samantha的衣橱"""
import json, io, zipfile, os
from datetime import datetime
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

# ========== 数据模型 ==========

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(10), default='👔')
    sort_order = db.Column(db.Integer, default=0)
    garments = db.relationship('Garment', backref='category', lazy='dynamic')

class Brand(db.Model):
    __tablename__ = 'brands'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    garments = db.relationship('Garment', backref='brand_rel', lazy='dynamic')

class LocationPreset(db.Model):
    __tablename__ = 'location_presets'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    room = db.Column(db.String(100))
    cabinet = db.Column(db.String(100))
    shelf = db.Column(db.String(100))
    box = db.Column(db.String(100))
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
    price = db.Column(db.Float)
    purchase_date = db.Column(db.Date)
    photo = db.Column(db.String(500))
    thumbnail = db.Column(db.String(500))
    notes = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    size_label = db.Column(db.String(50))
    shoulder = db.Column(db.Float)
    bust = db.Column(db.Float)
    waist = db.Column(db.Float)
    hip = db.Column(db.Float)
    length = db.Column(db.Float)
    sleeve = db.Column(db.Float)
    custom_size = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

DEFAULT_CATEGORIES = [
    ('👕','上衣',1),('👖','裤子',2),('👗','裙子',3),('🧥','外套',4),('🧣','配饰',5),
]
DEFAULT_BRANDS = [
    ('优衣库',1),('ZARA',2),('H&M',3),('无品牌',4),
]

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

def format_storage_location(garment):
    lp = garment.location_preset
    if not lp: return '未标记位置'
    parts = [lp.room, lp.cabinet, lp.shelf, lp.box]
    return ' → '.join(filter(None, parts))

# ========== 首页 ==========

@app.route('/')
def index():
    categories = Category.query.order_by(Category.sort_order).all()
    total = Garment.query.filter_by(archived=False).count()
    cat_counts = {c.id: Garment.query.filter_by(category_id=c.id, archived=False).count() for c in categories}
    season_stats = {sg: Garment.query.filter_by(archived=False, season_group=sg).count() for sg in ['夏季','冬季','春秋季']}
    recent = Garment.query.filter_by(archived=False).order_by(Garment.created_at.desc()).limit(8).all()
    return render_template('index.html', categories=categories, total=total,
                          cat_counts=cat_counts, season_stats=season_stats, recent=recent,
                          format_location=format_storage_location)

# ========== 衣物 CRUD ==========

@app.route('/garments')
def garment_list():
    query = Garment.query.filter_by(archived=False)
    if cid := request.args.get('category', type=int): query = query.filter_by(category_id=cid)
    if sg := request.args.get('season'): query = query.filter_by(season_group=sg)
    if lid := request.args.get('location', type=int): query = query.filter_by(location_preset_id=lid)
    if bid := request.args.get('brand', type=int): query = query.filter_by(brand_id=bid)
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
    return render_template('detail.html', garment=Garment.query.get_or_404(id),
                          format_location=format_storage_location)

def _save_garment(garment):
    garment.name = request.form.get('name','')
    garment.category_id = request.form.get('category_id', type=int)
    garment.brand_id = request.form.get('brand_id', type=int)
    garment.location_preset_id = request.form.get('location_preset_id', type=int)
    garment.color = request.form.get('color','')
    garment.material = request.form.get('material','')
    garment.season_group = request.form.get('season_group','')
    garment.price = request.form.get('price', type=float)
    garment.notes = request.form.get('notes','')
    garment.size_label = request.form.get('size_label','')
    for f in ['shoulder','bust','waist','hip','length','sleeve']:
        setattr(garment, f, request.form.get(f, type=float))
    garment.custom_size = request.form.get('custom_size','')
    if pd := request.form.get('purchase_date',''): garment.purchase_date = datetime.strptime(pd, '%Y-%m-%d').date()
    else: garment.purchase_date = None
    if 'photo' in request.files and request.files['photo'].filename:
        garment.photo, garment.thumbnail = save_photo(request.files['photo'])

@app.route('/garments/new', methods=['GET','POST'])
def garment_new():
    if request.method == 'POST':
        g = Garment(); _save_garment(g); db.session.add(g); db.session.commit()
        return redirect(url_for('garment_detail', id=g.id))
    return render_template('form.html', garment=None,
                          categories=Category.query.order_by(Category.sort_order).all(),
                          location_presets=LocationPreset.query.order_by(LocationPreset.sort_order).all(),
                          brands=Brand.query.order_by(Brand.sort_order).all(), mode='new')

@app.route('/garments/<int:id>/edit', methods=['GET','POST'])
def garment_edit(id):
    g = Garment.query.get_or_404(id)
    if request.method == 'POST':
        _save_garment(g); g.updated_at = datetime.utcnow(); db.session.commit()
        return redirect(url_for('garment_detail', id=g.id))
    return render_template('form.html', garment=g,
                          categories=Category.query.order_by(Category.sort_order).all(),
                          location_presets=LocationPreset.query.order_by(LocationPreset.sort_order).all(),
                          brands=Brand.query.order_by(Brand.sort_order).all(), mode='edit')

@app.route('/garments/<int:id>/delete', methods=['POST'])
def garment_delete(id):
    db.session.delete(Garment.query.get_or_404(id)); db.session.commit()
    return redirect(url_for('garment_list'))

@app.route('/garments/<int:id>/archive', methods=['POST'])
def garment_archive(id):
    g = Garment.query.get_or_404(id); g.archived = not g.archived; db.session.commit()
    return redirect(url_for('garment_detail', id=id))

@app.route('/garments/<int:id>/clone', methods=['POST'])
def garment_clone(id):
    o = Garment.query.get_or_404(id)
    c = Garment(name=f"{o.name} (副本)", category_id=o.category_id, brand_id=o.brand_id,
                location_preset_id=o.location_preset_id, color=o.color, material=o.material,
                season_group=o.season_group, price=o.price, size_label=o.size_label,
                shoulder=o.shoulder, bust=o.bust, waist=o.waist, hip=o.hip,
                length=o.length, sleeve=o.sleeve, custom_size=o.custom_size, notes=o.notes)
    db.session.add(c); db.session.commit()
    return redirect(url_for('garment_edit', id=c.id))

# ========== 位置浏览 ==========

@app.route('/locations')
def locations():
    presets = LocationPreset.query.order_by(LocationPreset.sort_order).all()
    data = [{'preset': p, 'count': Garment.query.filter_by(location_preset_id=p.id, archived=False).count()} for p in presets]
    return render_template('locations.html', preset_data=data)

# ========== 管理 ==========

@app.route('/manage')
def manage():
    return render_template('manage.html', cat_count=Category.query.count(),
                          brand_count=Brand.query.count(), loc_count=LocationPreset.query.count())

@app.route('/manage/categories', methods=['GET','POST'])
def manage_categories():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            n = request.form.get('name','').strip()
            if n:
                mo = db.session.query(db.func.max(Category.sort_order)).scalar() or 0
                db.session.add(Category(name=n, icon=request.form.get('icon','📦').strip(), sort_order=mo+1))
                db.session.commit()
        elif a == 'edit':
            cat = Category.query.get(request.form.get('id', type=int))
            if cat: cat.name = request.form.get('name','').strip(); cat.icon = request.form.get('icon','📦').strip(); db.session.commit()
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

@app.route('/manage/locations', methods=['GET','POST'])
def manage_locations():
    if request.method == 'POST':
        a = request.form.get('action')
        if a == 'add':
            room = request.form.get('room','').strip()
            if room:
                cab, shelf, box = [request.form.get(x,'').strip() for x in ['cabinet','shelf','box']]
                mo = db.session.query(db.func.max(LocationPreset.sort_order)).scalar() or 0
                display = ' → '.join(filter(None, [room, cab, shelf, box]))
                db.session.add(LocationPreset(name=display, room=room, cabinet=cab, shelf=shelf, box=box, sort_order=mo+1))
                db.session.commit()
        elif a == 'edit':
            lp = LocationPreset.query.get(request.form.get('id', type=int))
            if lp:
                for f in ['room','cabinet','shelf','box']: setattr(lp, f, request.form.get(f,'').strip())
                lp.name = ' → '.join(filter(None, [lp.room, lp.cabinet, lp.shelf, lp.box]))
                db.session.commit()
        elif a == 'delete':
            lp = LocationPreset.query.get(request.form.get('id', type=int))
            if lp and lp.garments.filter_by(archived=False).count()==0: db.session.delete(lp); db.session.commit()
        return redirect(url_for('manage_locations'))
    presets = LocationPreset.query.order_by(LocationPreset.sort_order).all()
    for p in presets: p.garment_count = Garment.query.filter_by(location_preset_id=p.id, archived=False).count()
    return render_template('manage_locations.html', presets=presets)

# ========== 数据导出 ==========

@app.route('/export')
def export_data():
    """一键备份：导出所有衣物数据 + 照片为 ZIP 包"""
    garments = Garment.query.filter_by(archived=False).order_by(Garment.created_at.desc()).all()
    data = []
    for g in garments:
        item = {
            "名称": g.name,
            "分类": g.category.name if g.category else "",
            "品牌": g.brand_rel.name if g.brand_rel else "",
            "颜色": g.color or "",
            "材质": g.material or "",
            "季节": g.season_group or "",
            "尺码": g.size_label or "",
            "价格": g.price or "",
            "购买日期": str(g.purchase_date) if g.purchase_date else "",
            "位置_房间": g.location_preset.room if g.location_preset else "",
            "位置_柜子": g.location_preset.cabinet if g.location_preset else "",
            "位置_层": g.location_preset.shelf if g.location_preset else "",
            "位置_收纳箱": g.location_preset.box if g.location_preset else "",
            "肩宽": g.shoulder or "",
            "胸围": g.bust or "",
            "腰围": g.waist or "",
            "臀围": g.hip or "",
            "衣长": g.length or "",
            "袖长": g.sleeve or "",
            "尺寸备注": g.custom_size or "",
            "备注": g.notes or "",
        }
        data.append(item)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("数据.json", json.dumps(data, ensure_ascii=False, indent=2))
        uploads = app.config['UPLOAD_FOLDER']
        for g in garments:
            for fn in [g.photo, g.thumbnail]:
                if fn:
                    fp = os.path.join(uploads, fn)
                    if os.path.exists(fp):
                        zf.write(fp, f"照片/{fn}")

    buf.seek(0)
    date_str = datetime.utcnow().strftime("%Y%m%d")
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": f"attachment; filename=wardrobe_backup_{date_str}.zip"}
    )

# ========== 静态文件 ==========

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
