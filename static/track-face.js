// Face mesh track (Agent 3): mesh off on a range, on-canvas transform with keyframes, expression sliders, reset
// (docs/TIMELINE-SPEC.md §5, §A3).
//
// Every edit is a commit to layer.mesh ({off, keys, expr}) through the shared edit layer (one undo stack with the
// other tracks). Nothing here calls the server except the edit-layer PUTs and two static GETs (the run's
// face-landmarks.json once per run, static/face-connections.json once): the edited mesh is drawn instantly on the
// overlay canvas with the formulas of static/meshedit.js (a 1:1 port of stages/meshedit.py). "Save edits" makes the
// `mesh_edit` face tool re-draw it locally into the new version. The "Mesh edit" view shows the base clip WITHOUT the
// baked mesh (depth composite, or the original in Fast mode) so only the live edited mesh is on screen; selecting the
// track switches to it, leaving the track switches back.
import { getJSON } from './api.js';
import { el, ariaFor, showError } from './ui.js';
import { registerTrack } from './timeline.js';
import { EXPR, RANGES, IDENTITY, normalize, transformAt, editFrame, editPoints, centroid, offSet, sortedKeys, exprRuns, mergeRanges, subtractRange, isIdentity } from './meshedit.js';

const VIEW = 'mesh-edit';
const STATUS = { tracked: '#3aa76d', filled: '#e0b341', missing: '#d9534f', off: '#9a9eab' };
const COLOURS = { tessellation: [50, 170, 205], lips: [255, 135, 100], left_eye: [130, 255, 150], right_eye: [130, 255, 150] };   // as mesh_worker.py
const DRAW = [['tessellation', 1], ['lips', 2], ['left_eye', 2], ['right_eye', 2]];
const SLIDERS = [['jaw', 'Jaw open'], ['smile', 'Mouth smile'], ['pucker', 'Mouth pucker'], ['blink_l', 'Blink left (their left)'], ['blink_r', 'Blink right (their right)'], ['brow', 'Brow up']];
const st = { jobId: null, ctx: null, panel: null, base: null, baseKey: null, conn: null, drag: null, draft: null, exprDraft: null, prevView: null, info: '' };

const plural = (n, w, many) => `${n} ${n === 1 ? w : many || w + 's'}`;
const round = (v, p) => Number(Number(v).toFixed(p));
const value = ctx => { const v = ctx && ctx.edits.layer.mesh; return v && typeof v === 'object' ? v : {}; };
const norm = ctx => normalize(value(ctx));
const frames = () => (st.base && Array.isArray(st.base.frames) ? st.base.frames : []);
const running = ctx => !!(ctx && ctx.state.job && ctx.state.job.state === 'running');
const editable = ctx => !!ctx && !running(ctx) && frames().length > 0;
const baseFile = ctx => {
  const chain = ctx && ctx.run && ctx.run.run && ctx.run.run.chain, tool = chain && chain.composite && chain.composite.tool;
  return tool === 'depth_cutout' && ctx.files.has('depth-composite-silent.mp4') ? 'depth-composite-silent.mp4' : 'original.mp4';
};
const aspect = ctx => { const v = ctx && ctx.editor.video; return v && v.videoWidth && v.videoHeight ? v.videoWidth / v.videoHeight : (st.base && st.base.aspect) || 16 / 9; };
const target = ctx => { const r = ctx.editor.range; return r ? { from: r.from, to: r.to, text: `frames ${r.from}–${r.to}`, long: `frames ${r.from}–${r.to} (${r.to - r.from + 1})` } : { from: ctx.editor.frame, to: ctx.editor.frame, text: `frame ${ctx.editor.frame}`, long: `frame ${ctx.editor.frame}` }; };

