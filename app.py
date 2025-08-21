from __future__ import annotations
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import io, math, struct
from typing import List, Tuple

# --- Minimal numeric helpers (no external geom libs) ---
Vec3 = Tuple[float, float, float]
Tri = Tuple[Vec3, Vec3, Vec3]

def _add(a: Vec3, b: Vec3) -> Vec3: return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def _sub(a: Vec3, b: Vec3) -> Vec3: return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def _cross(a: Vec3, b: Vec3) -> Vec3: return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _norm(a: Vec3) -> float: return math.sqrt(a[0]**2 + a[1]**2 + a[2]**2)
def _normalize(a: Vec3) -> Vec3:
    n = _norm(a)
    return (0.0, 0.0, 0.0) if n == 0 else (a[0]/n, a[1]/n, a[2]/n)

def _write_binary_stl(tris: List[Tri]) -> bytes:
    """Write triangles as binary STL (normals auto-computed)."""
    buf = io.BytesIO()
    buf.write(b'JewelCAD_Stud'.ljust(80, b'\0'))
    buf.write(struct.pack('<I', len(tris)))
    for v1, v2, v3 in tris:
        n = _normalize(_cross(_sub(v2, v1), _sub(v3, v1)))
        buf.write(struct.pack('<3f', *n))
        buf.write(struct.pack('<3f', *v1))
        buf.write(struct.pack('<3f', *v2))
        buf.write(struct.pack('<3f', *v3))
        buf.write(struct.pack('<H', 0))  # attr
    return buf.getvalue()

# --- Primitive builders (cylinders, rings) ---

def cylinder(radius: float, height: float, segments: int,
             axis: str = 'y', center: Vec3 = (0.0, 0.0, 0.0)) -> List[Tri]:
    """
    Closed cylinder with caps. Default axis 'y' (height along +Y).
    axis: 'x' | 'y' | 'z'
    center is the center of the cylinder (mid-height).
    """
    tris: List[Tri] = []
    h2 = height * 0.5
    # Build circle in local Y-up, then rotate axes at the end.
    circle = []
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        circle.append((radius * math.cos(a), 0.0, radius * math.sin(a)))

    # side quads -> two triangles each
    for i in range(segments):
        i2 = (i + 1) % segments
        x1, _, z1 = circle[i]
        x2, _, z2 = circle[i2]
        # bottom/top ring vertices
        b1 = (x1, -h2, z1)
        b2 = (x2, -h2, z2)
        t1 = (x1, +h2, z1)
        t2 = (x2, +h2, z2)
        tris.append((b1, b2, t2))
        tris.append((b1, t2, t1))

    # bottom cap (fan)
    for i in range(1, segments - 1):
        v0 = (0.0, -h2, 0.0)
        v1 = (circle[i][0], -h2, circle[i][2])
        v2 = (circle[i+1][0], -h2, circle[i+1][2])
        tris.append((v0, v2, v1))  # CW so normal = -Y

    # top cap (fan)
    for i in range(1, segments - 1):
        v0 = (0.0, +h2, 0.0)
        v1 = (circle[i+1][0], +h2, circle[i+1][2])
        v2 = (circle[i][0], +h2, circle[i][2])
        tris.append((v0, v2, v1))  # CCW so normal = +Y

    # re-orient + translate
    def xform(p: Vec3) -> Vec3:
        x, y, z = p
        if axis == 'y':
            q = (x, y, z)
        elif axis == 'x':
            q = (y, x, z)  # swap x<->y so height goes along +X
        elif axis == 'z':
            q = (x, z, y)  # height along +Z
        else:
            q = (x, y, z)
        return _add(q, center)

    return [(xform(a), xform(b), xform(c)) for (a, b, c) in tris]

def ring(inner_r: float, outer_r: float, height: float, segments: int,
         center_y: float = 0.0) -> List[Tri]:
    """
    Vertical ring (a short tube): outer and inner cylinders + top/bottom ring faces.
    Axis is Y.
    """
    tris: List[Tri] = []
    h2 = height * 0.5

    # Create circle points for outer and inner rings
    outer_circle = []
    inner_circle = []
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        outer_circle.append((outer_r * math.cos(a), outer_r * math.sin(a)))
        inner_circle.append((inner_r * math.cos(a), inner_r * math.sin(a)))

    # Outer wall
    for i in range(segments):
        i2 = (i + 1) % segments
        x1, z1 = outer_circle[i]
        x2, z2 = outer_circle[i2]
        b1 = (x1, center_y - h2, z1)
        b2 = (x2, center_y - h2, z2)
        t1 = (x1, center_y + h2, z1)
        t2 = (x2, center_y + h2, z2)
        tris.append((b1, b2, t2))
        tris.append((b1, t2, t1))

    # Inner wall (reversed winding for inward normals)
    for i in range(segments):
        i2 = (i + 1) % segments
        x1, z1 = inner_circle[i]
        x2, z2 = inner_circle[i2]
        b1 = (x1, center_y - h2, z1)
        b2 = (x2, center_y - h2, z2)
        t1 = (x1, center_y + h2, z1)
        t2 = (x2, center_y + h2, z2)
        tris.append((b1, t2, b2))  # Reversed
        tris.append((b1, t1, t2))  # Reversed

    # Top ring face
    for i in range(segments):
        i2 = (i + 1) % segments
        out1 = (outer_circle[i][0], center_y + h2, outer_circle[i][1])
        out2 = (outer_circle[i2][0], center_y + h2, outer_circle[i2][1])
        in1 = (inner_circle[i][0], center_y + h2, inner_circle[i][1])
        in2 = (inner_circle[i2][0], center_y + h2, inner_circle[i2][1])
        tris.append((out1, out2, in2))
        tris.append((out1, in2, in1))

    # Bottom ring face (reversed for downward normal)
    for i in range(segments):
        i2 = (i + 1) % segments
        out1 = (outer_circle[i][0], center_y - h2, outer_circle[i][1])
        out2 = (outer_circle[i2][0], center_y - h2, outer_circle[i2][1])
        in1 = (inner_circle[i][0], center_y - h2, inner_circle[i][1])
        in2 = (inner_circle[i2][0], center_y - h2, inner_circle[i2][1])
        tris.append((out1, in2, out2))
        tris.append((out1, in1, in2))

    return tris

