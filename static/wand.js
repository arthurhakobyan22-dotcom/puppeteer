// Mask wand: fix the mask from the review panel. Pause on a frame, click + on a missed region or Alt-click (or the
// − toggle) on spill, see what the click selects, then apply to the whole clip. Applying is a branch at the mask
// stage (POST /jobs/{id}/mask/apply): depth is linked from the parent, nothing is re-billed, the parent stays as it
// is and the child opens with its review pending. The free tools (local propagation, brush) need no confirmation;
// the hosted ones show their estimate on the button and send confirm_cost=true from that click only.
import { api, send, plain } from './api.js';
import { $, el, usd, showError, notice } from './ui.js';
import { state, navigate } from './state.js';
import { registerReviewTool } from './review.js';

const FALLBACK_TOOLS = [
  { name: 'local_propagate', label: 'Local propagation (free, rougher edges)', paid: false },
  { name: 'sam3_points_fal', label: 'SAM 3 on fal (point prompts)', paid: true },
  { name: 'sam2_points_replicate', label: 'SAM 2 on Replicate (point prompts)', paid: true },
  { name: 'brush', label: 'Brush (free)', paid: false },
];
const WAND_NAMES = FALLBACK_TOOLS.map(t => t.name);

let wand = null;   // state for the job currently shown; replaced when the job changes

function toolList() {
  const stage = state.registry && state.registry.stages && state.registry.stages.find(s => s.name === 'mask');
  const known = stage ? stage.tools.filter(t => WAND_NAMES.includes(t.name)) : [];
  return WAND_NAMES.map(name => known.find(t => t.name === name) || FALLBACK_TOOLS.find(t => t.name === name));
}

function fresh(jobId) {
  return { jobId, open: false, frame: 0, frames: 0, fps: 24, width: 0, height: 0, mode: 'include', tool: 'local_propagate', edits: [], strokes: [],
    brush: { radius: 0.03, frames: 5, mode: 'paint' }, stroke: null, previewUrl: '', frameUrl: '', estimate: null, busy: false, info: '', node: null, overlay: null, video: null, viewer: null, resize: null };
}

/** The rendered video box inside the viewer (letterboxed videos are centred by the browser). */
function videoBox(video, w) {
  const cw = video.clientWidth, ch = video.clientHeight, vw = video.videoWidth || w.width || 16, vh = video.videoHeight || w.height || 9;
  const s = Math.min(cw / vw, ch / vh); const width = vw * s, height = vh * s;
  return { left: video.offsetLeft + (cw - width) / 2, top: video.offsetTop + (ch - height) / 2, width, height };
}

function positionOverlay(w) {
  if (!w.overlay || !w.video) return;
  const b = videoBox(w.video, w);
  Object.assign(w.overlay.style, { left: b.left + 'px', top: b.top + 'px', width: b.width + 'px', height: b.height + 'px' });
  const canvas = $('canvas', w.overlay); const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(b.width * dpr)); canvas.height = Math.max(1, Math.round(b.height * dpr));
  drawMarkers(w);
}

function drawMarkers(w) {
  const canvas = w.overlay && $('canvas', w.overlay); if (!canvas) return;
  const c = canvas.getContext('2d'); c.clearRect(0, 0, canvas.width, canvas.height);
  const W = canvas.width, H = canvas.height, r = Math.max(5, W * 0.012);
  for (const e of w.edits) {
    if (e.frame !== w.frame) continue;
    c.beginPath(); c.arc(e.x * W, e.y * H, r, 0, Math.PI * 2);
    c.fillStyle = e.label ? 'rgba(40,200,80,.85)' : 'rgba(230,60,50,.85)'; c.fill(); c.lineWidth = 2; c.strokeStyle = '#fff'; c.stroke();
    c.fillStyle = '#fff'; c.font = 'bold ' + Math.round(r * 1.4) + 'px sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText(e.label ? '+' : '−', e.x * W, e.y * H + 1);
  }
  const strokes = [...w.strokes.filter(s => s.frame_from <= w.frame && w.frame <= s.frame_to), ...(w.stroke ? [w.stroke] : [])];
  for (const s of strokes) {
    c.lineCap = 'round'; c.lineJoin = 'round'; c.lineWidth = Math.max(2, s.radius * 2 * H);
    c.strokeStyle = s.mode === 'erase' ? 'rgba(230,60,50,.5)' : 'rgba(40,200,80,.5)';
    c.beginPath();
    s.points.forEach(([x, y], i) => { if (i) c.lineTo(x * W, y * H); else c.moveTo(x * W, y * H); });
    if (s.points.length === 1) c.lineTo(s.points[0][0] * W + 0.01, s.points[0][1] * H);
    c.stroke();
  }
}

