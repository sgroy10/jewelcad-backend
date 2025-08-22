# app.py — Flask backend with strict CORS for Bolt/Railway

from flask import Flask, jsonify, request, Response, make_response
from flask_cors import CORS
import math
import os

app = Flask(__name__)

# Allow everything (safe for this service). Bolt runs on a credentialless origin.
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=False,
    allow_headers=["Content-Type"],
    methods=["GET", "POST", "OPTIONS"],
    max_age=86400,
)

# --- helpers ---------------------------------------------------------------

def _corsify(response: Response) -> Response:
    """Ensure CORS headers are on every response, including binary ones."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "86400"
    # If you need the browser to read Content-Disposition header:
    response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response

@app.after_request
def after(resp):
    return _corsify(resp)

def _preflight_ok() -> Response:
    resp = make_response("", 204)
    return _corsify(resp)

# --- health & simple ping --------------------------------------------------

@app.route("/", methods=["GET", "OPTIONS"])
def root():
    if request.method == "OPTIONS":
        return _preflight_ok()
    return _corsify(jsonify({"ok": True, "service": "stud-backend"}))

@app.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return _preflight_ok()
    return _corsify(jsonify({"ok": True}))

@app.route("/api/ping", methods=["GET", "OPTIONS"])
def ping():
    if request.method == "OPTIONS":
        return _preflight_ok()
    return _corsify(jsonify({"pong": True}))

# --- CAD generation (simple placeholder geometry) --------------------------

@app.route("/api/generate", methods=["POST", "OPTIONS"])
def generate():
    if request.method == "OPTIONS":
        return _preflight_ok()

    data = request.get_json(silent=True) or {}

    stone_d = float(data.get("stoneDiameterMm", 6.5))
    head_style = data.get("headStyle", "4-prong")
    prong_n = 6 if head_style == "6-prong" else 4
    prong_t = float(data.get("prongThicknessMm", 0.9))
    prong_h = float(data.get("prongHeightMm", 1.6))
    post_d = float(data.get("postDiameterMm", 0.9))
    post_l = float(data.get("postLengthMm", 10.0))

    # Build a very simple ASCII STL (ring + prongs + post) – placeholder
    stl = _build_ascii_stl(stone_d, prong_n, prong_t, prong_h, post_d, post_l)

    resp = make_response(stl)
    resp.headers["Content-Type"] = "application/octet-stream"
    resp.headers["Content-Disposition"] = 'attachment; filename="stud.stl"'
    return _corsify(resp)

@app.route("/api/generate/step", methods=["POST", "OPTIONS"])
def generate_step():
    if request.method == "OPTIONS":
        return _preflight_ok()

    step_content = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Stud Earring'),'2;1');
FILE_NAME('stud.step','2025-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('AP203'));
ENDSEC;
DATA;
#1=CLOSED_SHELL('',());
ENDSEC;
END-ISO-10303-21;"""

    resp = make_response(step_content)
    resp.headers["Content-Type"] = "application/step"
    resp.headers["Content-Disposition"] = 'attachment; filename="stud.step"'
    return _corsify(resp)

# --- naive STL builder (same spirit as your previous placeholder) ----------

def _build_ascii_stl(stone_d, prong_n, prong_t, prong_h, post_d, post_l) -> str:
    lines = ["solid stud\n"]

    rim_r = stone_d / 2 + 0.6
    rim_h = 0.8

    # crude ring side wall (8 segments)
    for i in range(8):
        a1 = i * math.pi / 4
        a2 = (i + 1) * math.pi / 4
        x1, z1 = rim_r * math.cos(a1), rim_r * math.sin(a1)
        x2, z2 = rim_r * math.cos(a2), rim_r * math.sin(a2)
        # two triangles per quad
        lines += _tri((x1, 0, z1), (x2, 0, z2), (x2, rim_h, z2))
        lines += _tri((x1, 0, z1), (x2, rim_h, z2), (x1, rim_h, z1))

    # prongs as tiny boxes
    half_t = prong_t / 2.0
    for i in range(prong_n):
        a = i * 2 * math.pi / prong_n
        px, pz = rim_r * math.cos(a), rim_r * math.sin(a)
        y0, y1 = rim_h, rim_h + prong_h
        # front
        lines += _tri((px-half_t, y0, pz-half_t), (px+half_t, y0, pz-half_t), (px+half_t, y1, pz-half_t))
        lines += _tri((px-half_t, y0, pz-half_t), (px+half_t, y1, pz-half_t), (px-half_t, y1, pz-half_t))
        # back
        lines += _tri((px-half_t, y0, pz+half_t), (px+half_t, y1, pz+half_t), (px+half_t, y0, pz+half_t))
        lines += _tri((px-half_t, y0, pz+half_t), (px-half_t, y1, pz+half_t), (px+half_t, y1, pz+half_t))

    # post as box on +X
    post_r = post_d / 2.0
    sx = rim_r + 0.6
    # top
    lines += _tri((sx,  post_r, -post_r), (sx+post_l, post_r, -post_r), (sx+post_l, post_r, post_r))
    lines += _tri((sx,  post_r, -post_r), (sx+post_l, post_r, post_r), (sx, post_r,  post_r))
    # bottom
    lines += _tri((sx, -post_r, -post_r), (sx+post_l, -post_r,  post_r), (sx+post_l, -post_r, -post_r))
    lines += _tri((sx, -post_r, -post_r), (sx,      -post_r,  post_r), (sx+post_l, -post_r,  post_r))

    lines.append("endsolid stud\n")
    return "".join(lines)

def _tri(v1, v2, v3):
    return [
        "  facet normal 0 0 0\n",
        "    outer loop\n",
        f"      vertex {v1[0]:.4f} {v1[1]:.4f} {v1[2]:.4f}\n",
        f"      vertex {v2[0]:.4f} {v2[1]:.4f} {v2[2]:.4f}\n",
        f"      vertex {v3[0]:.4f} {v3[1]:.4f} {v3[2]:.4f}\n",
        "    endloop\n",
        "  endfacet\n",
    ]

# --- entrypoint ------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
