# app.py — CadQuery/OpenCascade backend for basket stud settings
# Endpoints:
#   GET  /health
#   POST /api/generate        -> STL (attachment)
#   POST /api/generate/step   -> STEP (attachment)

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import cadquery as cq
from cadquery import exporters
import tempfile, os, math

app = Flask(__name__)
CORS(app)

# -------------------- helpers --------------------

def _f(d, k, default):  # float
    try:
        return float(d.get(k, default))
    except Exception:
        return float(default)

def _i(d, k, default):  # int
    try:
        return int(d.get(k, default))
    except Exception:
        return int(default)

def _b(d, k, default):  # bool
    v = d.get(k, default)
    if isinstance(v, bool): return v
    if isinstance(v, str):  return v.strip().lower() in ("1","true","yes","on")
    return bool(v)

def _export_bytes(shape, kind: str) -> bytes:
    assert kind in ("stl", "step")
    suffix = ".stl" if kind == "stl" else ".step"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tf:
        if kind == "stl":
            exporters.export(shape, tf.name, tolerance=0.001, angularTolerance=0.15)
        else:
            exporters.export(shape, tf.name)  # STEP
        tf.seek(0)
        return tf.read()

# -------------------- CAD core --------------------

def build_stud(p: dict) -> cq.Workplane:
    # ----- primary inputs (mm) -----
    stone_d      = _f(p, "stoneDiameterMm",        6.0)
    seat_clear   = _f(p, "seatClearanceMm",        0.15)  # radial clearance to stone
    rim_wall     = _f(p, "rimWallThicknessMm",     0.80)  # outer wall thickness (radial)
    rim_h        = _f(p, "rimHeightMm",            1.20)
    seat_drop    = _f(p, "seatDropMm",             0.18)  # vertical drop of seat from rim top

    prong_n      = _i(p, "prongCount",             4)
    prong_heel   = _f(p, "prongHeelDiaMm",         0.90)  # diameter at heel
    prong_tip    = _f(p, "prongTipDiaMm",          0.68)  # diameter near tip
    prong_h      = _f(p, "prongHeightMm",          2.8)
    prong_tilt   = _f(p, "prongTiltDeg",           22.0)

    gallery_drop = _f(p, "galleryDropMm",          1.20)  # distance from rim mid-plane to lower ring mid-plane
    gallery_h    = _f(p, "galleryHeightMm",        0.80)
    bridge_w     = _f(p, "bridgeWidthMm",          0.80)
    bridge_t     = _f(p, "bridgeThickMm",          0.70)

    post_d       = _f(p, "postDiameterMm",         0.95)
    post_len     = _f(p, "postLengthMm",           10.0)

    add_cross    = _b(p, "addSeatCrossRails",      stone_d < 5.0)  # default on for small stones

    # ----- derived geometry -----
    seat_r       = max(0.8, 0.5*stone_d - seat_clear)          # seat radius (stone sits here)
    rim_inner    = max(1.2, seat_r - 0.10)                     # tiny bearing under girdle
    rim_outer    = rim_inner + rim_wall                        # outer band radius
    rim_top_z    = +0.5*rim_h
    rim_bot_z    = -0.5*rim_h

    # ----- 1) Rim ring with inner seat ledge -----
    rim = (
        cq.Workplane("XY")
          .circle(rim_outer)
          .extrude(rim_h)
          .cut(cq.Workplane("XY").circle(rim_inner).extrude(rim_h + 0.05))
          .translate((0,0,-0.5*rim_h))
    )
    # seat ledge: cut down slightly from top so a shoulder remains
    seat_cut = (
        cq.Workplane("XY")
          .circle(seat_r)
          .extrude(seat_drop)
          .translate((0,0,rim_top_z - seat_drop))
    )
    rim = rim.cut(seat_cut)

    # soften rim a bit
    try:
        rim = rim.edges(">Z or <Z").fillet(0.08)
    except Exception:
        pass

    body = rim

    # ----- 2) Lower gallery ring -----
    gal_mid_z = -gallery_drop
    gallery = (
        cq.Workplane("XY")
          .circle(rim_inner)       # similar ID as seat ledge region
          .offset2D(rim_wall*0.65) # slim ring
          .extrude(gallery_h)
          .translate((0,0,gal_mid_z - 0.5*gallery_h))
    )
    body = body.union(gallery)

    # ----- 3) Inter-prong bridges (straight struts for now) -----
    # Place them halfway between prongs: offset angle = 180/prong_n
    inter_step = 360.0/prong_n
    half = 0.5*inter_step
    for k in range(prong_n):
        ang = k*inter_step + half
        # local plane facing outward at angle ang
        wp = (
            cq.Workplane("XY")
              .transformed(rotate=(0,0,ang))
        )
        # rectangular strut from gallery ring to rim band
        span_z = (rim_bot_z + 0.20, gal_mid_z + 0.5*gallery_h)  # bottom to top approx
        z0, z1 = min(span_z), max(span_z)
        strut_len = rim_outer - (rim_inner-0.10)
        strut = (
            wp.center(rim_inner-0.10 + 0.5*strut_len, 0)
              .box(strut_len, bridge_w, (z1-z0)+0.2, centered=(True, True, True))
              .translate((0,0,0.5*(z0+z1)))
        )
        try:
            strut = strut.edges("|Z").fillet(min(0.25, 0.5*bridge_w))
        except Exception:
            pass
        body = body.union(strut)

    # ----- 4) Prongs (tapered), evenly spaced, with inward tilt -----
    heel_r = 0.5*prong_heel
    tip_r  = 0.5*prong_tip
    heel_z = rim_top_z - 0.05  # heel meets near top outer edge
    tip_z  = heel_z + prong_h

    prong_proto = (
        cq.Workplane("XY")
          .center(rim_outer, 0)
          .circle(heel_r)
          .workplane(offset=prong_h)
          .center(0,0)
          .circle(tip_r)
          .loft()
          .translate((0,0,heel_z))
          .rotate((rim_outer,0,heel_z),(rim_outer,1,heel_z), -prong_tilt)  # tilt inward about local tangent (Y at +X)
    )

    # tiny claw facet: cut a shallow chamfer plane at the very tip
    try:
        prong_proto = prong_proto.faces(">Z").chamfer(min(0.10, 0.35*prong_tip))
    except Exception:
        pass

    # heel blend: small fillet where heel meets outer rim
    try:
        prong_proto = prong_proto.edges("|Z").fillet(0.10)
    except Exception:
        pass

    step = 360.0/prong_n
    prongs = cq.Workplane("XY")
    unit = prong_proto.val()
    for a in [i*step for i in range(prong_n)]:
        prongs = prongs.add(unit.rotate((0,0,0),(0,0,1), a))
    prongs = prongs.combineSolids()
    body = body.union(prongs)

    # ----- 5) Optional seat cross rails (useful for small stones) -----
    if add_cross:
        rail_w = 0.70
        rail_h = 0.60
        rail_len = 2.0*rim_inner*0.96
        z_pos = rim_top_z - seat_drop - 0.12
        rx = cq.Workplane("XY").box(rail_len, rail_w, rail_h).translate((0,0,z_pos))
        ry = cq.Workplane("XY").box(rail_w, rail_len, rail_h).translate((0,0,z_pos))
        body = body.union(rx).union(ry)

    # ----- 6) Post (axial) -----
    post = (
        cq.Workplane("XY")
          .circle(0.5*post_d)
          .extrude(post_len)
          .translate((0,0,gal_mid_z - 0.5*gallery_h))  # start near gallery plane
    )
    body = body.union(post)

    # ----- 7) Orient for viewer: basket axis +Y, post +Y -----
    # We built along +Z; rotate so Z->Y
    body = body.rotate((0,0,0), (1,0,0), -90)

    return body

# -------------------- routes --------------------

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
