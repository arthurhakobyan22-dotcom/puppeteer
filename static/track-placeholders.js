// Placeholder tracks (Agent 1) so the editor shell works on its own: they only draw what a run already has.
// Mask: the mask area per frame (mask-cleanup-report.json) with red ticks where it jumps. Face: tracked / filled /
// missing per frame (face-tracking.json). Words: word blocks from the edit layer or words.json, "No transcript yet"
// otherwise, plus a tiny "add a word at the playhead" tool that exercises the edit layer (commit / undo / save).
import { api } from './api.js';
import { el } from './ui.js';

const JUMP = 0.12;   // |Δ area| above 12 % of the median area between neighbouring frames = a red tick

function perJob(load) {   // per-run cache of a loaded file: {jobId, value, pending}
  const cache = { jobId: null, value: null, pending: null };
  return ctx => {
    if (cache.jobId !== ctx.jobId) { cache.jobId = ctx.jobId; cache.value = null; cache.pending = null; }
    if (!cache.value && !cache.pending) {
      const job = ctx.jobId;
      cache.pending = Promise.resolve(load(ctx)).then(v => { if (cache.jobId === job) { cache.value = v; ctx.editor.redraw(); } }).catch(() => { if (cache.jobId === job) cache.value = { failed: true }; });
    }
    return cache.value;
  };
}
const hint = text => el('p', { class: 'hint', text });

// ---------------------------------------------------------------- Mask
const maskAreas = perJob(async ctx => {
  if (!ctx.files.has('mask-cleanup-report.json')) return { areas: [] };
  const report = await api.runFile(ctx.jobId, 'mask-cleanup-report.json');
  const areas = [];
  for (const row of Array.isArray(report) ? report : []) { const i = Number(String(row.frame || '').replace(/\D/g, '')); if (Number.isFinite(i)) areas[i] = Number(row.mask_pixels) || 0; }
  const known = areas.filter(a => a != null).sort((a, b) => a - b); const median = known.length ? known[Math.floor(known.length / 2)] : 0;
  const jumps = []; for (let i = 1; i < areas.length; i++) if (areas[i] != null && areas[i - 1] != null && median && Math.abs(areas[i] - areas[i - 1]) > JUMP * median) jumps.push(i);
  return { areas, max: known[known.length - 1] || 1, jumps };
});

export const maskPlaceholder = (() => {
  let last = null;   // draw(lane, view) gets no ctx; the track keeps the last one it saw
  return {
    id: 'mask', label: 'Mask', order: 10, markerColor: '#b3261e',
    available: ctx => ctx.files.has('mask.mp4') || ctx.files.has('mask-cleanup-report.json'),
    mount(row, panel, ctx) { last = ctx; maskAreas(ctx); panel.append(hint('Mask area on every frame (from mask-cleanup-report.json). Red ticks mark frames where the area jumps by more than 12 % of the median; [ and ] jump between them. Mask fixes arrive with the mask track; the old "Fix the mask" wand below still works.')); },
    update(ctx) { last = ctx; maskAreas(ctx); },
    markers(ctx) { const d = maskAreas(ctx); return (d && d.jumps) || []; },
    draw(lane, v) {
      const d = last && maskAreas(last), c = v.ctx2d;
      if (!d || !d.areas || !d.areas.length) { c.fillStyle = '#9a9eab'; c.font = '11px sans-serif'; c.textBaseline = 'middle'; c.fillText(d && d.failed ? 'The mask report could not be read' : d ? 'No mask area report in this run' : 'Loading mask areas…', 8, v.height / 2); return; }
      const first = Math.max(0, v.frameAt(0)), lastF = Math.min(v.frames - 1, v.frameAt(v.width) + 1), H = v.height - 8;
      c.beginPath(); c.moveTo(v.x(first), v.height);
      for (let f = first; f <= lastF; f++) { const y = v.height - 2 - ((d.areas[f] || 0) / d.max) * H; c.lineTo(v.x(f), y); c.lineTo(v.x(f + 1), y); }
      c.lineTo(v.x(lastF + 1), v.height); c.closePath(); c.fillStyle = 'rgba(31,24,192,.16)'; c.fill(); c.strokeStyle = 'rgba(31,24,192,.7)'; c.lineWidth = 1; c.stroke();
      c.fillStyle = 'rgba(179,38,30,.85)';
      for (const f of d.jumps) { const x = v.x(f); if (x < -2 || x > v.width + 2) continue; c.fillRect(Math.round(x), 8, Math.max(1.5, Math.min(3, v.pxPerFrame)), v.height - 8); }
    },
  };
})();

