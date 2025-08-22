# app.py — CadQuery backend (OpenCascade) for a 4/6-prong basket stud
# Endpoints:
#   GET  /health
#   POST /api/generate        -> STL (attachment)
#   POST /api/generate/step   -> STEP (attachment)
#
# Built for headless server use (Railway). Uses solid booleans/fillets and
# outputs clean, manifold STL and true STEP (AP203).
#
# Coordinate convention for your viewer:
#   - Basket axis  : +Y (Y-up)
#   - Post axis    : +X
#
# Default params target a round 6.0 mm stone and should already look “right”.

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import os
import math
import tempfile
import cadquery as cq
from cadquery import exporters

app = Flask(__name__)
CORS(app)

# ---------- small helpers ----------

def _f(d, key, default):
    try:
        return float(d.get(key, default))
    except Exception:
        return float(default)

def _i(d, key, default):
    try:
        return int(d.get(key, default))
    except Exception:
        return int(default)

def _b(d, key, default):
    v = d.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)

def _export_bytes(shape, kind: str) -> bytes:
    """kind in {'stl','step'}"""
    assert kind in ("stl", "step")
    suffix = ".stl" if kind == "stl" else ".step"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tf:
        if kind == "stl":
            # tight tolerances but safe for web
            exporters.export(shape, tf.name, tolerance=0.001, angularTolerance=0.1)
        else:
            exporters.export(shape, tf.name)
        tf.seek(0)
        return tf.read()

# ---------- core CAD ----------

def build_stud(params: dict) -> cq.Workplane:
    # -------- inputs (mm) --------
    stone_d    = _f(params, "stoneDiameterMm", 6.0)
    seat_cl    = _f(params, "seatClearanceMm", 0.15)  # stone - seat OD clearance
    wall_th    = _f(params, "basketWallThicknessMm", 0.80)
    rim_h      = _f(params, "rimHeightMm", 1.10)

    prong_n    = _i(params, "prongCount", 4)
    if prong_n not in (4, 6): prong_n = 4
    prong_t    = _f(params, "prongThicknessMm", 0.90)  # round section proxy
    prong_r    = max(0.20, 0.5 * prong_t)
    prong_h    = _f(params, "prongHeightMm", max(1.2, 0.32 * stone_d))
    prong_tilt = _f(params, "prongTiltDeg", 20.0)

    # prong “foot” pad sitting on rim top (visually cleaner joint)
    pad_w      = _f(params, "prongPadWidthMm", 0.90)   # along tangent (Y at +X prong)
    pad_d      = _f(params, "prongPadDepthMm", 0.60)   # radial depth onto rim top
    pad_h      = _f(params, "prongPadHeightMm", 0.25)
    pad_fillet = _f(params, "prongPadFilletMm", 0.10)

    post_d     = _f(params, "postDiameterMm", 0.90)
    post_len   = _f(params, "postLengthMm", 10.0)
    post_r     = max(0.20, post_d / 2.0)

    use_disk   = _b(params, "includeBackingDisk", True)
    disk_extra = _f(params, "backDiskExtraRadius", 0.25)
    disk_t     = _f(params, "backDiskThickness", 0.70)

    # -------- derived --------
    seat_d     = max(1.0, stone_d - seat_cl)          # seat ring OD
    rim_inner  = max(1.4, seat_d / 2.0 - 0.05)        # small bearing ledge
    rim_outer  = rim_inner + wall_th
    rim_ID     = 2.0 * rim_inner

    # -------- 1) Basket rim (band) --------
    rim = (
        cq.Workplane("XY")
        .circle(rim_outer)
        .extrude(rim_h)
        .cut(cq.Workplane("XY").circle(rim_inner).extrude(rim_h + 0.05))
        .translate((0, 0, -rim_h/2.0))                 # Z centered about 0
    )

    # soften outer top/bottom edges slightly
    try:
        rim = rim.edges(">Z or <Z").fillet(0.08)
    except Exception:
        pass

    # -------- 2) Seat rails (cross) --------
    rail_w = _f(params, "railWidthMm", 0.70)
    rail_h = _f(params, "railHeightMm", 0.70)
    rail_len = rim_ID * 0.96
    z_pos = -0.05  # just below rim mid-plane for a subtle shadow split

    rail_x = cq.Workplane("XY").box(rail_len, rail_w, rail_h).translate((0, 0, z_pos))
    rail_y = cq.Workplane("XY").box(rail_w, rail_len, rail_h).translate((0, 0, z_pos))
    body = rim.union(rail_x.union(rail_y))

    # -------- 3) Prong + pad at +X, then polar array --------
    z_top = rim_h / 2.0
    base_x = rim_outer
    base_y = 0.0

    # Pad sits on top face of rim
    pad = (
        cq.Workplane("XY")
        .center(base_x - pad_d/2.0, base_y)           # center so inner edge ~ at rim_outer - pad_d
        .rect(pad_d, pad_w)
        .extrude(pad_h)
        .translate((0, 0, z_top))
    )
    # soften pad edges
    try:
        pad = pad.edges("|Z").fillet(min(0.5*pad_w, pad_fillet))
    except Exception:
        pass

    # Prong grows upward from pad top, then tilts inward
    pr_base_z = z_top + pad_h
    pr = (
        cq.Workplane("XY")
        .center(base_x, base_y)
        .circle(prong_r)
        .extrude(prong_h)
        .translate((0, 0, pr_base_z))
    )
    # Tilt around tangent axis at +X (tangent = +Y there)
    pr = pr.rotate(
        (base_x, base_y, pr_base_z),
        (base_x, base_y + 1.0, pr_base_z),
        -prong_tilt
    )

    prong_unit = pad.union(pr)
    prongs = cq.Workplane("XY")
    step = 360 // prong_n
    unit = prong_unit.val()
    for ang in range(0, 360, step):
        prongs = prongs.add(unit.rotate((0, 0, 0), (0, 0, 1), ang))
    prongs = prongs.combineSolids()
    body = body.union(prongs)

    # -------- 4) Post along +X from mid-height of basket back --------
    post_offset_x = rim_outer + 0.15  # small gap into the band
    post = (
        cq.Workplane("YZ")
        .workplane(offset=post_offset_x)
        .circle(post_r)
        .extrude(post_len)  # +X
    )
    body = body.union(post)

    # -------- 5) Back disk (optional) --------
    if use_disk:
        disk_r = rim_outer + disk_extra
        disk = (
            cq.Workplane("YZ")
            .workplane(offset=post_offset_x - disk_t)
            .circle(disk_r)
            .extrude(disk_t)
        )
        body = body.union(disk)

    # -------- 6) Orient to Y-up for your viewer (Z->Y) --------
    body = body.rotate((0, 0, 0), (1, 0, 0), -90)

    return body

# ---------- routes ----------

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.post("/api/generate")
def api_generate():
    params = request.get_json(silent=True) or {}
    model = build_stud(params)
    data = _export_bytes(model, "stl")
    return Response(
        data,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="stud.stl"'}
    )

@app.post("/api/generate/step")
def api_generate_step():
    params = request.get_json(silent=True) or {}
    model = build_stud(params)
    data = _export_bytes(model, "step")
    return Response(
        data,
        mimetype="application/step",
        headers={"Content-Disposition": 'attachment; filename="stud.step"'}
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