async function loadFrame(w, frame) {
  const token = ++w.loadToken;
  try {
    const response = await fetch('/jobs/' + w.jobId + '/mask/frame?i=' + Math.max(0, Math.round(frame)), { cache: 'no-store' });
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw Object.assign(new Error(body.message || body.detail || 'The frame could not be loaded.'), { fix: body.fix }); }
    const blob = await response.blob();
    if (token !== w.loadToken) return;
    w.frame = Number(response.headers.get('X-Frame') || frame); w.frames = Number(response.headers.get('X-Frames') || w.frames); w.fps = Number(response.headers.get('X-Fps') || w.fps) || 24;
    w.width = Number(response.headers.get('X-Width') || w.width); w.height = Number(response.headers.get('X-Height') || w.height);
    if (w.frameUrl) URL.revokeObjectURL(w.frameUrl);
    w.frameUrl = URL.createObjectURL(blob); w.previewUrl = '';
    const img = $('img', w.overlay); img.src = w.frameUrl;
    if (w.video && Math.abs(w.video.currentTime * w.fps - w.frame) > 0.6) { w.seeking = true; w.video.currentTime = w.frame / w.fps; }
    renderToolbar(w); positionOverlay(w);
    if (w.edits.some(e => e.frame === w.frame)) preview(w);
  } catch (e) { if (token === w.loadToken) showError(e, { key: 'wand' }); }
}

let previewTimer = null;
function preview(w) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    const here = w.edits.filter(e => e.frame === w.frame);
    if (!here.length) { if (w.frameUrl) $('img', w.overlay).src = w.frameUrl; w.info = ''; renderToolbar(w); return; }
    const token = ++w.previewToken; w.info = 'Looking at what the click selects…'; renderToolbar(w);
    try {
      const r = await send('/jobs/' + w.jobId + '/mask/preview', { frame: w.frame, edits: here });
      if (token !== w.previewToken) return;
      w.previewUrl = r.url + '?t=' + Date.now(); $('img', w.overlay).src = w.previewUrl;
      w.info = r.selections.map(s => (s.mode === 'include' ? 'Adds ' : 'Removes ') + (s.fraction * 100).toFixed(1) + '% of the frame' + (s.mode === 'include' && s.already_in_mask > 0.9 ? ' (already in the mask)' : '')).join(' · ') + '. Apply to follow it through the clip.';
    } catch (e) { if (token === w.previewToken) { w.info = ''; showError(e, { key: 'wand' }); } }
    renderToolbar(w);
  }, 150);
}

let estimateTimer = null;
function estimate(w) {
  clearTimeout(estimateTimer); w.estimate = null; renderToolbar(w);
  const tool = toolList().find(t => t.name === w.tool);
  if (!tool || !tool.paid) return;
  estimateTimer = setTimeout(async () => {
    try { const r = await api.estimateBranch(w.jobId, { stage: 'mask', tool: w.tool, params: { edits: JSON.stringify(w.edits) } }); w.estimate = r; }
    catch (e) { w.estimate = { error: plain(e).message }; }
    renderToolbar(w);
  }, 200);
}

