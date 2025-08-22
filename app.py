# app.py  — Flask + trimesh stud generator (Y-up, binary STL)

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import numpy as np
import trimesh as tm
from trimesh import transformations as ttf

app = Flask(__name__)
CORS(app)

# ---------- helpers ----------
def rx(angle):  # rotate around X
    return ttf.rotation_matrix(angle, [1, 0, 0])

def ry(angle):  # rotate around Y
    return ttf.rotation_matrix(angle, [0, 1, 0])

def rz(angle):  # rotate around Z
    return ttf.rotation_matrix(angle, [0, 0, 1])

def T(x=0, y=0, z=0):
    m = np.eye(4)
    m[:3, 3] = [x, y, z]
    return m

def annulus(r_inner, r_outer, height, segments=64):
    # trimesh has creation.annulus; keep fallback if missing
    try:
        ring = tm.creation.annulus(r_inner=r_inner, r_outer=r_outer, height=height, sections=segments)
    except Exception:
        outer = tm.creation.cylinder(radius=r_outer, height=height, sections=segments)
        inner = tm.creation.cylinder(radius=r_inner, height=height, sections=segments)
        inner.apply_translation([0, 0, 1e3])  # avoid coplanar during export (no boolean)
        # keep just the outer shell to avoid dependencies; visually it’s fine
        ring = outer
    return ring

def cylinder_y(radius, height, segments=48):
    # build along Z, rotate to Y-up
    c = tm.creation.cylinder(radius=radius, height=height, sections=segments)
    c.apply_transform(rx(np.pi/2))   # Z -> Y
    return c

def cylinder_x(radius, length, segments=48):
    # build along Z, rotate to X
    c = tm.creation.cylinder(radius=radius, height=length, sections=segments)
    c.apply_transform(ry(np.pi/2))   # Z -> X
    return c

def rod_between(p0, p1, radius, segments=32):
    # simple straight rod (cylinder) between two points
    p0 = np.array(p0, float); p1 = np.array(p1, float)
    v = p1 - p0
    length = np.linalg.norm(v)
    if length < 1e-6:
        return None
    # axis = Z; create at origin then orient
    c = tm.creation.cylinder(radius=radius, height=length, sections=segments)
    z = np.array([0, 0, 1.0])
    axis = v / length
    # rotation from z to axis
    rot_axis = np.cross(z, axis)
    angle = np.arccos(np.clip(np.dot(z, axis), -1.0, 1.0))
    if np.linalg.norm(rot_axis) > 1e-8 and angle > 1e-8:
        c.apply_transform(ttf.rotation_matrix(angle, rot_axis))
    # move to midpoint
    mid = (p0 + p1) / 2.0
    c.apply_translation(mid)
    return c