// ---------------------------------------------------------------- data (two static GETs, cached)
async function loadBase(ctx) {
  const key = ctx.jobId + '|' + (ctx.files.has('face-landmarks.json') ? 'lm' : '');
  if (st.baseKey === key) return;
  st.baseKey = key; st.base = null;
  if (!ctx.files.has('face-landmarks.json')) { render(); return; }
  try {
    const [lm, conn] = await Promise.all([getJSON('/runs/' + ctx.jobId + '/face-landmarks.json'), st.conn ? Promise.resolve(st.conn) : getJSON('/static/face-connections.json')]);
    if (st.baseKey !== key) return;
    st.base = lm && Array.isArray(lm.frames) ? lm : { frames: [] }; st.conn = conn; render(); ctx.editor.redraw();
  } catch (e) { if (st.baseKey === key) { st.base = { frames: [], failed: true }; showError(e, { key: 'face-track' }); render(); } }
}

// ---------------------------------------------------------------- the edited face of a frame (drafts included)
function layerWithDrafts(ctx) {
  const n = norm(ctx);
  if (st.draft) n.keys.set(st.draft.frame, st.draft.key);
  if (st.exprDraft) for (const f of st.exprDraft.frames) { const e = { ...(n.expr.get(f) || {}) }; if (st.exprDraft.value) e[st.exprDraft.name] = st.exprDraft.value; else delete e[st.exprDraft.name]; if (Object.keys(e).length) n.expr.set(f, e); else n.expr.delete(f); }
  return n;
}
function faceAt(ctx, frame, n = layerWithDrafts(ctx)) {
  const fr = frames()[frame]; if (!fr) return null;
  const out = editFrame(fr, frame, n, aspect(ctx));
  return out.faces && out.faces.length ? { points: out.faces[0].map(p => [p.x, p.y]), status: out.status, edited: out.edited, base: fr.faces[0].map(p => [p.x, p.y]) } : { points: null, status: out.status };
}

// ---------------------------------------------------------------- edits (one commit per gesture / click)
function commitMesh(ctx, label, fn) {
  return ctx.edits.commit(label, 'mesh', d => {
    const v = d && typeof d === 'object' ? d : {};
    v.off = Array.isArray(v.off) ? v.off : []; v.keys = v.keys && typeof v.keys === 'object' ? v.keys : {}; v.expr = v.expr && typeof v.expr === 'object' ? v.expr : {};
    fn(v); return v;
  });
}
function meshOff(ctx, on) {
  const t = target(ctx);
  commitMesh(ctx, `Mesh ${on ? 'on' : 'off'} on ${t.text}`, v => { v.off = on ? subtractRange(normalize(v).off, t.from, t.to) : mergeRanges([...normalize(v).off, [t.from, t.to]]); });
}
function setKey(ctx, frame, key, label) {
  const k = { dx: round(key.dx, 5), dy: round(key.dy, 5), scale: round(key.scale, 4), rot: round(key.rot, 2) };
  commitMesh(ctx, label, v => { v.keys[String(frame)] = k; });
}
function setExpr(ctx, name, val, t) {
  const label = SLIDERS.find(s => s[0] === name)[1];
  commitMesh(ctx, `${label} ${val} on ${t.text}`, v => {
    for (let f = t.from; f <= t.to; f++) { const e = { ...(v.expr[String(f)] || {}) }; if (val) e[name] = val; else delete e[name]; if (Object.keys(e).length) v.expr[String(f)] = e; else delete v.expr[String(f)]; }
  });
}
function reset(ctx, t, what) {
  commitMesh(ctx, `Reset the face edits on ${what || t.text}`, v => {
    for (let f = t.from; f <= t.to; f++) { delete v.keys[String(f)]; delete v.expr[String(f)]; }
    v.off = subtractRange(normalize(v).off, t.from, t.to);
  });
}

