"""Self-contained HTML viewer for the integrated 3D assembly projection.

The viewer embeds the GLB payload and the vendored three.js modules as
``data:`` URLs resolved through an import map, so the generated HTML has no
network dependency. It is an L3 projection for human review only.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from importlib import resources
from pathlib import Path

THREE_ASSET_PACKAGE = "acd.adapters.cad.viewer_assets.three"

# Relative specifiers inside the vendored modules are rewritten to bare
# specifiers so the import map can resolve them from data: URLs.
_VENDORED_MODULES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("three", "three.module.js", (("'./three.core.js'", "'three-core'"),)),
    ("three-core", "three.core.js", ()),
    ("three-orbit-controls", "OrbitControls.js", ()),
    (
        "three-gltf-loader",
        "GLTFLoader.js",
        (
            ("'../utils/BufferGeometryUtils.js'", "'three-buffer-geometry-utils'"),
            ("'../utils/SkeletonUtils.js'", "'three-skeleton-utils'"),
        ),
    ),
    ("three-buffer-geometry-utils", "BufferGeometryUtils.js", ()),
    ("three-skeleton-utils", "SkeletonUtils.js", ()),
)


class AssemblyViewerAssetError(RuntimeError):
    """Raised when a vendored viewer asset is missing or unexpectedly shaped."""


def three_version() -> str:
    return _read_asset("VERSION").strip()


def three_license_text() -> str:
    return _read_asset("LICENSE")


def _read_asset(name: str) -> str:
    try:
        return resources.files(THREE_ASSET_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise AssemblyViewerAssetError(f"vendored viewer asset missing: {name}") from exc


def _module_data_url(source: str) -> str:
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return f"data:text/javascript;base64,{encoded}"


def _import_map() -> dict[str, str]:
    imports: dict[str, str] = {}
    for specifier, file_name, rewrites in _VENDORED_MODULES:
        source = _read_asset(file_name)
        for old, new in rewrites:
            if old not in source:
                raise AssemblyViewerAssetError(
                    f"vendored module {file_name} lacks expected import {old}"
                )
            source = source.replace(old, new)
        imports[specifier] = _module_data_url(source)
    return imports


def render_assembly_viewer_html(
    *,
    glb_bytes: bytes,
    title: str,
    summary: Mapping[str, object],
) -> str:
    """Render the standalone viewer HTML embedding ``glb_bytes``.

    ``summary`` is serialized verbatim into the page and shown in the side
    panel; it must be JSON-serializable and contain only projection metadata.
    """

    import_map = json.dumps({"imports": _import_map()})
    glb_b64 = base64.b64encode(glb_bytes).decode("ascii")
    summary_json = json.dumps(summary, sort_keys=True, ensure_ascii=False)
    # Prevent "</script>" injection from any embedded string.
    summary_json = summary_json.replace("</", "<\\/")
    return _TEMPLATE.replace("__TITLE__", _escape(title)).replace(
        "__IMPORT_MAP__", import_map
    ).replace("__GLB_B64__", glb_b64).replace("__SUMMARY_JSON__", summary_json).replace(
        "__THREE_VERSION__", _escape(three_version())
    )


def write_assembly_viewer_html(
    *,
    glb_bytes: bytes,
    title: str,
    summary: Mapping[str, object],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_assembly_viewer_html(glb_bytes=glb_bytes, title=title, summary=summary),
        encoding="utf-8",
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  html, body { margin: 0; height: 100%; background: #1e1f24; color: #e6e6e6;
    font: 13px/1.4 system-ui, sans-serif; }
  #viewport { position: absolute; inset: 0 320px 0 0; }
  #panel { position: absolute; top: 0; right: 0; bottom: 0; width: 320px; overflow: auto;
    background: #26272e; border-left: 1px solid #3a3b44; padding: 12px 14px; box-sizing: border-box; }
  h1 { font-size: 15px; margin: 0 0 8px; }
  h2 { font-size: 12px; margin: 14px 0 6px; color: #9aa0b4; text-transform: uppercase; letter-spacing: .04em; }
  label { display: block; margin: 4px 0; cursor: pointer; }
  input[type=range] { width: 100%; }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px; margin-left: 4px; }
  .approx { background: #7a5a00; color: #fff; }
  .step { background: #1f5f3a; color: #fff; }
  .graph { background: #2f4f7f; color: #fff; }
  .computed { background: #8a1f1f; color: #fff; }
  .warn { background: #5a2a00; border: 1px solid #b86b1f; padding: 6px 8px; border-radius: 4px; margin: 8px 0; }
  .ok { background: #163b25; border: 1px solid #2c7a4b; padding: 6px 8px; border-radius: 4px; margin: 8px 0; }
  ul { margin: 4px 0; padding-left: 18px; }
  li { margin: 2px 0; word-break: break-all; }
  .muted { color: #9aa0b4; }
  #status { position: absolute; left: 12px; bottom: 10px; color: #9aa0b4; }
  code { font-size: 11px; }
</style>
<script type="importmap">__IMPORT_MAP__</script>
</head>
<body>
<div id="viewport"></div>
<div id="status">loading…</div>
<div id="panel">
  <h1>__TITLE__</h1>
  <div id="provenance" class="muted"></div>
  <div id="approx-note"></div>
  <div id="interference-note"></div>
  <h2>Layers</h2>
  <label><input type="checkbox" id="layer-board" checked> Board</label>
  <label><input type="checkbox" id="layer-component" checked> Components</label>
  <label><input type="checkbox" id="layer-enclosure" checked> Enclosure</label>
  <label><input type="checkbox" id="layer-interference" checked> Interference bodies</label>
  <label><input type="checkbox" id="enclosure-transparent" checked> Translucent enclosure</label>
  <h2>Section</h2>
  <label>Axis
    <select id="section-axis">
      <option value="none">off</option>
      <option value="x">X (side)</option>
      <option value="y">Y (front)</option>
      <option value="z">Z (height)</option>
    </select>
  </label>
  <input type="range" id="section-pos" min="0" max="1000" value="500" disabled>
  <div id="section-readout" class="muted"></div>
  <h2>Nodes</h2>
  <ul id="nodes"></ul>
  <h2>Tessellation</h2>
  <div id="tessellation" class="muted"></div>
  <h2>About</h2>
  <div class="muted">L3 projection: does not affect gates or Evidence. Rendered with
    three.js r__THREE_VERSION__ (MIT, vendored; no external network access). Units: mm.</div>
</div>
<script id="assembly-glb" type="application/octet-stream">__GLB_B64__</script>
<script id="assembly-summary" type="application/json">__SUMMARY_JSON__</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three-orbit-controls';
import { GLTFLoader } from 'three-gltf-loader';

const summary = JSON.parse(document.getElementById('assembly-summary').textContent);
const status = document.getElementById('status');
const viewport = document.getElementById('viewport');

function decodeGlb(b64) {
  const bin = atob(b64.trim());
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.localClippingEnabled = true;
viewport.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1e1f24);
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 10000);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 1.6));
const key = new THREE.DirectionalLight(0xffffff, 1.4);
key.position.set(1, 2, 1.5);
scene.add(key);

function resize() {
  const w = viewport.clientWidth, h = viewport.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

const layers = { board: [], component: [], enclosure: [], interference: [] };
const clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);
const bounds = new THREE.Box3();
let root = null;

const loader = new GLTFLoader();
loader.parse(decodeGlb(document.getElementById('assembly-glb').textContent), '', (gltf) => {
  root = gltf.scene;
  // GLB is in metres (Y-up); display in millimetres.
  root.scale.setScalar(1000);
  root.updateMatrixWorld(true);
  root.traverse((obj) => {
    if (!obj.isMesh) return;
    const layer = obj.parent?.userData?.layer ?? obj.userData?.layer ?? 'component';
    const mat = obj.material.clone();
    mat.side = THREE.DoubleSide;
    mat.clippingPlanes = [clipPlane];
    mat.clipShadows = true;
    if (layer === 'interference') {
      mat.emissive = new THREE.Color(0xff2020);
      mat.emissiveIntensity = 0.6;
      mat.depthTest = false;
      obj.renderOrder = 10;
    }
    obj.material = mat;
    obj.userData.layer = layer;
    (layers[layer] ?? layers.component).push(obj);
  });
  scene.add(root);
  bounds.setFromObject(root);
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3()).length();
  camera.position.copy(center).add(new THREE.Vector3(size * 0.9, size * 0.7, size * 0.9));
  camera.near = size / 1000;
  camera.far = size * 20;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
  scene.add(new THREE.GridHelper(Math.ceil(size / 10) * 10, Math.ceil(size / 10), 0x555566, 0x33343c)
    .translateY(bounds.min.y - 0.5));
  applyLayers();
  applyEnclosureAlpha();
  applySection();
  status.textContent = `loaded ${gltf.scene.children.length} nodes`;
  fillPanel(gltf);
  resize();
}, (err) => {
  status.textContent = 'GLB parse failed: ' + (err?.message ?? err);
  status.style.color = '#ff6b6b';
});

function applyLayers() {
  for (const [layer, meshes] of Object.entries(layers)) {
    const on = document.getElementById('layer-' + layer).checked;
    meshes.forEach((m) => { m.visible = on; });
  }
}
function applyEnclosureAlpha() {
  const translucent = document.getElementById('enclosure-transparent').checked;
  layers.enclosure.forEach((m) => {
    m.material.transparent = translucent;
    m.material.opacity = translucent ? 0.35 : 1.0;
    m.material.depthWrite = !translucent;
    m.material.needsUpdate = true;
  });
}
const axisVectors = { x: new THREE.Vector3(-1, 0, 0), y: new THREE.Vector3(0, 0, 1), z: new THREE.Vector3(0, -1, 0) };
function applySection() {
  const axis = document.getElementById('section-axis').value;
  const slider = document.getElementById('section-pos');
  const readout = document.getElementById('section-readout');
  slider.disabled = axis === 'none';
  if (axis === 'none') {
    clipPlane.constant = 1e9;
    clipPlane.normal.set(0, -1, 0);
    readout.textContent = '';
    return;
  }
  // Slider maps to CAD axes: X→scene X, Y (CAD depth)→scene −Z, Z (CAD height)→scene Y.
  const t = slider.value / 1000;
  const n = axisVectors[axis];
  let lo, hi;
  if (axis === 'x') { lo = bounds.min.x; hi = bounds.max.x; }
  else if (axis === 'y') { lo = -bounds.max.z; hi = -bounds.min.z; }
  else { lo = bounds.min.y; hi = bounds.max.y; }
  const pos = lo + (hi - lo) * t;
  clipPlane.normal.copy(n);
  // Keep the half-space below `pos` along the CAD axis.
  clipPlane.constant = pos;
  readout.textContent = `${axis.toUpperCase()} = ${pos.toFixed(2)} mm`;
}
for (const id of ['layer-board', 'layer-component', 'layer-enclosure', 'layer-interference']) {
  document.getElementById(id).addEventListener('change', applyLayers);
}
document.getElementById('enclosure-transparent').addEventListener('change', applyEnclosureAlpha);
document.getElementById('section-axis').addEventListener('change', applySection);
document.getElementById('section-pos').addEventListener('input', applySection);

function fillPanel(gltf) {
  const asset = gltf.parser.json.asset ?? {};
  const extras = asset.extras ?? {};
  document.getElementById('provenance').textContent =
    `graph ${extras.graph_id ?? summary.graph_id ?? '?'} @ ${extras.graph_revision ?? summary.target_revision ?? '?'}`;
  const nodes = gltf.parser.json.nodes ?? [];
  const list = document.getElementById('nodes');
  let approximated = 0, interference = 0;
  for (const node of nodes) {
    const ex = node.extras ?? {};
    const li = document.createElement('li');
    li.textContent = node.name ?? '(unnamed)';
    const badge = document.createElement('span');
    const src = ex.source ?? 'unknown';
    badge.className = 'badge ' + ({ approximated: 'approx', step: 'step', graph_outline: 'graph', computed: 'computed' }[src] ?? '');
    badge.textContent = src;
    li.appendChild(badge);
    if (ex.layer === 'interference' && ex.interference_volume_mm3 !== undefined) {
      const v = document.createElement('span');
      v.className = 'muted';
      v.textContent = ` ${Number(ex.interference_volume_mm3).toFixed(3)} mm³`;
      li.appendChild(v);
    }
    list.appendChild(li);
    if (src === 'approximated') approximated++;
    if (ex.layer === 'interference') interference++;
  }
  const approxNote = document.getElementById('approx-note');
  if (approximated > 0) {
    approxNote.className = 'warn';
    approxNote.textContent = `${approximated} component bod${approximated === 1 ? 'y is' : 'ies are'} approximated as boxes from component_bodies (no bundled KiCad 3D models).`;
  }
  const intNote = document.getElementById('interference-note');
  if (interference > 0) {
    intNote.className = 'warn';
    intNote.textContent = `${interference} interference bod${interference === 1 ? 'y' : 'ies'} highlighted in red (from the mechanical gate report).`;
  } else {
    intNote.className = 'ok';
    intNote.textContent = 'No interference bodies recorded.';
  }
  const tess = summary.tessellation ?? extras.tessellation ?? {};
  document.getElementById('tessellation').textContent =
    `linear deflection ${tess.linear_deflection_mm ?? '?'} mm, angular deflection ${tess.angular_deflection_deg ?? '?'}° ` +
    `(same tolerances as the 3MF/STL Mesher output).`;
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
resize();
animate();
</script>
</body>
</html>
"""
