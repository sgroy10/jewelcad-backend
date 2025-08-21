from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import json

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
    
    # Generate a simple cube STL scaled by stone diameter
    stl_content = generate_simple_stl(stone_diameter)
    
    return Response(
        stl_content,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': 'attachment; filename=stud.stl'}
    )

def generate_simple_stl(size):
    """Generate a simple cube STL"""
    # Simple ASCII STL of a cube
    stl = f"""solid cube
  facet normal 0 0 1
    outer loop
      vertex 0 0 {size}
      vertex {size} 0 {size}
      vertex {size} {size} {size}
    endloop
  endfacet
  facet normal 0 0 1
    outer loop
      vertex 0 0 {size}
      vertex {size} {size} {size}
      vertex 0 {size} {size}
    endloop
  endfacet
  facet normal 0 0 -1
    outer loop
      vertex 0 0 0
      vertex {size} {size} 0
      vertex {size} 0 0
    endloop
  endfacet
  facet normal 0 0 -1
    outer loop
      vertex 0 0 0
      vertex 0 {size} 0
      vertex {size} {size} 0
    endloop
  endfacet
  facet normal 0 1 0
    outer loop
      vertex 0 {size} 0
      vertex 0 {size} {size}
      vertex {size} {size} {size}
    endloop
  endfacet
  facet normal 0 1 0
    outer loop
      vertex 0 {size} 0
      vertex {size} {size} {size}
      vertex {size} {size} 0
    endloop
  endfacet
  facet normal 0 -1 0
    outer loop
      vertex 0 0 0
      vertex {size} 0 0
      vertex {size} 0 {size}
    endloop
  endfacet
  facet normal 0 -1 0
    outer loop
      vertex 0 0 0
      vertex {size} 0 {size}
      vertex 0 0 {size}
    endloop
  endfacet
  facet normal 1 0 0
    outer loop
      vertex {size} 0 0
      vertex {size} {size} 0
      vertex {size} {size} {size}
    endloop
  endfacet
  facet normal 1 0 0
    outer loop
      vertex {size} 0 0
      vertex {size} {size} {size}
      vertex {size} 0 {size}
    endloop
  endfacet
  facet normal -1 0 0
    outer loop
      vertex 0 0 0
      vertex 0 0 {size}
      vertex 0 {size} {size}
    endloop
  endfacet
  facet normal -1 0 0
    outer loop
      vertex 0 0 0
      vertex 0 {size} {size}
      vertex 0 {size} 0
    endloop
  endfacet
endsolid cube"""
    return stl

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)