// ---------------------------------------------------------------- the Mesh edit view (base clip without the baked mesh)
function syncView(ctx) {
  const file = baseFile(ctx);
  ctx.editor.addView({ id: VIEW, label: 'Mesh edit', order: 15, layers: [{ file }], download: file, downloadLabel: file === 'original.mp4' ? 'Download the original (no mesh)' : 'Download the depth composite (no mesh)', available: c => c.files.has('face-landmarks.json') && c.files.has(baseFile(c)),
    caption: (file === 'original.mp4' ? 'Original frames' : 'Depth composite') + ' without the baked mesh · the edited mesh is drawn live on top' });
}
function onSelect(id) {
  const ctx = st.ctx; if (!ctx || !ctx.files.has('face-landmarks.json')) return;
  const ed = ctx.editor;
  if (id === 'face' && ed.view !== VIEW) { st.prevView = ed.view; ed.setView(VIEW, { chosen: true }); }
  else if (id !== 'face' && ed.view === VIEW && st.prevView) { const back = st.prevView; st.prevView = null; ed.setView(back, { chosen: true }); }
}

// ---------------------------------------------------------------- panel
const button = (text, title, onclick, cls = 'small secondary', disabled = false) => el('button', { type: 'button', class: cls, text, title, 'aria-label': ariaFor(text, title), onclick, disabled });
function render() {
  const ctx = st.ctx, box = st.panel; if (!ctx || !box) return;
  const ed = ctx.editor, f = ed.frame, can = editable(ctx), n = norm(ctx), t = target(ctx), off = offSet(n.off), ks = sortedKeys(n.keys);
  const face = can ? faceAt(ctx, f, n) : null, key = n.keys.get(f), cur = transformAt(n.keys, f) || { ...IDENTITY };
  const where = !can ? '' : off.has(f) ? 'Mesh off on this frame (the base clip only).' + (key ? ` ◆ Transform key on frame ${f} (it still blends into the frames around it).` : '') : !face || !face.points ? `No face on frame ${f} (${(frames()[f] || {}).status || 'missing'}), so there are no handles here. ` + (key ? `◆ Transform key on frame ${f}: it blends into the tracked frames around it.` : 'You can still place a key here with the fields or "Set key here"; it blends into the tracked frames around it.') :
    key ? `◆ Transform key on frame ${f}.` : transformAt(n.keys, f) ? `Blended between keys ${ks.filter(k => k < f).pop()} and ${ks.find(k => k > f)} (ease-in-out).` : 'No correction on this frame.';
  const prevKey = [...ks].reverse().find(k => k < f), nextKey = ks.find(k => k > f);
  const help = el('p', { class: 'hint', text: !ctx.files.has('face-landmarks.json') ? 'This run has no face landmarks, so there is no mesh to edit.' : st.base && st.base.failed ? 'The face landmarks could not be loaded.' : !st.base ? 'Loading the face landmarks…' : running(ctx) ? 'The run is still preparing; mesh edits open when it finishes.' :
    'Drag inside the mesh to move it, the corner square to scale, the top circle to rotate: each drag sets a key on this frame, and keys blend with an ease-in-out across the frames between them. Everything is drawn locally and free; nothing changes until "Save edits".' });
  const targetRow = el('div', { class: 'mt-row' }, el('strong', { text: 'Applies to ' + t.long }), ed.range ? null : el('span', { class: 'hint', text: 'drag across the ruler to pick a range' }));
  const offRow = el('div', { class: 'mt-row' },
    button(ed.range ? 'Mesh off on range' : 'Mesh off on this frame', 'Those frames show the base clip only (no mesh drawn)', () => meshOff(ctx, false), 'small secondary', !can),
    button('Mesh on', 'Draw the mesh again on ' + t.text, () => meshOff(ctx, true), 'small secondary', !can || ![...Array(t.to - t.from + 1)].some((_, i) => off.has(t.from + i))),
    n.off.length ? el('span', { class: 'hint', text: 'off: ' + n.off.map(([a, b]) => (a === b ? a : a + '–' + b)).join(', ') }) : null);
  const field = (k, label, step, title) => {
    const i = el('input', { type: 'number', step: String(step), 'aria-label': label, title, class: 'ft-num', style: 'width:76px;padding:5px 6px', disabled: !can });   // any frame, faceless too: a key there blends into its tracked neighbours
    i.value = String(k === 'scale' ? round(cur.scale, 3) : k === 'rot' ? round(cur.rot, 1) : round(cur[k], 4));
    i.onchange = () => { const v = Number(i.value); if (!Number.isFinite(v)) return; setKey(ctx, f, { ...cur, [k]: v }, `Set ${label} on frame ${f}`); };
    return el('label', { class: 'wand-inline' }, label + ' ', i);
  };
  const tRow = el('div', { class: 'mt-row ft-transform' }, field('dx', 'dx', 0.005, 'Shift right, in frame widths'), field('dy', 'dy', 0.005, 'Shift down, in frame heights'), field('scale', 'scale', 0.01, 'Size factor'), field('rot', 'rot °', 0.5, 'Degrees, clockwise'),
    button('Set key here', key ? `Frame ${f} already has a key; change the fields to edit it` : `Place a transform key on frame ${f} with the values shown (the current blend, or no correction), so later changes start from it`, () => setKey(ctx, f, cur, `Set a transform key on frame ${f}`), 'small secondary', !can || !!key));
  const sliders = el('div', { class: 'ft-sliders' }, SLIDERS.map(([name, label]) => {
    const [lo, hi] = RANGES[name], e = n.expr.get(f) || {}, v = st.exprDraft && st.exprDraft.name === name ? st.exprDraft.value : e[name] || 0;
    const out = el('output', { class: 'mono', text: v.toFixed(2) });
    const r = el('input', { type: 'range', min: String(lo), max: String(hi), step: '0.05', 'aria-label': label + ' on ' + t.text, disabled: !can });
    r.value = String(v);
    r.oninput = () => { const val = round(r.value, 2), fr = []; for (let x = t.from; x <= t.to; x++) fr.push(x); st.exprDraft = { name, value: val, frames: fr }; out.textContent = val.toFixed(2); ed.redraw(); };
    r.onchange = () => { const val = round(r.value, 2); st.exprDraft = null; setExpr(ctx, name, val, t); };   // commit on release
    return el('label', { class: 'ft-slider' }, el('span', { text: label }), r, out);
  }));
  const navRow = el('div', { class: 'mt-row' },
    button('◀ Prev key', 'Previous transform key ([ jumps between all face marks)', () => ed.seek(prevKey), 'small secondary', prevKey == null),
    button('Next key ▶', 'Next transform key', () => ed.seek(nextKey), 'small secondary', nextKey == null),
    button('Reset frame', `Remove every face edit on frame ${f}`, () => reset(ctx, { from: f, to: f, text: `frame ${f}` }), 'small secondary', !can || !(n.keys.has(f) || n.expr.has(f) || off.has(f))),
    button('Reset range', ed.range ? `Remove every face edit on frames ${t.from}–${t.to}` : 'Select a range first', () => reset(ctx, t), 'small secondary', !can || !ed.range));
  const viewRow = el('div', { class: 'mt-row' }, el('span', { class: 'hint', text: 'View' }),
    button('Mesh edit', 'Base clip without the baked mesh; your edited mesh drawn live', () => ed.setView(VIEW, { chosen: true }), 'small ' + (ed.view === VIEW ? '' : 'secondary'), !ctx.files.has('face-landmarks.json')),
    button('Prepared input', 'The clip as prepared (mesh baked in, before your edits)', () => ed.setView('seedance-input.mp4', { chosen: true }), 'small ' + (ed.view === 'seedance-input.mp4' ? '' : 'secondary'), !ctx.files.has('seedance-input.mp4')));
  const counts = [n.off.length ? plural(n.off.length, 'off range') : '', n.keys.size ? plural(n.keys.size, 'key') : '', n.expr.size ? `expressions on ${plural(n.expr.size, 'frame')}` : ''].filter(Boolean).join(' · ');
  const status = el('p', { class: 'hint ft-where', 'aria-live': 'polite', text: [where, counts ? 'This session: ' + counts + '.' : ''].filter(Boolean).join(' ') });
  const legend = el('div', { class: 'legend' }, ...Object.entries(STATUS).map(([k, c]) => el('span', {}, el('i', { style: `background:${c}` }), k)), el('span', { text: '◆ key' }), el('span', { text: '● expression' }), el('span', { text: '▨ mesh off' }));
  const kids = [help, can ? targetRow : null, can ? offRow : null, can ? tRow : null, can ? sliders : null, can ? navRow : null, viewRow, can ? status : null, legend];
  const focused = box.contains(document.activeElement) && document.activeElement.type === 'range';
  if (focused && st.exprDraft) return;   // keep the slider being dragged alive
  box.replaceChildren(...kids.filter(Boolean));   // replaceChildren would print a null as text
}