// ---------------------------------------------------------------- Face
const FACE = { tracked: '#3aa76d', filled: '#e0b341', missing: '#d9534f' };
function faceStatus(t) {
  if (!t || !t.frames) return null;
  const status = new Array(t.frames).fill('tracked');
  for (const f of t.filled_frames || []) if (f < t.frames) status[f] = 'filled';
  for (const f of t.missing_frames || []) if (f < t.frames) status[f] = 'missing';
  if (!(t.missing_frames || []).length) for (const g of t.gaps || []) for (let f = g.start_frame; f <= g.end_frame && f < t.frames; f++) status[f] = 'missing';
  return status;
}
export const facePlaceholder = (() => {
  let tracking = null, statuses = null;
  const read = ctx => { if (ctx.state.tracking !== tracking) { tracking = ctx.state.tracking; statuses = faceStatus(tracking); } };
  return {
    id: 'face', label: 'Face', order: 20, markerColor: '#b3261e',
    available: ctx => ctx.files.has('face-tracking.json'),
    mount(row, panel, ctx) {
      read(ctx);
      panel.append(hint('Face tracking per frame: green tracked, amber filled by interpolation (drawn dimmer), red lost (the depth composite stands in). Markers sit where the face is lost; [ and ] jump between them. Mesh edits arrive with the face track.'),
        el('div', { class: 'legend' }, ...Object.entries(FACE).map(([k, c]) => el('span', {}, el('i', { style: `background:${c}` }), k))));
    },
    update(ctx) { read(ctx); },
    markers() { return ((tracking && tracking.gaps) || []).map(g => g.start_frame); },
    draw(lane, v) {
      const c = v.ctx2d;
      if (!statuses) { c.fillStyle = '#9a9eab'; c.font = '11px sans-serif'; c.textBaseline = 'middle'; c.fillText('No face tracking report', 8, v.height / 2); return; }
      const first = Math.max(0, v.frameAt(0)), last = Math.min(statuses.length - 1, v.frameAt(v.width) + 1);
      for (let f = first; f <= last; f++) { c.fillStyle = FACE[statuses[f]] || '#ccc'; c.globalAlpha = statuses[f] === 'tracked' ? 0.75 : 0.9; c.fillRect(v.x(f), 12, Math.max(1, v.pxPerFrame - (v.pxPerFrame > 4 ? 1 : 0)), v.height - 20); }
      c.globalAlpha = 1;
    },
  };
})();

// ---------------------------------------------------------------- Words
export const wordsPlaceholder = (() => {
  let ctxLast = null;
  const fileWords = perJob(async ctx => (ctx.files.has('words.json') ? api.runFile(ctx.jobId, 'words.json') : { words: [] }));
  const words = ctx => {
    const layer = ctx.edits.layer.words;
    if (layer && Array.isArray(layer.words)) return layer.words;
    const f = fileWords(ctx); return (f && Array.isArray(f.words) ? f.words : []).map((w, i) => ({ id: 'f' + i, ...w }));
  };
  return {
    id: 'words', label: 'Words', order: 30, height: 34,
    available: ctx => ctx.files.has('original.mp4') || ctx.files.has('seedance-input.mp4'),
    mount(row, panel, ctx) {
      ctxLast = ctx;
      const input = el('input', { type: 'text', placeholder: 'a word', 'aria-label': 'Word to add', maxlength: '60', style: 'max-width:180px' });
      const add = el('button', { type: 'button', class: 'small', text: 'Add at the playhead', onclick: () => {
        const text = input.value.trim(); if (!text) { input.focus(); return; }
        const e = ctx.editor, start = e.frame / e.fps, end = Math.min(e.frames, e.frame + Math.max(1, Math.round(e.fps * 0.4))) / e.fps, id = 'w' + Date.now().toString(36);
        const current = words(ctx).map(w => ({ id: w.id, text: w.text, start: w.start, end: w.end }));
        ctx.edits.commit(`Add word "${text}" at ${start.toFixed(2)} s`, 'words', draft => {
          const value = draft && Array.isArray(draft.words) ? draft : { words: current, singing: false, edited: [] };
          value.words = [...value.words, { id, text, start: Number(start.toFixed(3)), end: Number(end.toFixed(3)) }].sort((a, b) => a.start - b.start);
          value.edited = [...new Set([...(value.edited || []), id])]; return value;
        });
        input.value = '';
      } });
      const remove = el('button', { type: 'button', class: 'small secondary', text: 'Remove the word at the playhead', onclick: () => {
        const f = ctx.editor.frame / ctx.editor.fps; const hit = words(ctx).find(w => w.start <= f + 1e-6 && f < w.end);
        if (!hit) return;
        ctx.edits.commit(`Remove word "${hit.text}"`, 'words', draft => {
          const value = draft && Array.isArray(draft.words) ? draft : { words: words(ctx).map(w => ({ id: w.id, text: w.text, start: w.start, end: w.end })), singing: false, edited: [] };
          value.words = value.words.filter(w => w.id !== hit.id); value.edited = [...new Set([...(value.edited || []), hit.id])]; return value;
        });
      } });
      input.addEventListener('keydown', e => { if (e.key === 'Enter') add.click(); });
      panel.append(hint('Placeholder until the words track arrives (transcription, timing drags, split / merge). You can already add or remove a word at the playhead: it is a pending edit (Undo / Redo / Save edits work on it).'), el('div', { class: 'row' }, input, add, remove));
    },
    update(ctx) { ctxLast = ctx; fileWords(ctx); },
    markers(ctx) { return words(ctx).map(w => Math.floor(w.start * ctx.editor.fps + 1e-3)); },
    draw(lane, v) {
      const c = v.ctx2d, list = ctxLast ? words(ctxLast) : [];
      if (!list.length) { c.fillStyle = '#9a9eab'; c.font = '11px sans-serif'; c.textBaseline = 'middle'; c.fillText('No transcript yet', 8, v.height / 2); return; }
      c.font = '11px sans-serif'; c.textBaseline = 'middle';
      for (const w of list) {
        const x0 = v.x(w.start * v.fps), x1 = v.x(Math.max(w.end, w.start + 1 / v.fps) * v.fps);
        if (x1 < 0 || x0 > v.width) continue;
        c.fillStyle = '#eef0fb'; c.strokeStyle = '#1f18c0'; c.lineWidth = 1; c.fillRect(x0, 6, x1 - x0 - 1, v.height - 12); c.strokeRect(x0 + 0.5, 6.5, x1 - x0 - 2, v.height - 13);
        c.save(); c.beginPath(); c.rect(x0 + 2, 0, Math.max(0, x1 - x0 - 4), v.height); c.clip(); c.fillStyle = '#16181f'; c.fillText(w.text, x0 + 4, v.height / 2); c.restore();
      }
    },
  };
})();
