# app.py — JewelCAD backend on CadQuery/OpenCascade (solid modeling)
# Endpoints:
#   GET  /health
#   POST /api/generate        -> STL (attachment)
#   POST /api/generate/step   -> STEP (attachment)
#
# Notes:
# - Solid/boolean modeling (no trimesh). Clean, manifold solids.
# - Built in Z-up for robustness, then rotated to Y-up so:
#     basket axis = +Y, post = +X  (matches your viewer)
# - Parametric: stoneDiameterMm, seatClearanceMm, basketWallThicknessMm,
#   prongCount (4/6), prongThicknessMm, prongHeightMm, postDiameterMm,
#   postLengthMm, includeBackingDisk, backDiskExtraRadius, backDiskThickness

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import os
import io
import math
import tempfile
import cadquery as cq
from cadquery import exporters

app = Flask(__name__)
CORS(app)

# ---------------------- helpers ----------------------

def _to_float(d, key, default):
    try:
        return float(d.get(key, default))
    except Exception:
        return float(default)

def _to_bool(d, key, default):
    v = d.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)

def _export_bytes(shape, kind: str) -> bytes:
    """
    kind: 'stl' or 'step'
    """
    assert kind in ("stl", "step")
    suffix = ".stl" if kind == "stl" else ".step"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tf:
        if kind == "stl":
            # tight but safe tolerances; mm units
            exporters.export(shape, tf.name, tolerance=0.001, angularTolerance=0.1)
        else:
            exporters.export(shape, tf.name)
        tf.seek(0)
        return tf.read()

# ---------------------- CAD logic ----------------------

def build_stud(params: dict) -> cq.Workplane:
    # ---- inputs (mm) ----
    stone_d   = _to_float(params, 'stoneDiameterMm', 6.0)
    seat_cl   = _to_float(params, 'seatClearanceMm', 0.15)     # clearance between stone & seat
    wall_th   = _to_float(params, 'basketWallThicknessMm', 0.8)
    rim_h     = _to_float(params, 'rimHeightMm', 1.10)

    prong_n   = int(params.get('prongCount', 4))
    if prong_n not in (4, 6): prong_n = 4
    prong_t   = _to_float(params, 'prongThicknessMm', 0.9)     # square-ish or round section proxy
    prong_r   = max(0.25, 0.5 * prong_t)                       # round approximation
    prong_h   = _to_float(params, 'prongHeightMm', max(1.2, 0.32*stone_d))
    tilt_deg  = _to_float(params, 'prongTiltDeg', 18)

    post_d    = _to_float(params, 'postDiameterMm', 0.9)
    post_len  = _to_float(params, 'postLengthMm', 10.0)
    post_r    = max(0.25, post_d/2.0)

    use_disk  = _to_bool(params, 'includeBackingDisk', True)
    disk_extra= _to_float(params, 'backDiskExtraRadius', 0.25)
    disk_t    = _to_float(params, 'backDiskThickness', 0.7)

    # rails/seat defaults
    rail_w    = _to_float(params, 'railWidthMm', 0.7)
    rail_h    = _to_float(params, 'railHeightMm', 0.7)

    # ---- derived ----
    # inner seat diameter slightly smaller than stone so it sits; clearance reduces seat OD
    seat_d    = max(1.0, stone_d - seat_cl)
    rim_inner = max(1.5, seat_d/2.0 - 0.05)                    # leave small ledge
    rim_outer = rim_inner + wall_th
    rim_OD    = 2.0 * rim_outer
    rim_ID    = 2.0 * rim_inner

    # ---- 1) Basket rim (band) ----
    rim = (
        cq.Workplane("XY")
        .circle(rim_outer)
        .extrude(rim_h)
        .cut(cq.Workplane("XY").circle(rim_inner).extrude(rim_h + 0.05))
    ).translate((0, 0, -rim_h/2.0))  # center about Z=0

    # ---- 2) Cross rails (gallery/seat) inside rim ----
    rail_len = rim_ID * 0.96
    z_pos    = -0.05  # slightly below mid-plane
    rail_x = cq.Workplane("XY").box(rail_len, rail_w, rail_h).translate((0, 0, z_pos))
    rail_y = cq.Workplane("XY").box(rail_w, rail_len, rail_h).translate((0, 0, z_pos))
    rails = rail_x.union(rail_y)

    body = rim.union(rails)

    # ---- 3) Prongs (round section, tilted inward) ----
    # Build one prong at +X, then polar copy about Z.
    z_top = rim_h/2.0
    base_x = rim_outer
    base_y = 0.0

    pr0 = (
        cq.Workplane("XY")
        .center(base_x, base_y)
        .circle(prong_r)
        .extrude(prong_h)
        .translate((0, 0, z_top))  # base sits on rim top
    )
    # tilt about local tangential axis (+Y) at the base point
    pr0 = pr0.rotate((base_x, base_y, z_top), (base_x, base_y + 1.0, z_top), -tilt_deg)

    pr_solid = pr0.val()
    prongs_wp = cq.Workplane("XY")
    step_deg = 360 // prong_n
    for a in range(0, 360, step_deg):
        prongs_wp = prongs_wp.add(pr_solid.rotate((0, 0, 0), (0, 0, 1), a))
    prongs_wp = prongs_wp.combineSolids()
    body = body.union(prongs_wp)

    # ---- 4) Post along +X, anchored at rim outer face mid-height ----
    # Place the YZ workplane at X = rim_outer + small gap; extrude +X.
    post_offset_x = rim_outer + 0.15
    post = (
        cq.Workplane("YZ")
        .workplane(offset=post_offset_x)
        .circle(post_r)
        .extrude(post_len)  # +X direction
    )
    body = body.union(post)

    # ---- 5) Backing disk (optional), coaxial with post ----
    if use_disk:
        disk_r = rim_outer + disk_extra
        # Put disk so its mid-plane touches the basket face; extrude thinly in +X.
        disk = (
            cq.Workplane("YZ")
            .workplane(offset=post_offset_x - disk_t)
            .circle(disk_r)
            .extrude(disk_t)
        )
        body = body.union(disk)

    # ---- 6) Gentle fillets for nicer look (best-effort; keep tiny) ----
    try:
        body = body.edges(">Z or <Z").fillet(0.08)  # rim top/bottom outer edges
    except Exception:
        pass
    try:
        body = body.edges("|Z").fillet(0.05)       # vertical edges (rails)
    except Exception:
        pass

    # ---- 7) Orient to Y-up for your viewer: Z->Y (rotate -90° about X) ----
    body = body.rotate((0, 0, 0), (1, 0, 0), -90)

    return body

# ---------------------- routes ----------------------

@app.get('/health')
def health():
    return jsonify({"ok": True})

@app.post('/api/generate')
def api_generate():
    params = request.get_json(silent=True) or {}
    model = build_stud(params)

    stl_bytes = _export_bytes(model, "stl")
    return Response(
        stl_bytes,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="stud.stl"'}
    )

@app.post('/api/generate/step')
def api_generate_step():
    params = request.get_json(silent=True) or {}
    model = build_stud(params)

    step_bytes = _export_bytes(model, "step")
    return Response(
        step_bytes,
        mimetype="application/step",
        headers={"Content-Disposition": 'attachment; filename="stud.step"'}
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