async function apply(w, confirm) {
  const tool = toolList().find(t => t.name === w.tool);
  const body = { tool: w.tool, base: 'parent' };
  if (w.tool === 'brush') body.strokes = w.strokes; else body.edits = w.edits;
  if (confirm) body.confirm_cost = 'true';
  w.busy = true; renderToolbar(w);
  try {
    const r = await send('/jobs/' + w.jobId + '/mask/apply', body);
    notice('Mask fix started as a new branch run; the review opens there once the composite is rebuilt.', { kind: 'ok', key: 'wand' });
    close(w);
    navigate({ job: r.id, view: state.view === 'studio' ? 'studio' : 'quick' });
  } catch (e) {
    const p = plain(e);
    showError(e, { key: 'wand', actions: p.status === 402 ? [{ label: 'Run anyway · ' + usd(p.body.estimated_cost_usd), run: () => apply(w, true) }] : [] });
    w.busy = false; renderToolbar(w);
  }
  void tool;
}

function open(w, video) {
  w.video = video; w.viewer = video.parentElement; w.open = true;
  video.pause(); video.controls = false;
  if (!w.overlay) {
    w.overlay = el('div', { class: 'wand-overlay' }, el('img', { alt: 'Current frame with the mask outline', draggable: 'false' }), el('canvas', { 'aria-label': 'Click to select a region' }));
    const canvas = $('canvas', w.overlay);
    canvas.addEventListener('pointerdown', ev => onPointerDown(w, ev));
    canvas.addEventListener('pointermove', ev => onPointerMove(w, ev));
    canvas.addEventListener('pointerup', ev => onPointerUp(w, ev));
    canvas.addEventListener('pointercancel', ev => onPointerUp(w, ev));
    canvas.addEventListener('contextmenu', ev => ev.preventDefault());
  }
  if (getComputedStyle(w.viewer).position === 'static') w.viewer.style.position = 'relative';
  w.viewer.append(w.overlay);
  w.onSeeked = () => { if (w.seeking) { w.seeking = false; return; } loadFrame(w, Math.round(video.currentTime * w.fps)); };
  video.addEventListener('seeked', w.onSeeked);
  w.resize = new ResizeObserver(() => positionOverlay(w)); w.resize.observe(video);
  w.loadToken = 0; w.previewToken = 0;
  loadFrame(w, Math.round((video.currentTime || 0) * w.fps));
}

function close(w) {
  w.open = false;
  if (w.overlay && w.overlay.parentElement) w.overlay.remove();
  if (w.resize) { w.resize.disconnect(); w.resize = null; }
  if (w.video) { w.video.controls = true; if (w.onSeeked) w.video.removeEventListener('seeked', w.onSeeked); }
  if (w.frameUrl) { URL.revokeObjectURL(w.frameUrl); w.frameUrl = ''; }
  w.stroke = null; w.previewUrl = '';
  renderToolbar(w);
}

function normalized(w, ev) {
  const rect = ev.currentTarget.getBoundingClientRect();
  return [Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width)), Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height))];
}

function onPointerDown(w, ev) {
  if (w.busy) return;
  ev.preventDefault();
  try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* a pointer the browser does not track (some touch stacks): the stroke still works without capture */ }
  const [x, y] = normalized(w, ev);
  if (w.tool === 'brush') { w.stroke = { frame_from: w.frame, frame_to: w.frame + Math.max(1, w.brush.frames) - 1, mode: w.brush.mode, points: [[x, y]], radius: w.brush.radius }; drawMarkers(w); return; }
  const exclude = ev.altKey || ev.button === 2 || w.mode === 'exclude';
  w.edits.push({ frame: w.frame, x: Number(x.toFixed(4)), y: Number(y.toFixed(4)), label: exclude ? 0 : 1 });
  drawMarkers(w); preview(w); estimate(w);
}
function onPointerMove(w, ev) {
  if (!w.stroke) return;
  const [x, y] = normalized(w, ev); const last = w.stroke.points[w.stroke.points.length - 1];
  if (Math.hypot(x - last[0], y - last[1]) > 0.004) { w.stroke.points.push([Number(x.toFixed(4)), Number(y.toFixed(4))]); drawMarkers(w); }
}
function onPointerUp(w, ev) {
  if (!w.stroke) return;
  w.strokes.push(w.stroke); w.stroke = null; drawMarkers(w); renderToolbar(w);
  void ev;
}

