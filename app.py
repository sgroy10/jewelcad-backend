from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import numpy as np
import trimesh as tm

app = Flask(__name__)
CORS(app)

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.post("/api/generate")
def generate():
    data = request.get_json(force=True, silent=True) or {}

    # --- Parameters with sensible defaults (millimeters) ---
    stone_d = float(data.get("stoneDiameterMm", 6.5))
    seat_clear = float(data.get("seatClearanceMm", 0.05))
    head_style = data.get("headStyle", "4-prong")
    prong_n = 6 if head_style == "6-prong" else 4
    prong_t = float(data.get("prongThicknessMm", 0.9))
    prong_h = float(data.get("prongHeightMm", max(1.2, 0.3 * stone_d)))  # auto if not provided
    basket_wall = float(data.get("basketWallThicknessMm", 0.7))
    post_d = float(data.get("postDiameterMm", 0.9))
    post_l = float(data.get("postLengthMm", 10.0))
    include_disk = bool(data.get("includeDisk", True))
    disk_extra_r = float(data.get("diskExtraRadiusMm", 0.25))
    disk_t = float(data.get("diskThicknessMm", 0.7))

    # --- Derived ---
    seat_d = stone_d + seat_clear
    rim_inner_r = seat_d * 0.5 + 0.2
    rim_outer_r = rim_inner_r + max(basket_wall, 0.5)
    rim_mid_r = 0.5 * (rim_inner_r + rim_outer_r)
    rim_height = 0.8
    rim_y = 0.2 * prong_h
    prong_r = prong_t * 0.5
    post_r = post_d * 0.5

    meshes = []

    # 1) Rim = torus (round basket ring) sitting around (x,z), centered at y = rim_y + rim_height/2
    #    major radius = rim_mid_r, tube radius = (rim_outer_r - rim_inner_r)/2
    tube_r = 0.5 * (rim_outer_r - rim_inner_r)
    rim = tm.creation.torus(r=rim_mid_r, tube_radius=tube_r, sections=64)
    rim.apply_translation([0.0, rim_y + rim_height * 0.5, 0.0])
    meshes.append(rim)

    # 2) Vertical band (thin wall look): cylinder shell approximated by two cylinders
    band_outer = tm.creation.cylinder(radius=rim_outer_r, height=rim_height, sections=64)
    band_outer.apply_translation([0.0, rim_y + rim_height * 0.5, 0.0])
    band_inner = tm.creation.cylinder(radius=rim_inner_r, height=rim_height, sections=64)
    band_inner.apply_translation([0.0, rim_y + rim_height * 0.5, 0.0])
    # We can't boolean-subtract without external kernels, so we keep both;
    # STL viewers render union fine. For visual fidelity the torus gives the rim contour.
    meshes.extend([band_outer, band_inner])

    # 3) Prongs: cylinders placed around rim, up from rim top
    prong_base_y = rim_y + rim_height
    for i in range(prong_n):
        ang = (2.0 * np.pi * i) / prong_n
        px = rim_outer_r * np.cos(ang)
        pz = rim_outer_r * np.sin(ang)
        pr = tm.creation.cylinder(radius=prong_r, height=prong_h, sections=24)
        # Cylinder is centered; lift so its base sits at prong_base_y
        pr.apply_translation([0.0, prong_h * 0.5, 0.0])
        pr.apply_translation([px, prong_base_y, pz])
        meshes.append(pr)

    # 4) Post: cylinder along +X, starting just outside rim
    start_x = rim_outer_r + 0.20
    post = tm.creation.cylinder(radius=post_r, height=post_l, sections=32)
    # Rotate cylinder (Y axis) to align along X: rotate around Z by 90°
    post.apply_transform(tm.transformations.rotation_matrix(np.pi / 2.0, [0, 0, 1]))
    # After rotation, cylinder length is along X; move to start at start_x
    post.apply_translation([start_x + post_l * 0.5, rim_y + rim_height * 0.5, 0.0])
    meshes.append(post)

    # 5) Optional backing disk: thin cylinder along X, slightly embedded
    if include_disk:
        disk_r = rim_outer_r + disk_extra_r
        disk = tm.creation.cylinder(radius=disk_r, height=disk_t, sections=64)
        disk.apply_transform(tm.transformations.rotation_matrix(np.pi / 2.0, [0, 0, 1]))
        disk.apply_translation([0.15 + disk_t * 0.5, rim_y + rim_height * 0.5, 0.0])
        meshes.append(disk)

    # Concatenate all parts (visual union; no booleans required for STL)
    combined = tm.util.concatenate(meshes)

    # Binary STL bytes
    stl_bytes = tm.exchange.stl.export_stl_binary(combined)
    return Response(
        stl_bytes,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=stud.stl"}
    )

@app.post("/api/generate/step")
def generate_step():
    # Placeholder STEP (we'll swap in a STEP kernel later)
    content = (
        "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Stud Earring'), '2;1');\n"
        "FILE_NAME('stud.step','2025-01-01T00:00:00',(''),(''),'','','');\n"
        "FILE_SCHEMA(('AP203'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;"
    )
    return Response(
        content,
        mimetype="application/step",
        headers={"Content-Disposition": "attachment; filename=stud.step"}
    )

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
