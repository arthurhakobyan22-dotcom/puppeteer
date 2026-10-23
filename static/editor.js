// The timeline editor inside the review panel (step 02): view switch, stacked synced videos, an overlay canvas on
// the rendered picture, the transport, the timeline with its tracks, the selected track's tools and the Save bar.
//
// The editor keeps its own state (frame, range, selected track, the <video> elements) outside the DOM that the
// review panel's update() refreshes, so the 2.5 s polls never reset a video. Frames: one playhead = one integer
// frame; seeking sets currentTime = (frame + 0.5) / fps, the frame shown is floor(currentTime * fps + 1e-3), and
// playback follows requestVideoFrameCallback (fallback: timeupdate).
//
// API for tracks (ctx.editor) and for the console (window.puppeteer.editor):
//   editor.frame, editor.frames, editor.fps, editor.range ({from, to} inclusive or null), editor.selected (track id)
//   editor.seek(frame), editor.step(n), editor.play(), editor.pause(), editor.toggle()
//   editor.setRange(range | null), editor.select(trackId | null), editor.redraw() (lanes + overlay)
//   editor.addView({id, label, layers: [{file | src, style?}], caption?, download?, downloadLabel?, available?(ctx), order?}) — a view
//     whose first layer is the base video and the others are stacked over it (e.g. Tint = original + mask video with a
//     CSS blend style); editor.setView(id); editor.view (id); editor.video (the base <video> of the current view)
//   editor.on(event, fn) — 'frame', 'range', 'select', 'view', 'zoom', 'update'; editor.ctx() — the track ctx
//   editor.overlay (the <canvas>), editor.pictureBox() — {left, top, width, height} of the picture inside the stage
import { api } from './api.js';
import { $, $$, el, ariaFor, showError, tpl } from './ui.js';
import { state } from './state.js';
import { edits } from './editlayer.js';
import { createTimeline, tracks } from './timeline.js';
import './tracks.js';   // registers the Mask, Face and Words tracks

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** The rendered picture inside a box of cw × ch for a clip of vw × vh (object-fit: contain, centred). */
export function pictureBox(cw, ch, vw, vh) {
  vw = vw || 16; vh = vh || 9;
  const s = Math.min(cw / vw, ch / vh); const width = vw * s, height = vh * s;
  return { left: (cw - width) / 2, top: (ch - height) / 2, width, height };
}