function step(w, frames) { loadFrame(w, Math.max(0, Math.min((w.frames || 1) - 1, w.frame + frames))); }

function renderToolbar(w) {
  const node = w.node; if (!node) return;
  const bar = $('[data-wand-bar]', node), openButton = $('[data-wand-open]', node), hint = $('[data-wand-hint]', node);
  openButton.textContent = w.open ? 'Close the wand' : 'Fix the mask';
  openButton.classList.toggle('secondary', w.open);
  hint.hidden = w.open;
  bar.hidden = !w.open; if (!w.open) { bar.replaceChildren(); return; }
  const tools = toolList(); const tool = tools.find(t => t.name === w.tool) || tools[0]; const isBrush = w.tool === 'brush';
  const pending = isBrush ? w.strokes.length : w.edits.length;
  const frameLabel = w.frames ? `frame ${w.frame} of ${w.frames} · ${(w.frame / w.fps).toFixed(2)} s` : 'loading frame…';
  bar.replaceChildren(
    el('div', { class: 'wand-row' },
      el('span', { class: 'wand-frame-label mono', text: frameLabel }),
      el('span', { class: 'row wand-steps' },
        el('button', { type: 'button', class: 'small secondary', text: '−1 s', title: 'One second back', onclick: () => step(w, -Math.round(w.fps)) }),
        el('button', { type: 'button', class: 'small secondary', text: '◀ frame', onclick: () => step(w, -1) }),
        el('button', { type: 'button', class: 'small secondary', text: 'frame ▶', onclick: () => step(w, 1) }),
        el('button', { type: 'button', class: 'small secondary', text: '+1 s', title: 'One second forward', onclick: () => step(w, Math.round(w.fps)) }))),
    el('div', { class: 'wand-row' },
      el('label', { class: 'field wand-tool' }, 'Tool', (() => {
        const select = el('select', { 'aria-label': 'Mask wand tool' });
        for (const t of tools) select.append(el('option', { value: t.name, text: t.label + (t.paid ? ' · paid' : '') }));
        select.value = w.tool; select.onchange = () => { w.tool = select.value; w.stroke = null; estimate(w); renderToolbar(w); drawMarkers(w); };
        return select;
      })()),
      isBrush
        ? el('span', { class: 'row wand-brush' },
          el('button', { type: 'button', class: 'small ' + (w.brush.mode === 'paint' ? '' : 'secondary'), text: 'Paint', onclick: () => { w.brush.mode = 'paint'; renderToolbar(w); } }),
          el('button', { type: 'button', class: 'small ' + (w.brush.mode === 'erase' ? 'danger' : 'secondary'), text: 'Erase', onclick: () => { w.brush.mode = 'erase'; renderToolbar(w); } }),
          el('label', { class: 'wand-inline' }, 'radius ', (() => { const r = el('input', { type: 'range', min: '0.005', max: '0.15', step: '0.005', 'aria-label': 'Brush radius' }); r.value = String(w.brush.radius); r.oninput = () => { w.brush.radius = Number(r.value); }; return r; })()),
          el('label', { class: 'wand-inline' }, 'on ', (() => { const n = el('input', { type: 'number', min: '1', max: '500', step: '1', 'aria-label': 'Number of frames', style: 'width:64px' }); n.value = String(w.brush.frames); n.onchange = () => { w.brush.frames = Math.max(1, Math.round(Number(n.value) || 1)); renderToolbar(w); }; return n; })(), ' frames from here'))
        : el('span', { class: 'row wand-mode', role: 'group', 'aria-label': 'Click mode' },
          el('button', { type: 'button', class: 'small ' + (w.mode === 'include' ? '' : 'secondary'), text: '+ include', title: 'Click adds the region (a missed hand, a prop)', onclick: () => { w.mode = 'include'; renderToolbar(w); } }),
          el('button', { type: 'button', class: 'small ' + (w.mode === 'exclude' ? 'danger' : 'secondary'), text: '− exclude', title: 'Click removes spill (Alt-click does the same)', onclick: () => { w.mode = 'exclude'; renderToolbar(w); } }),
          el('span', { class: 'hint', text: 'Alt-click = exclude' }))),
    el('p', { class: 'hint wand-info', text: w.info || (isBrush ? 'Draw on the frame to paint (green) or erase (red). The stroke applies from this frame on.' : 'Click on the picture. + adds what you click (a missed finger, a prop), − removes spill. The selection shows at once; applying follows it through the clip.') }),
    el('div', { class: 'wand-row wand-actions' },
      el('span', { class: 'hint', text: pending ? `${pending} pending ${isBrush ? 'stroke' : 'click'}${pending > 1 ? 's' : ''}` + (isBrush ? '' : ` on ${new Set(w.edits.map(e => e.frame)).size} frame${new Set(w.edits.map(e => e.frame)).size > 1 ? 's' : ''}`) : 'Nothing pending yet.' }),
      el('button', { type: 'button', class: 'small secondary', text: isBrush ? 'Undo last stroke' : 'Undo last click', disabled: !pending || w.busy, onclick: () => { if (isBrush) w.strokes.pop(); else w.edits.pop(); drawMarkers(w); preview(w); estimate(w); renderToolbar(w); } }),
      el('button', { type: 'button', class: 'small secondary', text: 'Clear all', disabled: !pending || w.busy, onclick: () => { w.edits = []; w.strokes = []; drawMarkers(w); preview(w); estimate(w); renderToolbar(w); } }),
      (() => {
        const paid = tool && tool.paid; const est = w.estimate;
        const label = 'Apply to the whole clip · ' + (paid ? (est && est.estimated_cost_usd != null ? usd(est.estimated_cost_usd) : est && est.error ? 'cost unknown' : 'estimating…') : 'free');
        const b = el('button', { type: 'button', class: 'small', text: w.busy ? 'Starting…' : label, disabled: !pending || w.busy || (paid && !(est && est.estimated_cost_usd != null)), onclick: () => apply(w, !!paid) });
        if (paid) b.title = 'The estimate on this button is the confirmation: clicking sends confirm_cost=true.';
        return b;
      })()));
}