# --- Stud builder ---

def build_stud(
    stone_diameter: float = 6.5,
    head_style: str = '4-prong',
    prong_thickness: float = 0.9,
    prong_height: float = 1.6,
    basket_wall_thickness: float = 0.8,
    post_diameter: float = 0.9,
    post_length: float = 10.0,
    include_backing_disk: bool = False,
    backing_extra_radius: float = 0.25,
    backing_thickness: float = 0.7,
    segments: int = 48
) -> List[Tri]:
    """
    Compose a professional stud from:
      - basket rim (ring)
      - vertical prongs (tapered cylinders)
      - post along +X (cylinder)
      - optional backing disk
    Units: mm
    """
    tris: List[Tri] = []

    # Calculate dimensions
    seat_radius = stone_diameter * 0.5
    rim_inner = seat_radius + 0.1  # Slightly larger than stone
    rim_outer = rim_inner + basket_wall_thickness
    rim_height = 1.2  # Taller basket for better stone seating
    rim_base_y = 0.0
    rim_center_y = rim_base_y + rim_height * 0.5

    # 1) Basket rim - high quality ring
    tris += ring(rim_inner, rim_outer, rim_height, segments, center_y=rim_center_y)

    # 2) Prongs - positioned on rim, angled slightly inward
    prong_r = prong_thickness * 0.5
    prong_base_y = rim_base_y + rim_height
    prong_n = 6 if head_style == '6-prong' else 4
    prong_radius_position = (rim_inner + rim_outer) * 0.5  # Middle of rim wall
    
    for i in range(prong_n):
        angle = 2.0 * math.pi * i / prong_n
        x = prong_radius_position * math.cos(angle)
        z = prong_radius_position * math.sin(angle)
        
        # Create slightly tapered prong by using smaller radius at top
        # For now using cylinder, but could enhance with taper
        tris += cylinder(
            radius=prong_r,
            height=prong_height,
            segments=max(12, segments//4),
            axis='y',
            center=(x, prong_base_y + prong_height * 0.5, z)
        )

    # 3) Post: horizontal along +X axis
    post_r = post_diameter * 0.5
    post_start_x = rim_outer + 0.5  # Small gap from rim
    post_center_x = post_start_x + post_length * 0.5
    
    tris += cylinder(
        radius=post_r,
        height=post_length,
        segments=max(16, segments//3),
        axis='x',
        center=(post_center_x, rim_center_y, 0.0)
    )

    # 4) Optional backing disk (butterfly clutch)
    if include_backing_disk:
        disk_radius = post_r + backing_extra_radius + 1.5  # Larger disk
        disk_thickness = backing_thickness
        disk_x = post_start_x + post_length + 0.5  # Small gap after post
        
        tris += cylinder(
            radius=disk_radius,
            height=disk_thickness,
            segments=max(24, segments//2),
            axis='x',
            center=(disk_x + disk_thickness * 0.5, rim_center_y, 0.0)
        )

    return tris

# --- Flask app ---

app = Flask(__name__)
CORS(app)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"ok": True})

@app.route('/api/generate', methods=['POST', 'OPTIONS'])
def generate_stl():
    """
    Main STL generation endpoint matching Bolt's API call.
    Accepts JSON with stud parameters.
    """
    if request.method == 'OPTIONS':
        return '', 200
    
    # Get parameters from request, matching Bolt's field names
    spec = request.get_json(force=True, silent=True) or {}
    
    # Build the stud with parameters
    tris = build_stud(
        stone_diameter=float(spec.get("stoneDiameterMm", 6.5)),
        head_style=str(spec.get("headStyle", "4-prong")),
        prong_thickness=float(spec.get("prongThicknessMm", 0.9)),
        prong_height=float(spec.get("prongHeightMm", 1.6)),
        basket_wall_thickness=float(spec.get("basketWallThicknessMm", 0.8)),
        post_diameter=float(spec.get("postDiameterMm", 0.9)),
        post_length=float(spec.get("postLengthMm", 10.0)),
        include_backing_disk=bool(spec.get("includeBackingDisk", False)),
        backing_extra_radius=float(spec.get("backingExtraRadiusMm", 0.25)),
        backing_thickness=float(spec.get("backingThicknessMm", 0.7)),
        segments=48  # High quality
    )
    
    # Generate binary STL
    stl_bytes = _write_binary_stl(tris)
    
    return Response(
        stl_bytes,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=stud.stl"}
    )

@app.route('/api/generate/step', methods=['POST', 'OPTIONS'])
def generate_step():
    """STEP file generation endpoint (placeholder)"""
    if request.method == 'OPTIONS':
        return '', 200
    
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
    
    return Response(
        step_content,
        mimetype="application/step",
        headers={"Content-Disposition": "attachment; filename=stud.step"}
    )

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)