export function mountEditor(host, { tabs = [], onViewChosen } = {}) {
  const node = tpl('tpl-editor'); host.append(node);
  const q = s => $(s, node);
  const tabsBox = q('[data-tabs]'), stageView = q('[data-stage]'), caption = q('[data-caption]'), download = q('[data-download]');
  const transport = q('[data-transport]'), panelBox = q('[data-track-panel]'), saveBar = q('[data-savebar]');
  const overlay = el('canvas', { class: 'stage-overlay', 'aria-label': 'Overlay for the selected track' }); stageView.append(overlay);
  const zipLink = el('a', { download: '', hidden: true, style: 'margin-left:10px', text: 'Masks as PNGs (.zip) ↓' });

  const listeners = {};
  const videos = new Map();   // src -> <video>, kept alive so switching views is instant and nothing is downloaded twice
  const panels = new Map();   // track id -> panel element
  const extraViews = new Map();
  let data = { jobId: null, files: new Set(), run: null, mode: '' }, clip = { frames: 0, fps: 24, width: 0, height: 0, source: '' }, ready = false, discarding = false, inactiveSync = 0;

  const editor = {
    node, frame: 0, frames: 1, fps: 24, range: null, selected: null, view: null, video: null, playing: false, overlay, timeline: null,
    on(event, fn) { (listeners[event] = listeners[event] || new Set()).add(fn); return () => listeners[event].delete(fn); },
    emit(event, arg) { for (const fn of [...(listeners[event] || [])]) { try { fn(arg, editor); } catch (e) { console.warn('editor listener failed', event, e); } } },
    ctx() { return { jobId: data.jobId, files: data.files, run: data.run, mode: data.mode, editor, edits, state }; },
  };
  const tl = editor.timeline = createTimeline(q('[data-timeline]'), editor);

  // ---------------------------------------------------------------- views and videos
  function builtinViews() {
    return tabs.map(([label, file, text], i) => ({ id: file, label, layers: [{ file }], caption: text, download: file, order: i * 10, available: ctx => ctx.files.has(file) }));
  }
  function allViews() {
    const ctx = editor.ctx(); const byId = new Map(builtinViews().map(v => [v.id, v]));
    for (const v of extraViews.values()) byId.set(v.id, { order: 500, ...v });
    return [...byId.values()].filter(v => { try { return !v.available || v.available(ctx); } catch { return false; } }).sort((a, b) => a.order - b.order);
  }
  const srcOf = layer => layer.src || ('/runs/' + data.jobId + '/' + layer.file);
  function videoFor(src) {
    let v = videos.get(src);
    if (v) return v;
    v = el('video', { playsinline: true, preload: 'auto', class: 'stage-video', dataset: { src } });
    v.muted = true; v.src = src;
    v.addEventListener('loadedmetadata', () => {
      if (v === editor.video) { onMetadata(v); return; }
      setTime(v, editor.playing && editor.video ? frameOf(editor.video.currentTime) : editor.frame);   // a stacked layer or a background view joins at the playhead
      if (editor.playing && (editor.layers || []).includes(v)) v.play().catch(() => {});
    });
    v.addEventListener('play', () => { if (v === editor.video) onPlay(); });
    v.addEventListener('pause', () => { if (v === editor.video) onPause(); });
    v.addEventListener('ended', () => { if (v === editor.video) onPause(); });
    v.addEventListener('seeked', () => { if (v === editor.video && !editor.playing) followVideo(v); });
    v.addEventListener('timeupdate', () => { if (v === editor.video && editor.playing) followVideo(v); });   // fallback; also covers a hidden tab, where requestVideoFrameCallback does not fire
    v.addEventListener('error', () => { if (v === editor.video) showError(new Error('This preview could not be played in the browser.'), { key: 'editor-video' }); });
    videos.set(src, v); stageView.insertBefore(v, overlay);
    return v;
  }
  editor.addView = def => { if (!def || !def.id || !def.layers || !def.layers.length) throw new Error('A view needs an id and at least one layer.'); extraViews.set(def.id, def); renderTabs(); };
  editor.setView = (id, { chosen = false } = {}) => {
    const views = allViews(); const view = views.find(v => v.id === id) || views[0];
    if (!view) return;
    if (chosen && onViewChosen) onViewChosen(view.id);
    const layers = view.layers.map(l => ({ ...l, video: videoFor(srcOf(l)) }));
    const base = layers[0].video, previous = editor.video, wasPlaying = editor.playing, muted = previous ? previous.muted : false, volume = previous ? previous.volume : 1;
    for (const v of videos.values()) { v.classList.remove('active', 'layer'); v.removeAttribute('style'); v.controls = false; v.muted = true; }
    layers.forEach((l, i) => { l.video.classList.add('active'); if (i) { l.video.classList.add('layer'); Object.assign(l.video.style, l.style || {}); } });
    base.controls = true; base.muted = muted; base.volume = volume;   // one audible video: the base of the current view
    editor.view = view.id; editor.video = base; editor.layers = layers.map(l => l.video);
    if (previous && previous !== base && !previous.paused) { editor.playing = false; previous.pause(); }
    for (const v of editor.layers) setTime(v, editor.frame);
    if (wasPlaying && previous !== base) { editor.playing = false; editor.play(); }
    if (base.readyState >= 1) onMetadata(base);
    for (const b of $$('button', tabsBox)) b.classList.toggle('active', b.dataset.view === view.id);
    caption.textContent = view.caption || view.label;
    const file = view.download || layers[0].file; download.hidden = !file && !layers[0].src;
    download.href = file ? '/runs/' + data.jobId + '/' + file : layers[0].src; download.setAttribute('download', (file || layers[0].src || '').split('/').pop());
    download.textContent = (view.downloadLabel || 'Download ' + view.label.toLowerCase()) + ' ↓';   // a stacked view names what the file really is
    const masks = /mask/i.test(view.id) && [...data.files].some(f => f.startsWith('clean-masks/'));   // the masks as PNG frames too (GET /jobs/{id}/download/mask.zip)
    zipLink.hidden = !masks; zipLink.href = '/jobs/' + data.jobId + '/download/mask.zip'; download.after(zipLink);
    placeOverlay(); editor.emit('view', view.id);
  };
  function preloadViews(views) {   // every view's videos exist (preload=auto, hidden) so a switch is instant; ones no view uses any more go
    if (!data.jobId) return;
    const needed = new Set(views.flatMap(v => v.layers.map(srcOf)));
    for (const [src, v] of videos) if (!needed.has(src) && !(editor.layers || []).includes(v)) { v.pause(); v.removeAttribute('src'); v.load(); v.remove(); videos.delete(src); }
    for (const src of needed) videoFor(src);
  }
  function renderTabs() {
    const views = allViews(); const key = views.map(v => v.id + ':' + v.layers.map(srcOf).join('+')).join('|');
    if (tabsBox.dataset.key === key) return;
    preloadViews(views);
    tabsBox.dataset.key = key; tabsBox.replaceChildren();
    for (const v of views) tabsBox.append(el('button', { type: 'button', dataset: { view: v.id, file: v.layers[0].file || '' }, text: v.label, onclick: () => editor.setView(v.id, { chosen: true }) }));
    for (const b of $$('button', tabsBox)) b.classList.toggle('active', b.dataset.view === editor.view);
  }

  // ---------------------------------------------------------------- frames, seeking, playback
  const timeOf = f => (f + 0.5) / editor.fps;
  const frameOf = t => clamp(Math.floor(t * editor.fps + 1e-3), 0, editor.frames - 1);
  function setTime(v, f) { const t = timeOf(f); if (v.readyState >= 1 && Math.abs(v.currentTime - t) > 0.2 / editor.fps) { try { v.currentTime = t; } catch { /* not seekable yet; loadedmetadata seeks again */ } } }
  function syncInactive() {   // paused: bring the other loaded videos to the same frame, so a view switch shows it at once
    clearTimeout(inactiveSync);
    inactiveSync = setTimeout(() => { if (editor.playing) return; for (const v of videos.values()) if (!editor.layers.includes(v)) setTime(v, editor.frame); }, 250);
  }
  editor.seek = (f, { follow = true } = {}) => {
    f = clamp(Math.round(Number(f) || 0), 0, editor.frames - 1);
    if (editor.playing) editor.pause();
    const changed = f !== editor.frame; editor.frame = f;
    for (const v of editor.layers || []) setTime(v, f);
    syncInactive(); frameChanged(changed, follow);
  };
  editor.step = n => editor.seek(editor.frame + n);
  editor.play = () => {
    const v = editor.video; if (!v) return;
    if (editor.frame >= editor.frames - 1) { editor.frame = 0; for (const l of editor.layers) setTime(l, 0); }
    const p = v.play(); if (p && p.catch) p.catch(e => { if (e && e.name !== 'AbortError') showError(new Error('The browser did not start playback.'), { key: 'editor-video' }); });
    for (const l of editor.layers) if (l !== v) l.play().catch(() => {});
  };
  editor.pause = () => { for (const l of editor.layers || []) l.pause(); };
  editor.toggle = () => (editor.video && !editor.video.paused ? editor.pause() : editor.play());
  function followVideo(v) { const f = frameOf(v.currentTime); if (f !== editor.frame) { editor.frame = f; frameChanged(true, true); } }
  function onPlay() {
    editor.playing = true; renderTransport();
    const v = editor.video;
    const tick = (now, meta) => {
      if (!editor.playing || v !== editor.video) return;
      const f = frameOf(meta && meta.mediaTime != null ? meta.mediaTime : v.currentTime);
      for (const l of editor.layers) if (l !== v && Math.abs(l.currentTime - v.currentTime) > 1.5 / editor.fps) l.currentTime = v.currentTime;
      if (f !== editor.frame) { editor.frame = f; frameChanged(true, true); }
      v.requestVideoFrameCallback(tick);
    };
    if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(tick);
  }
  function onPause() {
    editor.playing = false;
    for (const l of editor.layers || []) if (!l.paused) l.pause();
    const v = editor.video; if (v) { const f = frameOf(v.currentTime); const changed = f !== editor.frame; editor.frame = f; for (const l of editor.layers) if (l !== v) setTime(l, f); frameChanged(changed, false); }
    syncInactive(); renderTransport();
  }
  function onMetadata(v) {
    if (v.videoWidth) { clip.width = v.videoWidth; clip.height = v.videoHeight; stageView.style.aspectRatio = v.videoWidth + ' / ' + v.videoHeight; }
    if (!clip.frames && v.duration && Number.isFinite(v.duration)) setClip(Math.round(v.duration * (clip.fps || 24)), clip.fps || 24, 'duration');
    setTime(v, editor.frame); placeOverlay();
  }
  function setClip(frames, fps, source) {
    if (!frames) return;
    clip.frames = frames; clip.fps = fps || 24; clip.source = source;
    editor.frames = frames; editor.fps = clip.fps; editor.frame = clamp(editor.frame, 0, frames - 1);
    tl.setClip(frames, clip.fps); renderTransport();
  }
  async function loadClipInfo(jobId) {
    const reports = (data.run && data.run.reports) || {};
    const norm = reports.input_doctor && reports.input_doctor.data && reports.input_doctor.data.normalized;
    if (norm && norm.frames) setClip(Number(norm.frames), Number(norm.fps) || 24, 'report');
    else if (state.tracking && state.tracking.frames) setClip(Number(state.tracking.frames), Number(state.tracking.fps) || 24, 'tracking');
    if (!data.files.has('original.mp4')) return;
    try {   // the prepared clip itself is the authority (the same headers the mask wand reads)
      const r = await fetch('/jobs/' + jobId + '/mask/frame?i=0', { cache: 'no-store' });
      if (!r.ok || jobId !== data.jobId) return;
      const frames = Number(r.headers.get('X-Frames')), fps = Number(r.headers.get('X-Fps'));
      clip.width = Number(r.headers.get('X-Width')) || clip.width; clip.height = Number(r.headers.get('X-Height')) || clip.height;
      if (frames) setClip(frames, fps || 24, 'clip');
      placeOverlay();
    } catch { /* the duration fallback still sets the length */ }
  }

  function frameChanged(changed, follow) {
    renderCounter();
    if (follow) tl.follow();
    tl.placePlayhead(); if (changed) tl.draw();
    redrawOverlay();
    if (changed) { const ctx = editor.ctx(); for (const row of tl.visibleRows()) if (row.mounted && row.track.onFrame) { try { row.track.onFrame(editor.frame, ctx); } catch (e) { console.warn('track onFrame failed', row.track.id, e); } } editor.emit('frame', editor.frame); }
  }
  editor.setRange = r => {
    if (r && (r.from == null || r.to == null)) r = null;
    editor.range = r ? { from: clamp(Math.min(r.from, r.to), 0, editor.frames - 1), to: clamp(Math.max(r.from, r.to), 0, editor.frames - 1) } : null;
    tl.placePlayhead(); renderCounter(); editor.emit('range', editor.range);
  };
  editor.select = id => {
    editor.selected = id || null; tl.highlight(editor.selected);
    for (const [key, panel] of panels) panel.hidden = key !== editor.selected;
    panelHint.hidden = !!editor.selected && panels.has(editor.selected);
    const t = tracks().find(x => x.id === editor.selected);
    overlay.style.pointerEvents = t && t.pointer ? 'auto' : 'none'; overlay.classList.toggle('interactive', !!(t && t.pointer));
    redrawOverlay(); editor.emit('select', editor.selected);
  };
  editor.redraw = () => { tl.draw(); redrawOverlay(); };

  // ---------------------------------------------------------------- overlay canvas over the picture (letterbox-safe)
  editor.pictureBox = () => pictureBox(stageView.clientWidth, stageView.clientHeight, clip.width || (editor.video && editor.video.videoWidth), clip.height || (editor.video && editor.video.videoHeight));
  function placeOverlay() {
    const b = editor.pictureBox(), dpr = window.devicePixelRatio || 1;
    Object.assign(overlay.style, { left: b.left + 'px', top: b.top + 'px', width: b.width + 'px', height: b.height + 'px' });
    overlay.width = Math.max(1, Math.round(b.width * dpr)); overlay.height = Math.max(1, Math.round(b.height * dpr));
    redrawOverlay();
  }
  function redrawOverlay() {
    const c = overlay.getContext('2d'); c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, overlay.width, overlay.height);
    const box = { width: overlay.width, height: overlay.height, dpr: window.devicePixelRatio || 1 };
    for (const row of tl.visibleRows()) {
      if (!row.mounted || !row.track.canvas) continue;
      c.save(); try { row.track.canvas(c, box, editor.frame); } catch (e) { console.warn('track canvas failed', row.track.id, e); } c.restore();
    }
  }
  new ResizeObserver(() => placeOverlay()).observe(stageView);
  function point(e) {
    const r = overlay.getBoundingClientRect();
    return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1), frame: editor.frame };
  }
  for (const [type, hook] of [['pointerdown', 'down'], ['pointermove', 'move'], ['pointerup', 'up'], ['pointercancel', 'up']]) {
    overlay.addEventListener(type, e => {
      const t = tracks().find(x => x.id === editor.selected);
      if (!t || !t.pointer || !t.pointer[hook]) return;
      if (type === 'pointerdown') { e.preventDefault(); try { overlay.setPointerCapture(e.pointerId); } catch { /* capture is a convenience */ } }
      try { t.pointer[hook](e, point(e)); } catch (err) { showError(err, { key: 'editor-pointer' }); }
    });
  }
  overlay.addEventListener('contextmenu', e => { if (overlay.style.pointerEvents === 'auto') e.preventDefault(); });

  // ---------------------------------------------------------------- transport, counter, Save bar
  const btn = (text, title, onclick, cls = 'small secondary') => el('button', { type: 'button', class: cls, text, title, 'aria-label': ariaFor(text, title), onclick });
  const playButton = btn('▶ Play', 'Play / pause (Space)', () => editor.toggle(), 'small');
  const counter = el('span', { class: 'tr-counter mono', 'aria-live': 'off' });
  const zoomOut = btn('−', 'Zoom out (Ctrl/Cmd + wheel over the timeline)', () => tl.zoom(1 / 1.6)), zoomIn = btn('+', 'Zoom in (Ctrl/Cmd + wheel over the timeline)', () => tl.zoom(1.6));
  const zoomFit = btn('fit', 'Whole clip in view', () => tl.zoomFit());
  transport.append(
    el('span', { class: 'tr-steps' }, btn('−1 s', 'One second back (Shift+←)', () => editor.step(-Math.round(editor.fps))), btn('◀ frame', 'One frame back (←)', () => editor.step(-1)), playButton,
      btn('frame ▶', 'One frame forward (→)', () => editor.step(1)), btn('+1 s', 'One second forward (Shift+→)', () => editor.step(Math.round(editor.fps)))),
    counter,
    el('span', { class: 'tr-zoom', role: 'group', 'aria-label': 'Timeline zoom' }, el('span', { class: 'hint', text: 'zoom' }), zoomOut, zoomIn, zoomFit));
  editor.on('zoom', () => renderTransport());
  function renderCounter() {
    counter.textContent = `frame ${editor.frame} / ${editor.frames} · ${(editor.frame / editor.fps).toFixed(2)} s` + (editor.range ? `  ·  range ${editor.range.from}–${editor.range.to} (${editor.range.to - editor.range.from + 1} frames, Esc clears)` : '');
  }
  function renderTransport() {
    playButton.textContent = editor.playing ? '❚❚ Pause' : '▶ Play'; playButton.setAttribute('aria-label', editor.playing ? 'Pause' : 'Play');
    zoomIn.disabled = !tl.canZoomIn(); zoomOut.disabled = !tl.canZoomOut(); zoomFit.disabled = tl.fit;
    renderCounter();
  }
  const panelHint = el('p', { class: 'hint track-panel-hint', text: 'Click a track name on the left of the timeline to see its tools here. Drag across the ruler or an empty part of a track to select a range; click to move the playhead. Keys: ← → one frame, Shift+← → one second, Space play, [ ] markers, Esc clears the range, Cmd/Ctrl+Z undo.' });
  panelBox.append(panelHint);
  function renderSaveBar() {
    const n = edits.pending.total || 0;
    const summary = el('div', { class: 'sb-summary' },
      el('strong', { text: n ? `${n} pending edit${n > 1 ? 's' : ''}` : 'No pending edits' }),
      el('span', { class: 'hint', text: n ? edits.summary.join(' · ') : 'Edits you make on the tracks are kept here until you save them as a new version; this run is never changed.' }));
    const undo = btn('Undo', edits.canUndo ? 'Undo: ' + edits.undoLabel + ' (Cmd/Ctrl+Z)' : 'Nothing to undo', () => edits.undo()); undo.disabled = !edits.canUndo || edits.busy;
    const redo = btn('Redo', edits.canRedo ? 'Redo: ' + edits.redoLabel + ' (Shift+Cmd/Ctrl+Z)' : 'Nothing to redo', () => edits.redo()); redo.disabled = !edits.canRedo || edits.busy;
    const actions = el('div', { class: 'sb-actions' }, undo, redo);
    if (discarding && n) actions.append(el('span', { class: 'hint', text: `Discard ${n} pending edit${n > 1 ? 's' : ''}?` }), btn('Yes, discard', 'Remove every pending edit', async () => { discarding = false; await edits.discard(); }, 'small danger'), btn('Keep', 'Keep the edits', () => { discarding = false; renderSaveBar(); }));
    else { const d = btn('Discard', 'Remove every pending edit (asks first)', () => { discarding = true; renderSaveBar(); }); d.disabled = !n || edits.busy; actions.append(d); }
    const save = btn(edits.busy ? 'Saving…' : 'Save edits · free, creates one new version', 'Saves every pending edit as one new branch run; this run stays as it is and its approval does not carry over', () => edits.save(), 'small'); save.disabled = !n || edits.busy;
    actions.append(save);
    saveBar.replaceChildren(summary, actions);
    if (edits.stale && n) saveBar.append(el('p', { class: 'line warn', text: 'This run changed after you started editing. Check your edits on the tracks before saving.' }));
    saveBar.classList.toggle('has-edits', !!n);
  }

  // ---------------------------------------------------------------- keyboard (ignored while typing)
  function onKey(e) {
    if (!node.isConnected) { document.removeEventListener('keydown', onKey, true); return; }
    if (!ready || node.closest('[hidden]')) return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    const mod = e.metaKey || e.ctrlKey, key = e.key;
    if (mod && (key === 'z' || key === 'Z')) { e.preventDefault(); e.stopPropagation(); if (e.shiftKey) edits.redo(); else edits.undo(); return; }
    if (e.ctrlKey && (key === 'y' || key === 'Y')) { e.preventDefault(); e.stopPropagation(); edits.redo(); return; }
    if (mod || e.altKey) return;
    if (key === ' ' && t && t.closest && t.closest('button, a') && !node.contains(t)) return;   // Space on a button outside the editor clicks it
    const second = Math.round(editor.fps);
    const actions = {
      ArrowLeft: () => editor.step(e.shiftKey ? -second : -1), ArrowRight: () => editor.step(e.shiftKey ? second : 1), ' ': () => editor.toggle(),
      Home: () => editor.seek(0), End: () => editor.seek(editor.frames - 1), '[': () => jumpMarker(-1), ']': () => jumpMarker(1), Escape: () => editor.setRange(null),
    };
    if (!actions[key] || (key === 'Escape' && !editor.range)) return;
    e.preventDefault(); e.stopPropagation(); actions[key]();   // capture phase: the focused <video>'s own controls must not act on the same key
  }
  document.addEventListener('keydown', onKey, true);
  function jumpMarker(direction) {
    const ctx = editor.ctx(); const rows = tl.visibleRows().filter(r => !editor.selected || r.track.id === editor.selected);
    const all = [...new Set(rows.flatMap(r => { try { return (r.track.markers ? r.track.markers(ctx) : []) || []; } catch { return []; } }))].sort((a, b) => a - b);
    const next = direction > 0 ? all.find(f => f > editor.frame) : [...all].reverse().find(f => f < editor.frame);
    if (next != null) editor.seek(next);
  }
  const offEdits = edits.on('change', () => {
    if (!node.isConnected) { offEdits(); return; }
    if (edits.jobId !== data.jobId) return;
    updateTracks(); renderSaveBar();
  });

  // ---------------------------------------------------------------- tracks
  function updateTracks() {
    const ctx = editor.ctx();
    tl.sync(ctx);
    for (const row of tl.visibleRows()) {
      if (!row.mounted) {
        const panel = el('div', { class: 'track-panel-body', dataset: { track: row.track.id }, hidden: true }, el('h3', { text: row.track.label }));
        panels.set(row.track.id, panel); panelBox.append(panel); row.mounted = true;
        try { if (row.track.mount) row.track.mount(row.lane, panel, ctx); } catch (e) { showError(e, { key: 'track-' + row.track.id }); }
      }
      try { if (row.track.update) row.track.update(ctx); } catch (e) { console.warn('track update failed', row.track.id, e); }
    }
    for (const [id, panel] of panels) { const row = tl.rows.get(id); if (!row || !row.shown) panel.hidden = true; }
    if (editor.selected) editor.select(editor.selected);
    tl.draw(); redrawOverlay();
  }

  /** Called by the review panel after every load / poll. `preferred` = the view to show (kept stable across polls). */
  editor.update = ({ jobId, files, run, mode, preferred }) => {
    if (jobId !== data.jobId) {   // a new run: start over (render() normally remounts everything for a new job)
      for (const v of videos.values()) { v.pause(); v.removeAttribute('src'); v.load(); v.remove(); }
      videos.clear(); clip = { frames: 0, fps: 24, width: 0, height: 0, source: '' }; editor.frame = 0; editor.range = null; editor.video = null; editor.layers = [];
      data = { jobId, files, run, mode };
      loadClipInfo(jobId); edits.load(jobId);
    }
    data = { jobId, files, run, mode };
    ready = allViews().length > 0;
    renderTabs();
    const views = allViews();
    if (views.length && (!editor.video || !views.some(v => v.id === editor.view) || (preferred && preferred !== editor.view && views.some(v => v.id === preferred)))) editor.setView(preferred && views.some(v => v.id === preferred) ? preferred : views[0].id);
    if (!clip.frames && state.tracking && state.tracking.frames) setClip(Number(state.tracking.frames), Number(state.tracking.fps) || 24, 'tracking');
    updateTracks(); renderSaveBar(); renderTransport();
    editor.emit('update', editor.ctx());
  };
  renderTransport(); renderSaveBar();
  window.puppeteer = Object.assign(window.puppeteer || {}, { editor, edits });
  return editor;
}
