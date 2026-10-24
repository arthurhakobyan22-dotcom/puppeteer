// The timeline: a track registry plus the component the editor mounts. One ruler (seconds + frame ticks), one
// playhead across every row, a range band, zoom from "fit" up to 24 px per frame, horizontal scroll inside its own
// box (the page never scrolls sideways), track selection by clicking the label, markers with click-to-jump.
//
// Tracks (static/track-*.js) register themselves:
//   registerTrack({
//     id: 'mask', label: 'Mask', order: 10, height: 40,        // height (px) of the lane, optional
//     available(ctx) { return ctx.files.has('mask.mp4'); },    // ctx = {jobId, files, run, mode, editor, edits, state}
//     mount(row, panel, ctx) {},   // once per job: row = the lane element (row.canvas = its canvas), panel = its tools box
//     update(ctx) {},              // after every job load/poll and every edits change
//     draw(lane, view) {},         // view = {pxPerFrame, frames, fps, scrollLeft, width, height, frame, range, x(frame), frameAt(x), ctx2d, dpr}
//     markers(ctx) { return [12, 40]; },   // frames for [ / ] and click-to-jump; drawn as ticks on the lane
//     onFrame(frame, ctx) {},      // the playhead moved
//     canvas(ctx2d, box, frame) {},        // draw on the overlay canvas over the video; box = {width, height, dpr} in device px
//     pointer: { down(e, pt), move(e, pt), up(e, pt) },   // overlay pointer events while this track is selected; pt = {x, y, frame}, x/y 0–1 of the picture
//   });
// A later registerTrack with the same id replaces the earlier one (that is how a placeholder is swapped out).
// Elements a track puts inside its lane that handle their own pointer events carry `data-tl-item`; everywhere
// else a drag selects a range and a click moves the playhead.
import { el, cssVar } from './ui.js';

const registry = new Map();
export function registerTrack(def) {
  if (!def || !def.id) throw new Error('A track needs an id.');
  registry.set(def.id, { order: 100, height: 40, label: def.id, ...def });
}
export function tracks() { return [...registry.values()].sort((a, b) => a.order - b.order); }

export const MAX_PX_PER_FRAME = 24;
const RULER = 26;