// ---------------------------------------------------------------- overlay: the edited mesh + transform handles
function bbox(points) { let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (const [x, y] of points.slice(0, 468)) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; } return { x0, y0, x1, y1 }; }
function handles(points, W, H, dpr) {   // in device px of the overlay
  const b = bbox(points), r = 7 * dpr;
  const keep = (v, max) => Math.max(r + 2 * dpr, Math.min(max - r - 2 * dpr, v));   // handles stay on the picture (a face near the edge, a 380 px screen)
  return { x0: b.x0 * W, y0: b.y0 * H, x1: b.x1 * W, y1: b.y1 * H, corner: [keep(b.x1 * W, W), keep(b.y1 * H, H)], rotate: [keep((b.x0 + b.x1) / 2 * W, W), keep(b.y0 * H - 26 * dpr, H)], r };
}
function drawMesh(c, box, points, status) {
  const W = box.width, H = box.height, conn = st.conn, v = st.ctx && st.ctx.editor.video, scale = Math.max(1, v && v.videoWidth ? W / v.videoWidth : 1);
  for (const [name, width] of DRAW) {
    const col = COLOURS[name].map(x => (status === 'tracked' ? x : Math.trunc(x * 0.45)));
    c.strokeStyle = `rgb(${col.join(',')})`; c.lineWidth = width * scale; c.beginPath();
    for (const [a, b] of conn[name] || []) { const p = points[a], q = points[b]; if (!p || !q) continue; c.moveTo(p[0] * W, p[1] * H); c.lineTo(q[0] * W, q[1] * H); }
    c.stroke();
  }
}
function drawCanvas(c, box, frame) {
  const ctx = st.ctx; if (!ctx || !st.conn || !frames().length) return;
  const ed = ctx.editor; if (ed.view !== VIEW) return;   // other views carry the baked mesh already
  const face = faceAt(ctx, frame); if (!face || !face.points) return;
  drawMesh(c, box, face.points, face.status);
  if (ed.selected !== 'face' || !editable(ctx)) return;
  const h = handles(face.points, box.width, box.height, box.dpr);
  c.setLineDash([6 * box.dpr, 4 * box.dpr]); c.lineWidth = 1.5 * box.dpr; c.strokeStyle = 'rgba(255,255,255,.85)'; c.strokeRect(h.x0, h.y0, h.x1 - h.x0, h.y1 - h.y0); c.setLineDash([]);
  c.beginPath(); c.moveTo((h.x0 + h.x1) / 2, h.y0); c.lineTo(h.rotate[0], h.rotate[1]); c.stroke();
  c.fillStyle = '#1f18c0'; c.strokeStyle = '#fff'; c.lineWidth = 2 * box.dpr;
  c.fillRect(h.corner[0] - h.r, h.corner[1] - h.r, 2 * h.r, 2 * h.r); c.strokeRect(h.corner[0] - h.r, h.corner[1] - h.r, 2 * h.r, 2 * h.r);
  c.beginPath(); c.arc(h.rotate[0], h.rotate[1], h.r, 0, Math.PI * 2); c.fill(); c.stroke();
  if (st.draft && st.draft.frame === frame) { const k = st.draft.key; c.fillStyle = 'rgba(0,0,0,.6)'; c.font = `${12 * box.dpr}px sans-serif`; const text = `dx ${k.dx.toFixed(3)} dy ${k.dy.toFixed(3)} × ${k.scale.toFixed(2)} ${k.rot.toFixed(1)}°`; c.fillRect(h.x0, h.y1 + 6 * box.dpr, c.measureText(text).width + 10 * box.dpr, 18 * box.dpr); c.fillStyle = '#fff'; c.fillText(text, h.x0 + 5 * box.dpr, h.y1 + 19 * box.dpr); }
}

