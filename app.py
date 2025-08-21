from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import json
import math

app = Flask(__name__)
CORS(app)  # This enables CORS for all routes

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"ok": True})

@app.route('/api/generate', methods=['POST', 'OPTIONS'])
def generate():
    if request.method == 'OPTIONS':
        return '', 200
    
    # Get parameters from request
    data = request.json
    stone_diameter = data.get('stoneDiameterMm', 6.5)
    prong_count = 6 if data.get('headStyle') == '6-prong' else 4
    prong_thickness = data.get('prongThicknessMm', 0.9)
    prong_height = data.get('prongHeightMm', 1.6)
    post_diameter = data.get('postDiameterMm', 0.9)
    post_length = data.get('postLengthMm', 10.0)
    
    # Generate a real stud earring STL
    stl_content = generate_stud_stl(
        stone_diameter, 
        prong_count, 
        prong_thickness, 
        prong_height,
        post_diameter,
        post_length
    )
    
    return Response(
        stl_content,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': 'attachment; filename=stud.stl'}
    )

def generate_stud_stl(stone_d, prong_n, prong_t, prong_h, post_d, post_l):
    """Generate a parametric stud earring STL"""
    
    stl_parts = []
    stl_parts.append("solid stud_earring\n")
    
    # Calculate dimensions
    rim_radius = stone_d/2 + 0.5
    rim_height = 0.8
    
    # 1. Generate rim (basket) - simplified as octagon
    for i in range(8):
        angle1 = i * math.pi / 4
        angle2 = (i + 1) * math.pi / 4
        
        # Bottom face
        x1 = rim_radius * math.cos(angle1)
        z1 = rim_radius * math.sin(angle1)
        x2 = rim_radius * math.cos(angle2)
        z2 = rim_radius * math.sin(angle2)
        
        # Side face of rim
        stl_parts.append(f"  facet normal 0 0 0\n")
        stl_parts.append(f"    outer loop\n")
        stl_parts.append(f"      vertex {x1:.2f} 0 {z1:.2f}\n")
        stl_parts.append(f"      vertex {x2:.2f} 0 {z2:.2f}\n")
        stl_parts.append(f"      vertex {x2:.2f} {rim_height:.2f} {z2:.2f}\n")
        stl_parts.append(f"    endloop\n")
        stl_parts.append(f"  endfacet\n")
        
        stl_parts.append(f"  facet normal 0 0 0\n")
        stl_parts.append(f"    outer loop\n")
        stl_parts.append(f"      vertex {x1:.2f} 0 {z1:.2f}\n")
        stl_parts.append(f"      vertex {x2:.2f} {rim_height:.2f} {z2:.2f}\n")
        stl_parts.append(f"      vertex {x1:.2f} {rim_height:.2f} {z1:.2f}\n")
        stl_parts.append(f"    endloop\n")
        stl_parts.append(f"  endfacet\n")
    
    # 2. Generate prongs - simplified as rectangular pillars
    for i in range(prong_n):
        angle = i * 2 * math.pi / prong_n
        px = rim_radius * math.cos(angle)
        pz = rim_radius * math.sin(angle)
        
        # Prong vertices (simplified box)
        half_t = prong_t / 2
        
        # Front face
        stl_parts.append(f"  facet normal 0 0 1\n")
        stl_parts.append(f"    outer loop\n")
        stl_parts.append(f"      vertex {px-half_t:.2f} {rim_height:.2f} {pz-half_t:.2f}\n")
        stl_parts.append(f"      vertex {px+half_t:.2f} {rim_height:.2f} {pz-half_t:.2f}\n")
        stl_parts.append(f"      vertex {px+half_t:.2f} {rim_height+prong_h:.2f} {pz-half_t:.2f}\n")
        stl_parts.append(f"    endloop\n")
        stl_parts.append(f"  endfacet\n")
        
        stl_parts.append(f"  facet normal 0 0 1\n")
        stl_parts.append(f"    outer loop\n")
        stl_parts.append(f"      vertex {px-half_t:.2f} {rim_height:.2f} {pz-half_t:.2f}\n")
        stl_parts.append(f"      vertex {px+half_t:.2f} {rim_height+prong_h:.2f} {pz-half_t:.2f}\n")
        stl_parts.append(f"      vertex {px-half_t:.2f} {rim_height+prong_h:.2f} {pz-half_t:.2f}\n")
        stl_parts.append(f"    endloop\n")
        stl_parts.append(f"  endfacet\n")
        
        # Back face
        stl_parts.append(f"  facet normal 0 0 -1\n")
        stl_parts.append(f"    outer loop\n")
        stl_parts.append(f"      vertex {px-half_t:.2f} {rim_height:.2f} {pz+half_t:.2f}\n")
        stl_parts.append(f"      vertex {px+half_t:.2f} {rim_height+prong_h:.2f} {pz+half_t:.2f}\n")
        stl_parts.append(f"      vertex {px+half_t:.2f} {rim_height:.2f} {pz+half_t:.2f}\n")
        stl_parts.append(f"    endloop\n")
        stl_parts.append(f"  endfacet\n")
        
        stl_parts.append(f"  facet normal 0 0 -1\n")
        stl_parts.append(f"    outer loop\n")
        stl_parts.append(f"      vertex {px-half_t:.2f} {rim_height:.2f} {pz+half_t:.2f}\n")
        stl_parts.append(f"      vertex {px-half_t:.2f} {rim_height+prong_h:.2f} {pz+half_t:.2f}\n")
        stl_parts.append(f"      vertex {px+half_t:.2f} {rim_height+prong_h:.2f} {pz+half_t:.2f}\n")
        stl_parts.append(f"    endloop\n")
        stl_parts.append(f"  endfacet\n")
    
    # 3. Generate post - simplified as box along X axis
    post_start = rim_radius + 0.5
    post_r = post_d / 2
    
    # Post top face
    stl_parts.append(f"  facet normal 0 1 0\n")
    stl_parts.append(f"    outer loop\n")
    stl_parts.append(f"      vertex {post_start:.2f} {post_r:.2f} {-post_r:.2f}\n")
    stl_parts.append(f"      vertex {post_start+post_l:.2f} {post_r:.2f} {-post_r:.2f}\n")
    stl_parts.append(f"      vertex {post_start+post_l:.2f} {post_r:.2f} {post_r:.2f}\n")
    stl_parts.append(f"    endloop\n")
    stl_parts.append(f"  endfacet\n")
    
    stl_parts.append(f"  facet normal 0 1 0\n")
    stl_parts.append(f"    outer loop\n")
    stl_parts.append(f"      vertex {post_start:.2f} {post_r:.2f} {-post_r:.2f}\n")
    stl_parts.append(f"      vertex {post_start+post_l:.2f} {post_r:.2f} {post_r:.2f}\n")
    stl_parts.append(f"      vertex {post_start:.2f} {post_r:.2f} {post_r:.2f}\n")
    stl_parts.append(f"    endloop\n")
    stl_parts.append(f"  endfacet\n")
    
    # Post bottom face
    stl_parts.append(f"  facet normal 0 -1 0\n")
    stl_parts.append(f"    outer loop\n")
    stl_parts.append(f"      vertex {post_start:.2f} {-post_r:.2f} {-post_r:.2f}\n")
    stl_parts.append(f"      vertex {post_start+post_l:.2f} {-post_r:.2f} {post_r:.2f}\n")
    stl_parts.append(f"      vertex {post_start+post_l:.2f} {-post_r:.2f} {-post_r:.2f}\n")
    stl_parts.append(f"    endloop\n")
    stl_parts.append(f"  endfacet\n")
    
    stl_parts.append(f"  facet normal 0 -1 0\n")
    stl_parts.append(f"    outer loop\n")
    stl_parts.append(f"      vertex {post_start:.2f} {-post_r:.2f} {-post_r:.2f}\n")
    stl_parts.append(f"      vertex {post_start:.2f} {-post_r:.2f} {post_r:.2f}\n")
    stl_parts.append(f"      vertex {post_start+post_l:.2f} {-post_r:.2f} {post_r:.2f}\n")
    stl_parts.append(f"    endloop\n")
    stl_parts.append(f"  endfacet\n")
    
    stl_parts.append("endsolid stud_earring\n")
    
    return ''.join(stl_parts)

@app.route('/api/generate/step', methods=['POST', 'OPTIONS'])
def generate_step():
    """Generate STEP file (placeholder for now)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # For now, return a simple STEP header
    step_content = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Stud Earring'),'2;1');
FILE_NAME('stud.step','2024-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('AP203'));
ENDSEC;
DATA;
#1=CLOSED_SHELL('',(#2));
#2=ADVANCED_FACE('',(#3),#4,.T.);
ENDSEC;
END-ISO-10303-21;"""
    
    return Response(
        step_content,
        mimetype='application/step',
        headers={'Content-Disposition': 'attachment; filename=stud.step'}
    )

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)