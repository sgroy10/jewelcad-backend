# app.py — JewelCAD backend (Flask + trimesh)
# Generates a parametric stud earring as a single STL blob
# Designed to run headless on Railway (no heavyweight boolean kernels)

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import io
import math
import numpy as np
import trimesh

app = Flask(__name__)
CORS(app)

# ---- helpers ---------------------------------------------------------------

def cyl(radius: float, height: float, sections: int = 64) -> trimesh.Trimesh:
    """Y-up cylinder centered at origin (height along +Y / -Y)."""
    m = trimesh.creation.cylinder(
        radius=radius,
        height=height,
        sections=sections,
        segment=None,
        transform=np.eye(4)
    )
    return m

def ring_band(r_in: float, r_out: float, h: float, sections: int = 96) -> trimesh.Trimesh:
    """
    Thin ring 'wall': outer cylinder minus inner cylinder (no booleans).
    We'll approximate by building two open cylinders + top/bottom annulus caps.
    To avoid boolean, we just place very thin top+bottom rings and the outer wall.
    This exports fine for STL and looks like a basket wall.
    """
    outer = cyl(r_out, h, sections=sections)

    # Make top & bottom annulus (very thin cylinders) to visually close the wall
    cap_t = 0.12  # 0.12 mm thin visual rim
    top = cyl(r_out, cap_t, sections=sections).apply_translation([0, +h/2 + cap_t/2, 0])
    bot = cyl(r_out, cap_t, sections=sections).apply_translation([0, -h/2 - cap_t/2, 0])

    # Subtle inner band as visual (not boolean subtraction)
    # very slightly smaller height so no z-fighting
    inner = cyl(r_in, h * 0.96, sections=sections)
    inner.apply_scale([0.999, 0.999, 0.999])  # tiny shrink to keep meshes distinct

    return trimesh.util.concatenate([outer, top, bot, inner])

def torus(mean_r: float, tube_r: float, sections: int = 96, tube_sections: int = 24) -> trimesh.Trimesh:
    """
    Simple torus (XZ plane), then we will lift it along Y to sit mid-basket.
    """
    T = trimesh.creation.torus(radius=mean_r, tube_radius=tube_r,
                               sections=sections, tube_sections=tube_sections)
    return T

def rotate_about_axis(mesh: trimesh.Trimesh, axis: np.ndarray, angle_rad: float) -> trimesh.Trimesh:
    T = trimesh.transformations.rotation_matrix(angle_rad, axis, point=[0,0,0])
    mesh.apply_transform(T)
    return mesh

def translate(mesh: trimesh.Trimesh, x=0.0, y=0.0, z=0.0) -> trimesh.Trimesh:
    mesh.apply_translation([x, y, z])
    return mesh

# ---- core model ------------------------------------------------------------