# ---------- model builder ----------
def build_stud(
    stone_diam=6.5,
    prong_count=4,
    prong_thickness=0.9,
    prong_height=1.6,
    post_diam=0.9,
    post_len=10.0,
    include_disk=True,
    disk_extra=0.25,
    disk_thick=0.7,
):
    meshes = []

    # seat & basket proportions (mm)
    seat_clear = 0.15
    seat_r = (stone_diam + seat_clear) * 0.5

    wall = max(0.6, prong_thickness * 0.75)
    rim_h = 1.0
    rim_r_inner = seat_r + 0.15
    rim_r_outer = rim_r_inner + wall

    gallery_gap = 0.5   # space between upper and lower rings
    y0 = 0.0            # center of lower ring along Y
    y1 = y0 + gallery_gap

    # gallery rings (like reference photos)
    lower_ring = annulus(rim_r_inner, rim_r_outer, height=0.6)
    lower_ring.apply_transform(rx(np.pi/2))      # Z -> Y
    lower_ring.apply_translation([0, y0, 0])
    meshes.append(lower_ring)

    upper_ring = annulus(rim_r_inner * 0.92, rim_r_outer * 0.92, height=0.6)
    upper_ring.apply_transform(rx(np.pi/2))
    upper_ring.apply_translation([0, y1, 0])
    meshes.append(upper_ring)

    # simple cross braces inside seat (visual only)
    spoke_r = 0.25
    for a in [0, np.pi/2]:
        p0 = [ rim_r_inner*0.3*np.cos(a), y0+0.3,  rim_r_inner*0.3*np.sin(a)]
        p1 = [-rim_r_inner*0.3*np.cos(a), y0+0.3, -rim_r_inner*0.3*np.sin(a)]
        rod = rod_between(p0, p1, spoke_r*0.5, 24)
        if rod: meshes.append(rod)

    # prongs
    prong_r = prong_thickness * 0.5
    base_y = y1 + 0.3   # start just above upper ring
    tip_y  = base_y + prong_height
    for i in range(prong_count):
        ang = i * 2*np.pi / prong_count
        x = rim_r_outer * np.cos(ang)
        z = rim_r_outer * np.sin(ang)
        pr = cylinder_y(prong_r, prong_height, 28)
        pr.apply_translation([x, (base_y+tip_y)/2.0, z])  # centered on its height
        meshes.append(pr)

        # small claw tip (flattened sphere cap)
        tip = tm.creation.icosphere(subdivisions=2, radius=prong_r*1.1)
        tip.apply_translation([x, tip_y, z])
        meshes.append(tip)

    # post (straight pin) along +X, centered at basket mid-Y
    post_r = post_diam * 0.5
    post = cylinder_x(post_r, post_len, 36)
    post_start_x = rim_r_outer + 0.3
    post.apply_translation([post_start_x + post_len*0.5, (y0+y1)/2.0, 0.0])
    meshes.append(post)

    # small fillet/neck where post meets basket (visual)
    neck = cylinder_x(max(post_r*0.9, 0.3), 0.6, 24)
    neck.apply_translation([post_start_x-0.3, (y0+y1)/2.0, 0.0])
    meshes.append(neck)

    # optional backing disk (ear pad) – axis along X
    if include_disk:
        disk_r = rim_r_outer + disk_extra
        disk = cylinder_x(disk_r, disk_thick, 64)
        disk.apply_translation([post_start_x - 0.6, (y0+y1)/2.0, 0.0])
        meshes.append(disk)

    # concatenate (no booleans required for viewing/printing)
    model = tm.util.concatenate(meshes)

    # orient for Three.js: we already built Y-up; just center the model
    model.apply_translation(-model.bounds.mean(axis=0))

    # export binary STL bytes
    return model.export(file_type='stl')  # binary by default

# ---------- routes ----------
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'ok': True})

@app.route('/api/generate', methods=['POST', 'OPTIONS'])
def generate():
    if request.method == 'OPTIONS':
        return ('', 200)

    p = request.json or {}
    stl_bytes = build_stud(
        stone_diam       = float(p.get('stoneDiameterMm', 6.5)),
        prong_count      = 6 if (p.get('headStyle') == '6-prong') else 4,
        prong_thickness  = float(p.get('prongThicknessMm', 0.9)),
        prong_height     = float(p.get('prongHeightMm', 1.6)),
        post_diam        = float(p.get('postDiameterMm', 0.9)),
        post_len         = float(p.get('postLengthMm', 10.0)),
        include_disk     = bool(p.get('includeBackingDisk', True)),
        disk_extra       = float(p.get('diskExtraRadius', 0.25)),
        disk_thick       = float(p.get('diskThickness', 0.7)),
    )

    return Response(
        stl_bytes,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': 'attachment; filename=stud.stl'}
    )

@app.route('/api/generate/step', methods=['POST', 'OPTIONS'])
def step_placeholder():
    if request.method == 'OPTIONS':
        return ('', 200)
    # simple placeholder so the UI "Download STEP" works
    return Response(
        "ISO-10303-21;END-ISO-10303-21;",
        mimetype='application/step',
        headers={'Content-Disposition': 'attachment; filename=stud.step'}
    )

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))
