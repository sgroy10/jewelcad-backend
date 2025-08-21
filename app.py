import math
from io import BytesIO
from dataclasses import dataclass
from typing import Optional

import cadquery as cq
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


# ---------- Spec & Defaults ----------
@dataclass
class StudSpec:
    stoneDiameterMm: float = 6.5
    seatClearanceMm: float = 0.05

    headStyle: str = "4-prong"            # "4-prong" | "6-prong"
    prongThicknessMm: float = 0.9
    prongHeightMm: Optional[float] = None # if None, auto from ratio
    prongHeightRatio: float = 0.25        # prong height = ratio * stoneDiameter

    basketWallThicknessMm: float = 0.6
    rimLiftMm: float = 0.2                # rim sits slightly above base
    rimHeightMm: float = 0.8

    postDiameterMm: float = 0.9
    postLengthMm: float = 10.0
    postEmbedMm: float = 0.20             # slight embed into rim

    includeBackingDisk: bool = True
    backingDiskExtraRadiusMm: float = 0.25
    backingDiskThicknessMm: float = 0.7
    backingDiskEmbedMm: float = 0.15      # slight embed towards rim


def _as_spec(data: dict) -> StudSpec:
    spec = StudSpec(**{k: v for k, v in (data or {}).items() if k in StudSpec.__annotations__})
    if spec.prongHeightMm is None or spec.prongHeightMm <= 0:
        spec.prongHeightMm = spec.stoneDiameterMm * spec.prongHeightRatio
    return spec


# ---------- CAD Builders (CadQuery) ----------
def build_stud(spec: StudSpec) -> cq.Workplane:
    """
    Z is 'up' (prongs go +Z). Post points +X (backwards).
    Returns a single unified solid.
    """
    # Derived dims
    seat_diam = spec.stoneDiameterMm + spec.seatClearanceMm
    seat_r = seat_diam * 0.5

    rim_inner_r = seat_r + 0.20
    rim_outer_r = rim_inner_r + max(spec.basketWallThicknessMm, 0.6)
    rim_h = spec.rimHeightMm
    rim_z0 = spec.rimLiftMm
    rim_zc = rim_z0 + rim_h * 0.5

    prong_count = 6 if str(spec.headStyle).lower().startswith("6") else 4
    prong_r = spec.prongThicknessMm * 0.5
    prong_h = spec.prongHeightMm

    post_r = spec.postDiameterMm * 0.5
    post_len = spec.postLengthMm
    post_x0 = rim_outer_r + spec.postEmbedMm  # start just behind rim
    post_zc = rim_zc                           # run through rim mid-plane

    # 1) Rim (a proper hollow ring with a tiny fillet)
    rim = (
        cq.Workplane("XY")
        .circle(rim_outer_r)
        .circle(rim_inner_r)
        .extrude(rim_h)
        .translate((0, 0, rim_z0))
        .edges("|Z").fillet(min(0.15, spec.basketWallThicknessMm * 0.45))
    )

    # 2) Prongs (simple cylinders; robust & printable)
    prongs = []
    prong_radius_for_placement = rim_outer_r  # sit at the outer rim
    for i in range(prong_count):
        ang = i * 2 * math.pi / prong_count
        px = prong_radius_for_placement * math.cos(ang)
        py = prong_radius_for_placement * math.sin(ang)
        pr = (
            cq.Workplane("XY", origin=(px, py, rim_z0 + rim_h))
            .circle(prong_r)
            .extrude(prong_h)
        )
        prongs.append(pr)

    prong_solid = cq.Workplane(obj=cq.Compound.makeCompound([p.val() for p in prongs]))

    # 3) Post (cylinder along +X) built on the YZ plane and placed at post_x0
    post = (
        cq.Workplane("YZ")
        .circle(post_r)
        .extrude(post_len)
        .translate((post_x0 + post_len * 0.5, 0, post_zc))
    )

    # 4) Optional backing disk (perp. to post, also extruded on YZ)
    solids = [rim, prong_solid, post]
    if spec.includeBackingDisk:
        disk_r = rim_outer_r + spec.backingDiskExtraRadiusMm
        disk_t = spec.backingDiskThicknessMm
        disk = (
            cq.Workplane("YZ")
            .circle(disk_r)
            .extrude(disk_t)
            .translate((post_x0 - spec.backingDiskEmbedMm, 0, post_zc))
        )
        solids.append(disk)

    # Union into one watertight solid
    model = solids[0]
    for s in solids[1:]:
        model = model.union(s)

    # Light edge rounding on prong tips (safe selector)
    try:
        model = model.edges(">Z").fillet(min(0.12, prong_r * 0.6))
    except Exception:
        pass  # fillet is optional; never break

    return model


def export_stl_bytes(shape: cq.Workplane, tolerance: float = 0.001) -> bytes:
    buf = BytesIO()
    cq.exporters.export(shape, buf, exportType="STL", tolerance=tolerance)
    return buf.getvalue()


def export_step_bytes(shape: cq.Workplane) -> bytes:
    buf = BytesIO()
    cq.exporters.export(shape, buf, exportType="STEP")
    return buf.getvalue()


# ---------- HTTP ----------
@app.get("/health")
def health() -> Response:
    return jsonify({"ok": True})


@app.post("/stud.stl")
def stud_stl() -> Response:
    spec = _as_spec(request.get_json(silent=True) or {})
    model = build_stud(spec)
    payload = export_stl_bytes(model)
    return Response(
        payload,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=stud.stl"},
    )


@app.post("/stud.step")
def stud_step() -> Response:
    spec = _as_spec(request.get_json(silent=True) or {})
    model = build_stud(spec)
    payload = export_step_bytes(model)
    return Response(
        payload,
        mimetype="application/step",
        headers={"Content-Disposition": "attachment; filename=stud.step"},
    )


if __name__ == "__main__":
    # Local run (Railway uses Procfile/gunicorn)
    import os
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
