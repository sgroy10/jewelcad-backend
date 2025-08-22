from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import math
import numpy as np
import trimesh

app = Flask(__name__)
CORS(app)

# --------- helpers ---------
def cylinder_y(radius: float, height: float, sections: int = 32) -> trimesh.Trimesh:
    """
    Create a cylinder aligned to Y axis, centered at origin.
    trimesh.creation.cylinder defaults to Z; we rotate to Y for consistency.
    """
    m = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    # rotate Z->Y (x stays x, y=z, z=-y)
    R = trimesh.transformations.rotation_matrix(angle=math.pi/2, direction=[1, 0, 0], point=[0,0,0])
    m.apply_transform(R)
    return m

def cylinder_x(radius: float, length: float, sections: int = 32) -> trimesh.Trimesh:
    """
    Create a cylinder aligned to X axis (for post/backing disk).
    """
    m = trimesh.creation.cylinder(radius=radius, height=length, sections=sections)
    # rotate Z->X
    R = trimesh.transformations.rotation_matrix(angle=math.pi/2, direction=[0, 1, 0], point=[0,0,0])
    m.apply_transform(R)
    return m

# --------- core generator ---------
def build_stud_mesh(params: dict) -> trimesh.Trimesh:
    """
    Build a *visual* stud earring (no boolean merges; meshes are concatenated).
    This is robust for web preview & STL export.
    """
    # Inputs with defaults
    stone_d = float(params.get('stoneDiameterMm', 6.5))
    head_style = params.get('headStyle', '4-prong')
    prong_n = 6 if head_style == '6-prong' else 4
    prong_t = float(params.get('prongThicknessMm', 0.9))
    prong_h = float(params.get('prongHeightMm', 1.6))
    post_d  = float(params.get('postDiameterMm', 0.9))
    post_l  = float(params.get('postLengthMm', 10.0))
    wall    = float(params.get('basketWallThicknessMm', 0.7))
    include_disk = bool(params.get('includeBackingDisk', True))
    disk_extra_r = float(params.get('backingDiskExtraRadiusMm', 0.25))
    disk_thick   = float(params.get('backingDiskThicknessMm', 0.7))

    # Derived sizing
    seat_r   = stone_d * 0.5
    rim_h    = 0.8
    rim_r    = seat_r + 0.2 + wall   # simple outer radius for the ring
    prong_r  = prong_t * 0.5
    post_r   = post_d * 0.5

    meshes = []

    # 1) Rim (a thin cylinder band visually; single cylinder is OK for preview/print)
    rim = cylinder_y(radius=rim_r, height=rim_h, sections=48)
    # lift to around Y=rim_h/2 so base sits near Y=0
    rim.apply_translation([0, rim_h * 0.5, 0])
    meshes.append(rim)

    # 2) Prongs (cylinders) on top of rim
    prong_base_y = rim_h
    for i in range(prong_n):
        ang = 2.0 * math.pi * i / prong_n
        px = rim_r * math.cos(ang)
        pz = rim_r * math.sin(ang)
        pr = cylinder_y(radius=prong_r, height=prong_h, sections=24)
        pr.apply_translation([px, prong_base_y + prong_h * 0.5, pz])
        meshes.append(pr)

    # 3) Post (cylinder along +X)
    # start just outside rim; center will be at startX + post_l/2
    start_x = rim_r + 0.20
    post = cylinder_x(radius=post_r, length=post_l, sections=32)
    post.apply_translation([start_x + post_l * 0.5, rim_h * 0.5, 0])
    meshes.append(post)

    # 4) Backing disk (thin cylinder along X near the head)
    if include_disk:
        disk_r = rim_r + disk_extra_r
        disk = cylinder_x(radius=disk_r, length=disk_thick, sections=64)
        disk.apply_translation([0.15 + disk_thick * 0.5, rim_h * 0.5, 0])
        meshes.append(disk)

    # Combine to one mesh
    combined = trimesh.util.concatenate(meshes)
    return combined

# --------- routes ---------
@app.get('/health')
def health():
    return jsonify({"ok": True})

@app.post('/stud.stl')
def stud_stl():
    """
    Accepts JSON body with stud params and returns a *binary* STL.
    """
    try:
        params = request.get_json(force=True, silent=True) or {}
        mesh = build_stud_mesh(params)
        stl_bytes = mesh.export(file_type='stl')  # binary STL
        return Response(
            stl_bytes,
            mimetype='application/octet-stream',
            headers={'Content-Disposition': 'attachment; filename=stud.stl'}
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.post('/stud.step')
def stud_step_placeholder():
    """
    Simple placeholder STEP output so your UI's STEP button works.
    (Proper STEP needs an OCC kernel; this is a stub.)
    """
    step_content = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('JewelCAD Stud (placeholder)'),'2;1');
FILE_NAME('stud.step','2025-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('AP203'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;"""
    return Response(
        step_content,
        mimetype='application/step',
        headers={'Content-Disposition': 'attachment; filename=stud.step'}
    )

if __name__ == '__main__':
    # Local dev run (Railway uses gunicorn via Dockerfile)
    import os
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
