# app.py — JewelCAD backend (Flask + trimesh, no booleans)
# Robust fix: make cylinders Y-up explicitly, then transforms behave correctly.

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import os
import math
import numpy as np
import trimesh

app = Flask(__name__)
CORS(app)

# ----------------- transforms -----------------

def rotate_matrix(angle_rad, axis, point=(0.0, 0.0, 0.0)):
    axis = np.asarray(axis, dtype=float)
    axis = axis / (np.linalg.norm(axis) + 1e-12)
    return trimesh.transformations.rotation_matrix(angle_rad, axis, point)

def rotate_about_x(mesh, angle_rad, point=(0.0, 0.0, 0.0)):
    mesh.apply_transform(rotate_matrix(angle_rad, [1, 0, 0], point))
    return mesh

def rotate_about_y(mesh, angle_rad, point=(0.0, 0.0, 0.0)):
    mesh.apply_transform(rotate_matrix(angle_rad, [0, 1, 0], point))
    return mesh

def rotate_about_z(mesh, angle_rad, point=(0.0, 0.0, 0.0)):
    mesh.apply_transform(rotate_matrix(angle_rad, [0, 0, 1], point))
    return mesh

def rotate_about_axis(mesh, angle_rad, axis, point):
    mesh.apply_transform(rotate_matrix(angle_rad, axis, point))
    return mesh

def translate(mesh, x=0.0, y=0.0, z=0.0):
    mesh.apply_translation([x, y, z])
    return mesh

# ----------------- geometry helpers -----------------

def cylinder_y(radius: float, height: float, sections: int = 64) -> trimesh.Trimesh:
    """
    Create a cylinder whose axis is along +Y (Trimesh's default is +Z).
    """
    m = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    # Re-orient Z-up -> Y-up
    rotate_about_x(m, -math.pi / 2.0)  # Z->Y
    return m

def ring_band_visual(r_in: float, r_out: float, h: float, sections: int = 96) -> trimesh.Trimesh:
    """
    'Visual' ring wall without booleans:
    - outer wall
    - thin top/bottom beads (to visually close)
    - inner liner slightly smaller to avoid z-fighting
    All Y-up.
    """
    parts = []

    outer = cylinder_y(r_out, h, sections=sections)
    parts.append(outer)

    cap_t = 0.12
    top = cylinder_y(r_out, cap_t, sections=sections)
    translate(top, y=h/2 + cap_t/2)
    parts.append(top)

    bot = cylinder_y(r_out, cap_t, sections=sections)
    translate(bot, y=-h/2 - cap_t/2)
    parts.append(bot)

    inner = cylinder_y(max(r_in, 0.01), h * 0.96, sections=sections)
    inner.apply_scale([0.998, 0.998, 0.998])
    parts.append(inner)

    return trimesh.util.concatenate(parts)

# ----------------- model builder -----------------

def build_stud(params: dict) -> trimesh.Trimesh:
    stone_d = float(params.get('stoneDiameterMm', 6.5))
    head_style = params.get('headStyle', '4-prong')
    prong_n = 6 if head_style == '6-prong' else 4

    seat_clear = float(params.get('seatClearanceMm', 0.05))
    seat_d = stone_d + seat_clear

    prong_t = float(params.get('prongThicknessMm', 0.9))
    prong_r = max(0.25, prong_t * 0.45)
    prong_h = float(params.get('prongHeightMm') or max(1.2, 0.32 * stone_d))

    wall = float(params.get('basketWallThicknessMm', 0.8))
    post_d = float(params.get('postDiameterMm', 0.9))
    post_r = post_d / 2.0
    post_len = float(params.get('postLengthMm', 10.0))

    include_backing = bool(params.get('includeBackingDisk', True))
    disk_extra = float(params.get('backDiskExtraRadius', 0.25))
    disk_thick = float(params.get('backDiskThickness', 0.7))

    # Basket rim dimensions
    rim_inner = (seat_d / 2.0) + 0.15
    rim_outer = rim_inner + max(0.6, wall)
    rim_h = 1.0

    parts = []

    # 1) Basket band (Y-up)
    band = ring_band_visual(r_in=rim_inner * 0.98, r_out=rim_outer, h=rim_h, sections=96)
    translate(band, y=rim_h / 2.0)
    parts.append(band)

    # 2) Mid bead (thin ring)
    bead = cylinder_y(rim_outer, 0.25, sections=128)
    translate(bead, y=rim_h * 0.5)
    parts.append(bead)

    # 3) Seat ring (thin inner)
    seat = cylinder_y(rim_inner * 0.72, 0.18, sections=96)
    translate(seat, y=rim_h * 0.35)
    parts.append(seat)

    # 4) Prongs, tilted inward toward center
    prong_base_y = rim_h
    tilt = math.radians(18)
    for i in range(prong_n):
        ang = i * (2.0 * math.pi / prong_n)
        px = rim_outer * math.cos(ang)
        pz = rim_outer * math.sin(ang)

        pr = cylinder_y(prong_r, prong_h, sections=24)
        # Move base to y=0..h
        translate(pr, y=prong_h / 2.0)
        # Tilt toward center around axis = cross(Y, radial)
        radial = np.array([math.cos(ang), 0.0, math.sin(ang)], dtype=float)
        axis = np.cross([0.0, 1.0, 0.0], radial)  # axis lies in XZ plane
        base_point = np.array([px, prong_base_y, pz], dtype=float)
        rotate_about_axis(pr, -tilt, axis, base_point)
        # Now place at rim top
        translate(pr, x=px, y=prong_base_y, z=pz)
        parts.append(pr)

    # 5) Post along +X (start a hair behind basket rim)
    post = cylinder_y(post_r, post_len, sections=48)
    # Y (axis) -> X by +90° around Z
    rotate_about_z(post, math.pi / 2.0)
    translate(post, x=rim_outer + 0.25 + post_len / 2.0, y=rim_h * 0.5, z=0.0)
    parts.append(post)

    # 6) Backing disk coaxial with post (also along +X)
    if include_backing:
        disk_r = rim_outer + disk_extra
        disk = cylinder_y(disk_r, disk_thick, sections=96)
        rotate_about_z(disk, math.pi / 2.0)
        translate(disk, x=rim_outer + disk_thick / 2.0, y=rim_h * 0.5, z=0.0)
        parts.append(disk)

    model = trimesh.util.concatenate(parts)

    # Keep triangles sane for STL
    try:
        model.remove_degenerate_faces()
        model.remove_duplicate_faces()
        model.merge_vertices()
    except Exception:
        pass

    # Place nicely near grid (basket base near y≈0)
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
    # Placeholder STEP (still a stub until we switch to a real BREP kernel)
    content = (
        "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Stud Earring'),'2;1');\n"
        "FILE_NAME('stud.step','2025-01-01T00:00:00',(''),(''),'','','');\n"
        "FILE_SCHEMA(('AP203'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;"
    ).encode('utf-8')
    return Response(
        content,
        mimetype='application/step',
        headers={'Content-Disposition': 'attachment; filename=\"stud.step\"'}
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    app.run(host='0.0.0.0', port=port, debug=False)