// ---------------------------------------------------------------- pointer: move / scale / rotate = one commit per drag
const pointer = {
  down(e, pt) {
    const ctx = st.ctx; if (!editable(ctx) || ctx.editor.view !== VIEW) return;
    const face = faceAt(ctx, pt.frame); if (!face || !face.points) return;
    const pb = ctx.editor.pictureBox(), dpr = 1, h = handles(face.points, pb.width, pb.height, dpr), x = pt.x * pb.width, y = pt.y * pb.height, grab = Math.max(h.r + 6, 14);
    const mode = Math.hypot(x - h.rotate[0], y - h.rotate[1]) <= grab ? 'rotate' : Math.hypot(x - h.corner[0], y - h.corner[1]) <= grab ? 'scale' : x >= h.x0 && x <= h.x1 && y >= h.y0 && y <= h.y1 ? 'move' : null;
    if (!mode) return;
    const n = norm(ctx), T0 = transformAt(n.keys, pt.frame) || { ...IDENTITY }, c0 = centroid(face.base), A = aspect(ctx);
    st.drag = { mode, frame: pt.frame, start: pt, T0, C: [(c0[0] + T0.dx) * A, c0[1] + T0.dy], A };
    st.draft = { frame: pt.frame, key: { ...T0 } }; ctx.editor.redraw();
  },
  move(e, pt) {
    const d = st.drag; if (!d) return;
    const A = d.A, k = { ...d.T0 }, p = [pt.x * A, pt.y], s = [d.start.x * A, d.start.y];
    if (d.mode === 'move') { k.dx = d.T0.dx + (pt.x - d.start.x); k.dy = d.T0.dy + (pt.y - d.start.y); }
    else if (d.mode === 'scale') { const r0 = Math.hypot(s[0] - d.C[0], s[1] - d.C[1]) || 1e-6; k.scale = Math.max(0.2, Math.min(5, d.T0.scale * Math.hypot(p[0] - d.C[0], p[1] - d.C[1]) / r0)); }
    else { const a0 = Math.atan2(s[1] - d.C[1], s[0] - d.C[0]), a1 = Math.atan2(p[1] - d.C[1], p[0] - d.C[0]); let rot = d.T0.rot + (a1 - a0) * 180 / Math.PI; while (rot > 180) rot -= 360; while (rot < -180) rot += 360; k.rot = rot; }
    st.draft = { frame: d.frame, key: k }; st.ctx.editor.redraw();
  },
  up() {
    const d = st.drag; if (!d) return;
    st.drag = null; const k = st.draft && st.draft.key;
    if (k && ['dx', 'dy', 'scale', 'rot'].some(n => Math.abs(k[n] - d.T0[n]) > 1e-6)) {
      const verb = { move: 'Move', scale: 'Scale', rotate: 'Rotate' }[d.mode];
      setKey(st.ctx, d.frame, k, `${verb} the mesh on frame ${d.frame}`);
    }
    st.draft = null; st.ctx.editor.redraw(); render();
  },
};

