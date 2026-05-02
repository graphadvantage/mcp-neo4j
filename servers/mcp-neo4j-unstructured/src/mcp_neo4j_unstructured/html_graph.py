import json

# Colors matching the React app exactly
_LABEL_COLORS = {
    "Chunk":         {"background": "#0A6190", "border": "#074e70", "font": "#ffffff"},
    "NarrativeText": {"background": "#0A6190", "border": "#074e70", "font": "#ffffff"},
    "Document":      {"background": "#BCF194", "border": "#8ecf68", "font": "#1a1a1a"},
    "Image":         {"background": "#FFC300", "border": "#cc9a00", "font": "#1a1a1a"},
    "Table":         {"background": "#FF8E6A", "border": "#d96b47", "font": "#1a1a1a"},
}
_ENTITY_COLOR = {"background": "#B38EFF", "border": "#8a63db", "font": "#1a1a1a"}
_DEFAULT_COLOR = {"background": "#95a5a6", "border": "#7f8c8d", "font": "#ffffff"}

# Graph Cypher queries — match the modal's UNION query exactly
SUBGRAPH_QUERIES = """
MATCH (a:Chunk)-[r:PART_OF_DOCUMENT]->(b:Document)
WHERE elementId(a) IN $ids
RETURN DISTINCT
  elementId(startNode(r)) AS src_id, labels(startNode(r)) AS src_labels, properties(startNode(r)) AS src_props,
  type(r) AS rel_type,
  elementId(endNode(r)) AS tgt_id, labels(endNode(r)) AS tgt_labels, properties(endNode(r)) AS tgt_props
UNION ALL
MATCH (a:Chunk)-[r:NEXT_CHUNK]-(b:Chunk)
WHERE elementId(a) IN $ids AND elementId(b) IN $ids
RETURN DISTINCT
  elementId(startNode(r)) AS src_id, labels(startNode(r)) AS src_labels, properties(startNode(r)) AS src_props,
  type(r) AS rel_type,
  elementId(endNode(r)) AS tgt_id, labels(endNode(r)) AS tgt_labels, properties(endNode(r)) AS tgt_props
UNION ALL
MATCH (a:Chunk)-[r:HAS_ENTITY]-(b:Entity)
WHERE elementId(a) IN $ids AND elementId(b) IN $ids
RETURN DISTINCT
  elementId(startNode(r)) AS src_id, labels(startNode(r)) AS src_labels, properties(startNode(r)) AS src_props,
  type(r) AS rel_type,
  elementId(endNode(r)) AS tgt_id, labels(endNode(r)) AS tgt_labels, properties(endNode(r)) AS tgt_props
UNION ALL
MATCH (a:Chunk)-[r:RELATED_CONTENT]->(b)
WHERE elementId(a) IN $ids
  AND (b:Image OR b:Table)
  AND b.aspect_ratio < 10
  AND b.bytes > 9216
RETURN DISTINCT
  elementId(startNode(r)) AS src_id, labels(startNode(r)) AS src_labels, properties(startNode(r)) AS src_props,
  type(r) AS rel_type,
  elementId(endNode(r)) AS tgt_id, labels(endNode(r)) AS tgt_labels, properties(endNode(r)) AS tgt_props
LIMIT 500
"""

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Neo4j Context Graph</title>
<script src="https://unpkg.com/three@0.134.0/build/three.min.js"></script>
<script src="https://unpkg.com/3d-force-graph@1.70.6"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #1a1a2e; color: #e0e0e0; display: flex;
         flex-direction: column; height: 100vh; overflow: hidden; }
  header { padding: 10px 18px; background: #16213e; border-bottom: 1px solid #0f3460;
           display: flex; align-items: center; gap: 20px; flex-shrink: 0; }
  header h1 { font-size: 14px; font-weight: 600; color: #a0c4ff; white-space: nowrap; }
  .legend { display: flex; gap: 12px; flex-wrap: wrap; }
  .legend-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #aaa; }
  .legend-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
  .main { display: flex; flex: 1; overflow: hidden; }
  #graph { flex: 1; background: #0f0f1a; position: relative; overflow: hidden; }
  .graph-controls { position: absolute; top: 10px; right: 10px; z-index: 10;
                    display: flex; flex-direction: column; gap: 6px; }
  .graph-controls button { background: #16213e; border: 1px solid #0f3460; color: #a0c4ff;
                           padding: 6px 10px; border-radius: 6px; cursor: pointer;
                           font-size: 11px; }
  .graph-controls button:hover { background: #0f3460; }
  #panel { width: 380px; flex-shrink: 0; background: #16213e;
           border-left: 1px solid #0f3460; display: flex;
           flex-direction: column; overflow: hidden; }
  #panel-header { padding: 12px 16px 8px; border-bottom: 1px solid #0f3460; flex-shrink: 0; }
  #panel-header .node-type { font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
                              color: #a0c4ff; text-transform: uppercase; }
  #panel-header .node-name { font-size: 13px; color: #ddd; margin-top: 3px;
                              word-break: break-word; }
  #panel-empty { flex: 1; display: flex; align-items: center; justify-content: center;
                 color: #444; font-style: italic; font-size: 13px; }
  #panel-body { flex: 1; overflow-y: auto; padding: 14px; display: none; }
  .section-label { font-size: 10px; font-weight: 700; letter-spacing: 0.1em; color: #a0c4ff;
                   text-transform: uppercase; margin: 12px 0 6px; }
  .section-label:first-child { margin-top: 0; }
  .text-block { background: #0f0f1a; padding: 10px 12px; border-radius: 6px;
                font-size: 12px; line-height: 1.65; color: #cce0ff;
                white-space: pre-wrap; word-break: break-word; max-height: 400px;
                overflow-y: auto; border: 1px solid #1a2a4a; }
  .prop-row { font-size: 12px; margin-bottom: 5px; word-break: break-word; }
  .prop-key { color: #a0c4ff; font-weight: 600; margin-right: 4px; }
  img.node-img { max-width: 100%; border-radius: 6px; margin-top: 4px;
                 border: 1px solid #0f3460; display: block; }
  .table-wrap { overflow-x: auto; margin-top: 4px; border: 1px solid #0f3460; border-radius: 6px; }
  .table-wrap table { border-collapse: collapse; font-size: 11px; background: #0f0f1a;
                      width: 100%; }
  .table-wrap td, .table-wrap th { border: 1px solid #1a2a4a; padding: 4px 8px; }
  .table-wrap th { background: #16213e; color: #a0c4ff; }
  #node-count { font-size: 11px; color: #666; white-space: nowrap; margin-left: auto; }
</style>
</head>
<body>
<header>
  <h1>Neo4j Context Graph</h1>
  <div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#0A6190"></div>Chunk</div>
    <div class="legend-item"><div class="legend-dot" style="background:#BCF194"></div>Document</div>
    <div class="legend-item"><div class="legend-dot" style="background:#FFC300"></div>Image</div>
    <div class="legend-item"><div class="legend-dot" style="background:#FF8E6A"></div>Table</div>
    <div class="legend-item"><div class="legend-dot" style="background:#B38EFF"></div>Entity</div>
  </div>
  <div id="node-count"></div>
</header>
<div class="main">
  <div id="graph">
    <div class="graph-controls">
      <button onclick="fitAll()">Fit</button>
      <button onclick="resetView()">Reset</button>
    </div>
  </div>
  <div id="panel">
    <div id="panel-header">
      <div class="node-type" id="panel-type">NODE CONTENT</div>
      <div class="node-name" id="panel-name"></div>
    </div>
    <div id="panel-empty">Click a node to inspect its content</div>
    <div id="panel-body"></div>
  </div>
</div>
<script>
const NODES_DATA = __NODES_JSON__;
const LINKS_DATA = __EDGES_JSON__;
const CONTENT_MAP = __CONTENT_JSON__;

document.getElementById('node-count').textContent =
  NODES_DATA.length + ' nodes · ' + LINKS_DATA.length + ' edges';

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderPanel(nodeId) {
  const node = CONTENT_MAP[nodeId];
  if (!node) return;
  const props = node.props || {};
  const labels = node.labels || [];
  const nodeType = props.type || labels[0] || 'Node';

  document.getElementById('panel-type').textContent = nodeType.toUpperCase();
  document.getElementById('panel-name').textContent = node.display || nodeId;
  document.getElementById('panel-empty').style.display = 'none';
  const body = document.getElementById('panel-body');
  body.style.display = 'block';
  let html = '';

  if (nodeType === 'NarrativeText' || (labels.includes('Chunk') && nodeType !== 'Image' && nodeType !== 'Table')) {
    html += '<div class="section-label">narrative text</div>';
    html += '<div class="text-block">' + esc(props.text || '') + '</div>';
  }
  else if (nodeType === 'Image') {
    const img = props.image_base64 || props.image;
    if (img) {
      html += '<div class="section-label">image</div>';
      html += '<img class="node-img" src="data:image/png;base64,' + img + '" alt="image">';
    } else {
      html += '<p style="color:#666;font-size:12px">No image data on this node.</p>';
    }
    if (props.text) {
      html += '<div class="section-label">ocr text</div>';
      html += '<div class="text-block">' + esc(props.text) + '</div>';
    }
  }
  else if (nodeType === 'Table') {
    const img = props.image_base64 || props.image;
    if (img) {
      html += '<div class="section-label">table image</div>';
      html += '<img class="node-img" src="data:image/png;base64,' + img + '" alt="table">';
    }
    if (props.text_as_html) {
      html += '<div class="section-label">text_as_html</div>';
      html += '<div class="table-wrap">' + props.text_as_html + '</div>';
    }
    if (!img && !props.text_as_html) {
      html += '<p style="color:#666;font-size:12px">No table data.</p>';
    }
  }
  else if (labels.includes('Document')) {
    if (props.name) {
      html += '<div class="section-label">name</div>';
      html += '<div class="text-block">' + esc(props.name) + '</div>';
    }
    if (props.text) {
      html += '<div class="section-label">text</div>';
      html += '<div class="text-block">' + esc(props.text) + '</div>';
    }
  }
  else {
    const skip = new Set(['embedding', 'image_base64', 'image', 'text_as_html']);
    const entries = Object.entries(props).filter(([k,v]) => !skip.has(k) && typeof v !== 'object');
    entries.forEach(([k, v]) => {
      html += '<div class="prop-row"><span class="prop-key">' + esc(k) + '</span>' + esc(String(v).slice(0, 500)) + '</div>';
    });
  }

  body.innerHTML = html;
}

const graphEl = document.getElementById('graph');

function wrapText(ctx, text, maxWidth) {
  const words = text.split(' ');
  const lines = [];
  let line = '';
  for (const word of words) {
    const test = line ? line + ' ' + word : word;
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = test;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [text];
}

function makeSprite(label, bgColor, fontColor, fontSize, maxTextWidth, textAlign) {
  const fs = fontSize || 13;
  const maxW = maxTextWidth || 140;
  const align = textAlign || 'center';
  const pad = 10, lineH = Math.round(fs * 1.4);
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  ctx.font = `bold ${fs}px Arial, sans-serif`;
  const lines = wrapText(ctx, label, maxW);
  const contentW = Math.min(Math.max(...lines.map(l => ctx.measureText(l).width)), maxW);
  canvas.width = contentW + pad * 2;
  canvas.height = lines.length * lineH + pad;
  ctx.fillStyle = bgColor;
  const r = 3, w = canvas.width, h = canvas.height;
  ctx.beginPath();
  ctx.moveTo(r, 0); ctx.lineTo(w - r, 0);
  ctx.quadraticCurveTo(w, 0, w, r);
  ctx.lineTo(w, h - r);
  ctx.quadraticCurveTo(w, h, w - r, h);
  ctx.lineTo(r, h); ctx.quadraticCurveTo(0, h, 0, h - r);
  ctx.lineTo(0, r); ctx.quadraticCurveTo(0, 0, r, 0);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = fontColor;
  ctx.font = `bold ${fs}px Arial, sans-serif`;
  ctx.textAlign = align;
  ctx.textBaseline = 'middle';
  const x = align === 'left' ? pad : w / 2;
  lines.forEach((ln, i) => {
    ctx.fillText(ln, x, pad / 2 + lineH * i + lineH / 2);
  });
  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({ map: texture, depthWrite: false });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(w / 10, h / 10, 1);
  return sprite;
}

const graph = ForceGraph3D()(graphEl)
  .width(graphEl.clientWidth || 800)
  .height(graphEl.clientHeight || 600)
  .backgroundColor('#0f0f1a')
  .graphData({ nodes: NODES_DATA, links: LINKS_DATA })
  .nodeThreeObject(node => makeSprite(node.label, node.color, node.fontColor, 13, 140, 'left'))
  .nodeLabel('')
  .linkLabel('')
  .linkThreeObjectExtend(true)
  .linkThreeObject(link => makeSprite(link.label, '#1e2d4a', '#7090c0', 9))
  .linkPositionUpdate((sprite, { start, end }) => {
    sprite.position.set(
      start.x + (end.x - start.x) / 2,
      start.y + (end.y - start.y) / 2,
      start.z + (end.z - start.z) / 2,
    );
  })
  .linkColor(() => '#ffffff')
  .linkDirectionalArrowLength(4)
  .linkDirectionalArrowRelPos(1)
  .linkDirectionalArrowColor(() => '#ffffff')
  .linkDirectionalParticles(1)
  .linkDirectionalParticleSpeed(0.005)
  .linkDirectionalParticleColor(() => '#a0c4ff')
  .onNodeClick(node => renderPanel(node.id))
  .onNodeHover(node => { graphEl.style.cursor = node ? 'pointer' : 'default'; });

new ResizeObserver(() => {
  graph.width(graphEl.clientWidth).height(graphEl.clientHeight);
}).observe(graphEl);

function fitAll() { graph.zoomToFit(600, 40); }
function resetView() {
  graph.cameraPosition({ x: 0, y: 0, z: 600 }, { x: 0, y: 0, z: 0 }, 800);
}
</script>
</body>
</html>
"""


def _safe_props(props: dict) -> dict:
    return {k: v for k, v in props.items() if not (isinstance(v, list) and len(v) > 128)}


def _node_display(labels: list[str], props: dict) -> str:
    node_type = props.get("type", "")
    if node_type == "NarrativeText" or ("Chunk" in labels and node_type not in ("Image", "Table")):
        text = props.get("text", "")
        short = text[:55] + "…" if len(text) > 55 else text
        return f"Chunk: {short}"
    if node_type == "Image":
        return f"Image: {props.get('id', '')[:50]}"
    if node_type == "Table":
        return f"Table: {props.get('id', '')[:50]}"
    if "Document" in labels:
        return f"Doc: {props.get('name', '')[:55]}"
    if "Entity" in labels:
        return props.get("text") or props.get("name") or props.get("id", "Entity")
    label = labels[0] if labels else "Node"
    return f"{label}: {(props.get('id') or props.get('name') or '')[:40]}"


def _node_color(labels: list[str], props: dict) -> dict:
    node_type = props.get("type", "")
    if node_type == "Image" or "Image" in labels:
        return _LABEL_COLORS["Image"]
    if node_type == "Table" or "Table" in labels:
        return _LABEL_COLORS["Table"]
    for label in labels:
        if label in _LABEL_COLORS:
            return _LABEL_COLORS[label]
    if "Entity" in labels or any(l not in ("Chunk", "Document") for l in labels):
        return _ENTITY_COLOR
    return _DEFAULT_COLOR


def generate_interactive_graph_html(
    nodes_data: list[dict],
    edges_data: list[dict],
) -> str:
    vis_nodes = []
    content_map = {}
    seen_ids: set[str] = set()

    for n in nodes_data:
        node_id = n["id"]
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)

        labels: list[str] = n.get("labels", [])
        props: dict = _safe_props(n.get("props", {}))
        color = _node_color(labels, props)
        display = _node_display(labels, props)

        vis_nodes.append({
            "id": node_id,
            "label": display,
            "color": color["background"],
            "fontColor": color["font"],
        })
        content_map[node_id] = {"labels": labels, "display": display, "props": props}

    seen_edges: set[tuple] = set()
    vis_edges = []
    for e in edges_data:
        key = (e["source"], e["target"], e["type"])
        if key in seen_edges:
            continue
        seen_edges.add(key)
        vis_edges.append({
            "source": e["source"],
            "target": e["target"],
            "label": e["type"],
        })

    return (
        _HTML_TEMPLATE
        .replace("__NODES_JSON__", json.dumps(vis_nodes, default=str))
        .replace("__EDGES_JSON__", json.dumps(vis_edges, default=str))
        .replace("__CONTENT_JSON__", json.dumps(content_map, default=str))
    )
