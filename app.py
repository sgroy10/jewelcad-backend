# app.py — JewelCAD backend (Flask + trimesh, no torus)
# Stable on Railway: only cylinders + transforms, no booleans, no torus.

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import math
import numpy as np
import trimesh

app = Flask(__name__)
CORS(app)

# ----------------- helpers -----------------

def cyl(radius: float, height: float, sections: int = 64) -> trimesh.Trimesh:
    """Y-up cylinder centered at origin (height along Y)."""
    return trimesh.creation.cylinder(radius=radius, height=height, sections=sections)

def translate(mesh: trimesh.Trimesh, x=0.0, y=0.0, z=0.0) -> trimesh.Trimesh:
    mesh.apply_translation([x, y, z])
    return mesh

def rotate_about_z(mesh: trimesh.Trimesh, angle_rad: float) -> trimesh.Trimesh:
    T = trimesh.transformations.rotation_matrix(angle_rad, [0,0,1], point=[0,0,0])
    mesh.apply_transform(T)
    return mesh

def ring_band_visual(r_in: float, r_out: float, h: float, sections: int = 96) -> trimesh.Trimesh:
    """
    Visual ring wall using cylinders only (no boolean subtraction).
    Outer wall + thin top/bottom rings + a 'shadow' inner wall slightly shrunk.
    """
    outer = cyl(r_out, h, sections=sections)
    # thin top & bottom bead rings (look like closed wall)
    cap_t = 0.12
    top = cyl(r_out, cap_t, sections=sections);  translate(top, y= h/2 + cap_t/2)
    bot = cyl(r_out, cap_t, sections=sections);  translate(bot, y=-h/2 - cap_t/2)
    # inner visual liner (tiny shrink to avoid z-fighting)
    inner = cyl(max(r_in, 0.01), h*0.96, sections=sections)
    inner.apply_scale([0.998, 0.998, 0.998])
    return trimesh.util.concatenate([outer, top, bot, inner])

# ----------------- core model -----------------

def build_stud(params: dict) -> trimesh.Trimesh:
    # inputs
    stone_d = float(params.get('stoneDiameterMm', 6.5))
    head_style = params.get('headStyle', '4-prong')
    prong_n = 6 if head_style == '6-prong' else 4

    seat_clear = float(params.get('seatClearanceMm', 0.05))
    seat_d = stone_d + seat_clear

    prong_t = float(params.get('prongThicknessMm', 0.9))
    prong_r = max(0.25, prong_t * 0.45)
    prong_h = float(params.get('prongHeightMm') or max(1.2, 0.32*stone_d))

    wall = float(params.get('basketWallThicknessMm', 0.8))
    post_d = float(params.get('postDiameterMm', 0.9))
    post_r = post_d/2
    post_len = float(params.get('postLengthMm', 10.0))

    include_backing = bool(params.get('includeBackingDisk', True))
    disk_extra = float(params.get('backDiskExtraRadius', 0.25))
    disk_thick = float(params.get('backDiskThickness', 0.7))

    # basket geometry
    rim_inner = (seat_d/2.0) + 0.15
    rim_outer = rim_inner + max(0.6, wall)
    rim_h = 1.0

    parts = []

    # ring wall
    band = ring_band_visual(r_in=rim_inner*0.98, r_out=rim_outer, h=rim_h, sections=96)
    translate(band, y=rim_h/2)
    parts.append(band)

    # mid bead rim: emulate torus using very short cylinder "bead"
    bead_h = 0.25
    bead_r = rim_outer
    bead = cyl(bead_r, bead_h, sections=128)
    translate(bead, y=rim_h*0.5)
    parts.append(bead)

    # inner seat ring (thin)
    seat_h = 0.18
    seat_r = rim_inner*0.72
    seat = cyl(seat_r, seat_h, sections=96)
    translate(seat, y=rim_h*0.35)
    parts.append(seat)

    # prongs, angled inward
    prong_base_y = rim_h
    angle_in = math.radians(18)
    for i in range(prong_n):
        ang = i * (2*math.pi/prong_n)
        px = rim_outer * math.cos(ang)
        pz = rim_outer * math.sin(ang)
        pr = cyl(prong_r, prong_h, sections=24)
        translate(pr, y=prong_h/2)               # base at y=0
        rotate_about_z(pr, angle_in * math.cos(ang))  # lean inward a bit
        translate(pr, x=px, y=prong_base_y, z=pz)
        parts.append(pr)

    # post along +X
    post = cyl(post_r, post_len, sections=48)
    rotate_about_z(post, math.pi/2)  # Y->X
    translate(post, x=rim_outer + 0.25 + post_len/2, y=rim_h*0.5, z=0)
    parts.append(post)

    # backing disk (axis along X)
    if include_backing:
        disk_r = rim_outer + disk_extra
        disk = cyl(disk_r, disk_thick, sections=96)
        rotate_about_z(disk, math.pi/2)
        translate(disk, x=rim_outer + disk_thick/2, y=rim_h*0.5, z=0)
        parts.append(disk)

    model = trimesh.util.concatenate(parts)

    # smooth normals if available
    try:
        model = model.smoothed()
    except Exception:
        pass

    # place nicely near grid: keep basket base near y≈0
    bbox = model.bounds
    center = (bbox[0] + bbox[1]) / 2.0
    desired_y = rim_h * 0.1
    translate(model, x=-center[0], y=desired_y - center[1], z=-center[2])
    return model

# ----------------- routes -----------------

@app.get('/health')
def health():
    return jsonify({'ok': True})

@app.post('/api/generate')
def api_generate():
    params = request.get_json(silent=True) or {}
    mesh = build_stud(params)
    stl_bytes = mesh.export(file_type='stl')
    if isinstance(stl_bytes, str):
        stl_bytes = stl_bytes.encode('utf-8')
    return Response(
        stl_bytes,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': 'attachment; filename="stud.stl"'}
    )

@app.post('/api/generate/step')
def api_generate_step():
    # Placeholder STEP
    content = (
        "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Stud Earring'),'2;1');\n"
        "FILE_NAME('stud.step','2025-01-01T00:00:00',(''),(''),'','','');\n"
        "FILE_SCHEMA(('AP203'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;"
    ).encode('utf-8')
    return Response(content, mimetype='application/step',
                    headers={'Content-Disposition': 'attachment; filename=\"stud.step\"'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