// ---------------------------------------------------------------- lane
function statuses(ctx) {
  if (frames().length) return frames().map(fr => fr.status || 'missing');
  const t = ctx && ctx.state.tracking; if (!t || !t.frames) return null;
  const s = new Array(t.frames).fill('tracked');
  for (const f of t.filled_frames || []) if (f < t.frames) s[f] = 'filled';
  for (const f of t.missing_frames || []) if (f < t.frames) s[f] = 'missing';
  return s;
}
function drawLane(lane, v) {
  const ctx = st.ctx, c = v.ctx2d, s = statuses(ctx);
  if (!s) { c.fillStyle = '#9a9eab'; c.font = '11px sans-serif'; c.textBaseline = 'middle'; c.fillText('No face tracking in this run', 8, v.height / 2); return; }
  const first = Math.max(0, v.frameAt(0)), last = Math.min(s.length - 1, v.frameAt(v.width) + 1), w = Math.max(1, v.pxPerFrame - (v.pxPerFrame > 4 ? 1 : 0));
  for (let f = first; f <= last; f++) { c.fillStyle = STATUS[s[f]] || '#ccc'; c.globalAlpha = s[f] === 'tracked' ? 0.7 : 0.9; c.fillRect(v.x(f), 12, w, v.height - 22); }
  c.globalAlpha = 1;
  const n = norm(ctx), ks = sortedKeys(n.keys);
  if (ks.length > 1) { c.fillStyle = 'rgba(31,24,192,.55)'; c.fillRect(v.x(ks[0]) + v.pxPerFrame / 2, v.height - 9, v.x(ks[ks.length - 1]) - v.x(ks[0]), 3); }   // the blended span
  c.save(); c.beginPath(); for (const [a, b] of n.off) c.rect(v.x(a), 10, v.x(b + 1) - v.x(a), v.height - 18); c.clip();   // mesh off: hatched
  c.fillStyle = 'rgba(40,40,48,.45)'; c.fillRect(0, 0, v.width, v.height); c.strokeStyle = 'rgba(255,255,255,.8)'; c.lineWidth = 1.2; c.beginPath();
  for (let x = -v.height; x < v.width + v.height; x += 6) { c.moveTo(x, v.height); c.lineTo(x + v.height, 0); } c.stroke(); c.restore();
  c.fillStyle = '#7b3fbf';
  for (const f of n.expr.keys()) { const x = v.x(f) + v.pxPerFrame / 2; if (x < -4 || x > v.width + 4) continue; c.beginPath(); c.arc(x, v.height - 5, 2.6, 0, Math.PI * 2); c.fill(); }
  c.fillStyle = '#1f18c0'; c.strokeStyle = '#fff'; c.lineWidth = 1;
  for (const f of ks) { const x = v.x(f) + v.pxPerFrame / 2; if (x < -6 || x > v.width + 6) continue; c.beginPath(); c.moveTo(x, 2); c.lineTo(x + 5, 7); c.lineTo(x, 12); c.lineTo(x - 5, 7); c.closePath(); c.fill(); c.stroke(); }
}