def build_stud(params: dict) -> trimesh.Trimesh:
    """
    Build a stud earring roughly matching commercial 4/6-prong baskets.

    Coordinate system: Three.js friendly (Y up). We run the post along +X.
    Units: mm (viewer is unit-agnostic; we keep mm throughout).
    """
    # Inputs (defaults are sensible)
    stone_d = float(params.get('stoneDiameterMm', 6.5))
    head_style = params.get('headStyle', '4-prong')
    prong_n = 6 if head_style == '6-prong' else 4

    seat_clear = float(params.get('seatClearanceMm', 0.05))
    seat_d = stone_d + seat_clear

    prong_t = float(params.get('prongThicknessMm', 0.9))           # diameter-ish
    prong_r = max(0.25, prong_t * 0.45)                            # cylinder radius
    prong_h = float(params.get('prongHeightMm') or max(1.2, 0.32*stone_d))

    wall = float(params.get('basketWallThicknessMm', 0.8))
    post_d = float(params.get('postDiameterMm', 0.9))
    post_r = post_d / 2.0
    post_len = float(params.get('postLengthMm', 10.0))

    include_backing = True  # UI toggles this; if you pass includeBackingDisk false, we skip
    if 'includeBackingDisk' in params:
        include_backing = bool(params['includeBackingDisk'])
    disk_extra = float(params.get('backDiskExtraRadius', 0.25))
    disk_thick = float(params.get('backDiskThickness', 0.7))

    # Basket dimensions (tuned to reference photos)
    rim_inner = (seat_d / 2.0) + 0.15
    rim_outer = rim_inner + max(0.6, wall)
    rim_h = 1.0  # vertical height of basket wall

    # Build parts
    parts = []

    # Basket ring band
    band = ring_band(r_in=rim_inner*0.98, r_out=rim_outer, h=rim_h, sections=96)
    # Lift band so its base is near y=0 (rim bottom slightly above grid)
    translate(band, y=rim_h/2.0)
    parts.append(band)

    # Decorative/structural torus rim at mid-height
    mean_r = (rim_inner + rim_outer) * 0.5
    tube_r = max(0.18, (rim_outer - rim_inner) * 0.35)
    rim = torus(mean_r=mean_r, tube_r=tube_r, sections=128, tube_sections=24)
    # Torus is centered at origin (in XZ) with Y=0 midplane; lift to sit mid basket
    translate(rim, y=rim_h * 0.5 + 0.02)
    parts.append(rim)

    # Seat support ring (thin inner ring a little below mid)
    seat_ring = torus(mean_r=rim_inner*0.70, tube_r=max(0.15, tube_r*0.65),
                      sections=96, tube_sections=20)
    translate(seat_ring, y=rim_h * 0.35)
    parts.append(seat_ring)

    # Prongs: cylinders angled toward the stone center
    prong_base_y = rim_h  # start at top of the basket wall
    prong_tip_y  = prong_base_y + prong_h
    prong_angle_in = math.radians(18)  # lean inward a bit

    for i in range(prong_n):
        ang = i * (2*math.pi / prong_n)
        # Place base at outer rim (slightly outside)
        px = rim_outer * math.cos(ang)
        pz = rim_outer * math.sin(ang)

        pr = cyl(radius=prong_r, height=prong_h, sections=24)
        # Cyl is centered at origin; make its base at y=0 then lift to prong_base_y
        translate(pr, y=prong_h/2.0)
        # Aim it inward: rotate around Z to pitch toward center (depends on tangent)
        # First rotate it around Z so it leans toward -radial direction
        rotate_about_axis(pr, axis=np.array([0,0,1.0]), angle_rad=prong_angle_in * math.cos(ang))
        # Slight axial twist so prongs present a flat to the stone
        rotate_about_axis(pr, axis=np.array([0,1.0,0]), angle_rad=0.20*math.sin(ang))
        # Move to rim perimeter and up to base
        translate(pr, x=px, y=prong_base_y, z=pz)

        parts.append(pr)

    # Post: along +X, centered on basket mid-plane
    post = cyl(radius=post_r, height=post_len, sections=48)
    # rotate cylinder (Y-up) to align length along X => rotate about Z by 90deg
    rotate_about_axis(post, axis=np.array([0,0,1.0]), angle_rad=math.pi/2)
    # place left end near rim outer + small embed
    post_embed = 0.25
    translate(post, x=rim_outer + post_embed + post_len/2.0, y=rim_h*0.5, z=0.0)
    parts.append(post)

    # Optional backing disk: a thin disk perpendicular to post (axis along X)
    if include_backing:
        disk_r = rim_outer + disk_extra
        disk = cyl(radius=disk_r, height=disk_thick, sections=96)
        # rotate to align height along X
        rotate_about_axis(disk, axis=np.array([0,0,1.0]), angle_rad=math.pi/2)
        # tuck it close behind the basket
        translate(disk, x=rim_outer + disk_thick/2.0, y=rim_h*0.5, z=0.0)
        parts.append(disk)

    # Concatenate all meshes (no boolean) – produces a visually “merged” STL
    model = trimesh.util.concatenate(parts)

    # Gentle smoothing of normals for nicer preview
    try:
        model = model.smoothed()
    except Exception:
        pass

    # Center Y around basket mid-height so it sits nicely in viewer
    bbox = model.bounds
    center = (bbox[0] + bbox[1]) / 2.0
    # keep ground near y=0 (basket’s base near grid)
    desired_y = rim_h * 0.1
    translate(model, x=-center[0], y=desired_y - center[1], z=-center[2])

    return model

# ---- routes ----------------------------------------------------------------

@app.get('/health')
def health():
    return jsonify({'ok': True})

@app.post('/api/generate')
def api_generate():
    """
    Body: {
      stoneDiameterMm, seatClearanceMm, headStyle, prongThicknessMm, prongHeightMm?,
      basketWallThicknessMm, postDiameterMm, postLengthMm,
      includeBackingDisk?, backDiskExtraRadius?, backDiskThickness?
    }
    """
    params = request.get_json(silent=True) or {}
    mesh = build_stud(params)

    # Export STL (binary) into memory and return
    stl_bytes = mesh.export(file_type='stl')
    # trimesh may return either bytes or str; ensure bytes
    if isinstance(stl_bytes, str):
        stl_bytes = stl_bytes.encode('utf-8')

    return Response(
        stl_bytes,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': 'attachment; filename="stud.stl"'}
    )

@app.post('/api/generate/step')
def api_generate_step():
    # Placeholder STEP: real STEP export needs OpenCascade/OCCT which we are avoiding here
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
    # Local dev
    app.run(host='0.0.0.0', port=8000, debug=True)