function mount(box, ctx) {
  const node = el('div', { class: 'wand' },
    el('div', { class: 'wand-head' },
      el('button', { type: 'button', class: 'small', text: 'Fix the mask', 'data-wand-open': true }),
      el('span', { class: 'hint', 'data-wand-hint': true, text: 'Pause the video on a frame, then click + on a missed region or − on spill. The fix is propagated through the clip and becomes a new branch run; this run stays as it is.' })),
    el('div', { class: 'wand-bar', 'data-wand-bar': true, hidden: true }));
  box.append(node);
  $('[data-wand-open]', node).onclick = () => { if (wand.open) close(wand); else open(wand, ctx.video); };
  return node;
}

registerReviewTool((box, ctx) => {
  const files = ctx.files || new Set();
  const depthRun = files.has('mask.mp4') && ctx.mode !== 'face_mesh' && files.has('original.mp4');
  const running = state.job && state.job.state === 'running';
  if (!wand || wand.jobId !== ctx.jobId) { if (wand) close(wand); wand = fresh(ctx.jobId); }
  if (!depthRun || running) { if (wand.node && wand.node.parentElement) { close(wand); wand.node.remove(); wand.node = null; } return; }
  if (!wand.node || wand.node.parentElement !== box) { if (wand.node) wand.node.remove(); wand.node = mount(box, ctx); renderToolbar(wand); }
  if (wand.open && wand.video !== ctx.video) { close(wand); open(wand, ctx.video); }
  if (wand.open) positionOverlay(wand);
});