// ---------------------------------------------------------------- the track
function reset0(ctx) { Object.assign(st, { jobId: ctx.jobId, base: null, baseKey: null, drag: null, draft: null, exprDraft: null, prevView: null, info: '' }); }
let offSelect = null;
registerTrack({
  id: 'face', label: 'Face', order: 20, height: 44, markerColor: '#1f18c0',
  available: ctx => ctx.files.has('face-tracking.json') || ctx.files.has('face-landmarks.json'),
  mount(row, panel, ctx) {
    if (st.jobId !== ctx.jobId) reset0(ctx);
    st.ctx = ctx; st.panel = el('div', { class: 'mask-track face-track' }); panel.append(st.panel);
    if (offSelect) offSelect();
    const offs = [ctx.editor.on('select', id => onSelect(id)), ctx.editor.on('range', () => render())];
    offSelect = () => offs.forEach(f => f());
    syncView(ctx); loadBase(ctx); render();
    window.puppeteer = Object.assign(window.puppeteer || {}, { faceTrack: { st, faceAt: frame => st.ctx && faceAt(st.ctx, frame), editPoints, isIdentity } });   // for the console and browser checks
  },
  update(ctx) {
    if (st.jobId !== ctx.jobId) reset0(ctx);
    st.ctx = ctx; syncView(ctx); loadBase(ctx); render();
  },
  onFrame(frame, ctx) { st.ctx = ctx; if (ctx.editor.playing) return; render(); },   // no DOM work per frame during playback
  markers(ctx) {
    const n = norm(ctx); return [...new Set([...n.keys.keys(), ...n.off.map(r => r[0]), ...exprRuns(n.expr).map(r => r[0])])].sort((a, b) => a - b);
  },
  draw(lane, v) { drawLane(lane, v); },
  canvas(c, box, frame) { drawCanvas(c, box, frame); },
  pointer,
});