export function createTimeline(host, editor) {
  const labels = el('div', { class: 'tl-labels' }, el('div', { class: 'tl-corner', style: `height:${RULER}px` }));
  const ruler = el('canvas', { class: 'tl-ruler', style: `height:${RULER}px` });
  const lanes = el('div', { class: 'tl-lanes' });
  const playhead = el('div', { class: 'tl-playhead', 'aria-hidden': 'true' });
  const band = el('div', { class: 'tl-range', hidden: true, 'aria-hidden': 'true' });
  const stage = el('div', { class: 'tl-stage' }, ruler, lanes, band, playhead);
  const inner = el('div', { class: 'tl-inner' }, stage);
  const scroll = el('div', { class: 'tl-scroll', tabindex: '-1' }, inner);
  const root = el('div', { class: 'tl' }, labels, scroll);
  host.append(root);

  const rows = new Map();   // id -> {track, label, lane, canvas, shown}
  const tl = { root, scroll, ppf: 0, fit: true, frames: 1, fps: 24, rows };
  let raf = 0;

  const width = () => scroll.clientWidth || 300;
  const fitPpf = () => width() / Math.max(1, tl.frames);
  const clampPpf = p => Math.max(fitPpf(), Math.min(MAX_PX_PER_FRAME, p));
  tl.frameAt = clientX => { const r = scroll.getBoundingClientRect(); return (clientX - r.left + scroll.scrollLeft) / tl.ppf; };
  const frameIndex = clientX => Math.max(0, Math.min(tl.frames - 1, Math.floor(tl.frameAt(clientX))));

  tl.setClip = (frames, fps) => {
    frames = Math.max(1, Math.round(frames || 1)); fps = Number(fps) || 24;
    if (frames === tl.frames && fps === tl.fps && tl.ppf) return;
    tl.frames = frames; tl.fps = fps; if (tl.fit || !tl.ppf) tl.ppf = fitPpf(); tl.ppf = clampPpf(tl.ppf); tl.draw();
  };

  tl.zoom = (factor, clientX) => {
    const r = scroll.getBoundingClientRect(); const anchorX = clientX == null ? (editor.frame + 0.5) * tl.ppf - scroll.scrollLeft : clientX - r.left;
    const anchorFrame = (anchorX + scroll.scrollLeft) / tl.ppf;
    const next = clampPpf(tl.ppf * factor); tl.fit = next <= fitPpf() + 1e-6; tl.ppf = next;
    inner.style.width = Math.ceil(tl.frames * tl.ppf) + 'px';
    scroll.scrollLeft = Math.max(0, anchorFrame * tl.ppf - anchorX);
    tl.draw(); editor.emit('zoom');
  };
  tl.zoomFit = () => { tl.fit = true; tl.ppf = fitPpf(); scroll.scrollLeft = 0; tl.draw(); editor.emit('zoom'); };
  tl.canZoomIn = () => tl.ppf < MAX_PX_PER_FRAME - 1e-6;
  tl.canZoomOut = () => tl.ppf > fitPpf() + 1e-6;

  /** Keep the playhead visible (during playback and frame steps). */
  tl.follow = () => {
    const x = (editor.frame + 0.5) * tl.ppf, left = scroll.scrollLeft, w = width();
    if (x < left + 8 || x > left + w - 8) scroll.scrollLeft = Math.max(0, x - w * 0.25);
  };

  // ---------------------------------------------------------------- rows
  tl.sync = ctx => {
    const list = tracks();
    for (const t of list) {
      let row = rows.get(t.id);
      if (row && row.track !== t) { row.label.remove(); row.lane.remove(); rows.delete(t.id); row = null; }   // replaced definition
      let shown = false;
      try { shown = !t.available || !!t.available(ctx); } catch (e) { shown = false; }
      if (!row && !shown) continue;
      if (!row) {
        const canvas = el('canvas', { class: 'tl-lane-canvas' });
        const lane = el('div', { class: 'tl-lane', dataset: { track: t.id }, style: `height:${t.height}px` }, canvas); lane.canvas = canvas;
        const label = el('button', { type: 'button', class: 'tl-label', dataset: { track: t.id }, style: `height:${t.height}px`, title: 'Select the ' + t.label + ' lane (its tools show below)', 'aria-label': t.label + ' lane', 'aria-pressed': 'false', text: t.label, onclick: () => editor.select(editor.selected === t.id ? null : t.id) });
        row = { track: t, label, lane, canvas, shown: false, mounted: false }; rows.set(t.id, row);
      }
      row.shown = shown; row.label.hidden = !shown; row.lane.hidden = !shown;
    }
    // keep DOM order = track order
    for (const t of list) { const row = rows.get(t.id); if (row) { labels.append(row.label); lanes.append(row.lane); } }
    tl.draw();
  };
  tl.visibleRows = () => [...rows.values()].filter(r => r.shown).sort((a, b) => a.track.order - b.track.order);
  tl.highlight = id => { for (const [key, row] of rows) { row.label.classList.toggle('active', key === id); row.label.setAttribute('aria-pressed', key === id ? 'true' : 'false'); row.lane.classList.toggle('selected', key === id); } };

  // ---------------------------------------------------------------- drawing
  tl.draw = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(drawNow); };
  function view(canvas, height) {
    const dpr = window.devicePixelRatio || 1, w = width();
    if (canvas) { canvas.width = Math.max(1, Math.round(w * dpr)); canvas.height = Math.max(1, Math.round(height * dpr)); canvas.style.width = w + 'px'; canvas.style.height = height + 'px'; }
    const ctx2d = canvas ? canvas.getContext('2d') : null; if (ctx2d) ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { pxPerFrame: tl.ppf, frames: tl.frames, fps: tl.fps, scrollLeft: scroll.scrollLeft, width: w, height, frame: editor.frame, range: editor.range, dpr, ctx2d,
      x: f => f * tl.ppf - scroll.scrollLeft, frameAt: x => Math.floor((x + scroll.scrollLeft) / tl.ppf) };
  }
  function drawNow() {
    if (!root.isConnected) return;
    if (tl.fit) tl.ppf = fitPpf(); else tl.ppf = clampPpf(tl.ppf);
    const w = width();
    inner.style.width = Math.max(w, Math.ceil(tl.frames * tl.ppf)) + 'px'; stage.style.width = w + 'px';
    drawRuler(view(ruler, RULER));
    for (const row of tl.visibleRows()) {
      const v = view(row.canvas, row.track.height); drawLaneBase(v);
      try { if (row.track.draw) row.track.draw(row.lane, v); } catch (e) { console.warn('track draw failed', row.track.id, e); }
      drawMarkers(row, v);
    }
    placeOverlays();
  }
  function secondStep() { const pxPerSecond = tl.ppf * tl.fps; return [1, 2, 5, 10, 15, 30, 60].find(s => s * pxPerSecond >= 46) || 60; }
  function drawRuler(v) {
    const c = v.ctx2d, first = Math.max(0, v.frameAt(0)), last = Math.min(tl.frames, v.frameAt(v.width) + 1);
    c.fillStyle = cssVar('--canvas-ruler') || '#1e222b'; c.fillRect(0, 0, v.width, RULER);
    c.strokeStyle = cssVar('--canvas-tick') || '#3a4150'; c.fillStyle = cssVar('--canvas-ruler-text') || '#9aa1b0'; c.font = '10px "IBM Plex Mono", ui-monospace, monospace'; c.textBaseline = 'top'; c.lineWidth = 1;
    const showFrames = tl.ppf >= 3, numberEvery = [1, 2, 5, 10, 12, 24, 48].find(n => n * tl.ppf >= 30) || 48;
    c.beginPath();
    if (showFrames) for (let f = first; f < last; f++) { const x = Math.round(v.x(f)) + 0.5; const h = f % numberEvery === 0 ? 8 : 4; c.moveTo(x, RULER - h); c.lineTo(x, RULER); }
    else { const quarter = Math.max(1, Math.round(tl.fps / 4)); if (quarter * tl.ppf >= 5) for (let f = first - (first % quarter); f < last; f += quarter) { const x = Math.round(v.x(f)) + 0.5; c.moveTo(x, RULER - 4); c.lineTo(x, RULER); } }
    c.stroke();
    const step = secondStep(); c.strokeStyle = cssVar('--canvas-tick-strong') || '#5a6275'; c.beginPath();
    for (let s = Math.floor(first / tl.fps / step) * step; s * tl.fps < last; s += step) {
      const f = Math.round(s * tl.fps); const x = Math.round(v.x(f)) + 0.5; if (x < -40) continue;
      c.moveTo(x, 0); c.lineTo(x, RULER); c.fillText(s + ' s', x + 3, 2);
    }
    c.stroke();
    if (showFrames && tl.ppf >= 10) { c.fillStyle = cssVar('--muted') || '#9aa1b0'; for (let f = first; f < last; f++) if (f % numberEvery === 0 && f % Math.round(tl.fps) !== 0) c.fillText(String(f), Math.round(v.x(f)) + 2, 13); }
  }
  function drawLaneBase(v) {
    const c = v.ctx2d; c.clearRect(0, 0, v.width, v.height);
    const step = secondStep(); c.fillStyle = cssVar('--canvas-band') || '#1a1e26';
    for (let s = 0; s * tl.fps < tl.frames; s += step * 2) { const x0 = v.x(Math.round(s * tl.fps)), x1 = v.x(Math.round((s + step) * tl.fps)); if (x1 < 0 || x0 > v.width) continue; c.fillRect(x0, 0, x1 - x0, v.height); }
  }
  function drawMarkers(row, v) {
    let list = [];
    try { list = row.track.markers ? row.track.markers(editor.ctx()) || [] : []; } catch { list = []; }
    const c = v.ctx2d; c.fillStyle = row.track.markerColor ? (cssVar(row.track.markerColor) || row.track.markerColor) : cssVar('--accent');
    for (const f of list) { const x = v.x(f) + tl.ppf / 2; if (x < -6 || x > v.width + 6) continue; c.beginPath(); c.moveTo(x - 4, 0); c.lineTo(x + 4, 0); c.lineTo(x, 6); c.closePath(); c.fill(); }
    row.markers = list;
  }
  function placeOverlays() {
    const total = RULER + tl.visibleRows().reduce((s, r) => s + r.track.height, 0);
    const center = (editor.frame + 0.5) * tl.ppf - scroll.scrollLeft;
    playhead.style.transform = `translateX(${Math.round(center)}px)`; playhead.style.height = total + 'px'; playhead.hidden = center < -2 || center > width() + 2;
    const r = editor.range;
    if (r) { const x0 = r.from * tl.ppf - scroll.scrollLeft, x1 = (r.to + 1) * tl.ppf - scroll.scrollLeft; band.hidden = x1 < 0 || x0 > width(); band.style.left = Math.max(-1, x0) + 'px'; band.style.width = Math.max(2, Math.min(width(), x1) - Math.max(-1, x0)) + 'px'; band.style.height = total + 'px'; }
    else band.hidden = true;
  }
  tl.placePlayhead = placeOverlays;

  // ---------------------------------------------------------------- interaction: click = playhead, drag = range, Ctrl/Cmd+wheel = zoom
  let drag = null;
  stage.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.target.closest('[data-tl-item]')) return;
    e.preventDefault();
    const lane = e.target.closest('.tl-lane');
    drag = { x0: e.clientX, f0: frameIndex(e.clientX), moved: false, lane: lane && lane.dataset.track };
    try { stage.setPointerCapture(e.pointerId); } catch { /* capture is a convenience */ }
  });
  stage.addEventListener('pointermove', e => {
    if (!drag) return;
    if (!drag.moved && Math.abs(e.clientX - drag.x0) < 4) return;
    drag.moved = true;
    const r = scroll.getBoundingClientRect();
    if (e.clientX > r.right - 16) scroll.scrollLeft += 12; else if (e.clientX < r.left + 16) scroll.scrollLeft -= 12;
    const f = frameIndex(e.clientX); editor.setRange({ from: Math.min(drag.f0, f), to: Math.max(drag.f0, f) });
  });
  const end = e => {
    if (!drag) return;
    const d = drag; drag = null;
    if (d.moved) { editor.emit('range'); return; }
    let f = d.f0;
    const row = d.lane && rows.get(d.lane);
    if (row && row.markers && row.markers.length) {   // click near a marker jumps exactly to it
      const x = e.clientX - scroll.getBoundingClientRect().left + scroll.scrollLeft;
      const near = row.markers.map(m => [Math.abs((m + 0.5) * tl.ppf - x), m]).sort((a, b) => a[0] - b[0])[0];
      if (near && near[0] <= 6) f = near[1];
    }
    editor.setRange(null); editor.seek(f);
  };
  stage.addEventListener('pointerup', end);
  stage.addEventListener('pointercancel', () => { drag = null; });
  scroll.addEventListener('wheel', e => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    tl.zoom(Math.exp(-Math.max(-60, Math.min(60, e.deltaY)) * 0.006), e.clientX);
  }, { passive: false });
  scroll.addEventListener('scroll', () => tl.draw(), { passive: true });
  new ResizeObserver(() => tl.draw()).observe(scroll);
  return tl;
}
