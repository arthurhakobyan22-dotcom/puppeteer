// Words track (Agent 4): transcription, word blocks, timing drags, split / merge / add / delete, subtitles export
// (docs/TIMELINE-SPEC.md §6, §A4; docs/WORDS.md).
//
// Every edit is one commit to layer.words ({words: [{id, text, start, end}], singing, edited: [ids], replaced?}) through
// the shared edit layer (one undo stack with the other tracks; pending until "Save edits", which writes words.json +
// mouth-guidance.json into the new version). The lane shows one block per word (DOM elements with data-tl-item):
// click = select + jump, double-click = edit the text, drag an edge = fix the timing (snaps to frames, never overlaps
// a neighbour, at least one frame; one commit per drag). "Transcribe" runs the free local Whisper (or the paid fal
// fallback with its estimate on the button) through POST /jobs/{id}/words/transcribe.
import { api, getJSON, send, plain } from './api.js';
import { el, ariaFor, notice, showError, usd } from './ui.js';
import { registerTrack } from './timeline.js';

const st = { jobId: null, ctx: null, panel: null, layerBox: null, info: null, infoKey: null, selected: null, drag: null, editing: null, adding: null, busy: false, engine: 'local', singing: null, blocksKey: '', status: '' };
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
const fps = ctx => (ctx && ctx.editor.fps) || 24;
const snap = (t, ctx) => Math.round(t * fps(ctx)) / fps(ctx);
const fmt = t => Number(t).toFixed(2);
const frameOf = (t, ctx) => Math.floor(t * fps(ctx) + 1e-3);
const running = ctx => !!(ctx && ctx.state.job && ctx.state.job.state === 'running');
const uid = () => 'w' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

// ---------------------------------------------------------------- the words right now: the layer when it has any, else the run's words.json
function layerValue(ctx) { const v = ctx && ctx.edits.layer.words; return v && typeof v === 'object' && Array.isArray(v.words) ? v : null; }
function fileWords() { return st.info && st.info.source === 'words.json' ? st.info.words : st.info && st.info.fileWords ? st.info.fileWords : []; }
function words(ctx) {
  const v = layerValue(ctx);
  const list = v ? v.words : fileWords().map((w, i) => ({ id: 'f' + i, text: w.text, start: w.start, end: w.end }));
  return list.filter(w => w && String(w.text || '').trim()).map(w => ({ id: String(w.id), text: String(w.text), start: Number(w.start) || 0, end: Number(w.end) || 0, ...(w.split_of ? { split_of: String(w.split_of), split_sep: w.split_sep === '' ? '' : ' ' } : {}) })).sort((a, b) => a.start - b.start);
}
const singing = ctx => { const v = layerValue(ctx); return st.singing != null ? st.singing : v ? !!v.singing : !!(st.info && st.info.meta && st.info.meta.singing); };

async function loadInfo(ctx, force = false) {
  const key = ctx.jobId + '|' + (ctx.files.has('words.json') ? 'w' : '') + (ctx.files.has('original.mp4') ? 'o' : '');
  if (!force && st.infoKey === key) return;
  st.infoKey = key;
  try {
    const info = await getJSON('/jobs/' + ctx.jobId + '/words');
    if (st.infoKey !== key) return;
    // keep the file's words apart from the pending ones (the GET answers the layer first)
    if (info.source !== 'words.json' && info.words_file) { try { const f = await api.runFile(ctx.jobId, 'words.json'); info.fileWords = (f && f.words) || []; } catch { info.fileWords = []; } }
    st.info = info; render(); ctx.editor.redraw();
  } catch (e) { if (st.infoKey === key) { st.info = { failed: true, engines: [], words: [] }; showError(e, { key: 'words-track' }); render(); } }
}

// ---------------------------------------------------------------- edits (one commit each)
// `edited` = ids of the words this session changed (the Save bar's "n words edited"): `touched` are added, `dropped`
// removed (a word merged into its neighbour is not a separate edit: the merged word is). A deleted word stays listed.
function commitWords(ctx, label, fn, touched = [], dropped = []) {
  const base = words(ctx).map(w => ({ ...w }));
  return ctx.edits.commit(label, 'words', d => {
    const v = d && typeof d === 'object' && Array.isArray(d.words) ? d : { words: base, singing: singing(ctx), edited: [] };
    v.words = fn(v.words.map(w => ({ ...w }))).filter(Boolean).sort((a, b) => a.start - b.start);
    v.edited = [...new Set([...(Array.isArray(v.edited) ? v.edited : []), ...touched])].filter(id => !dropped.includes(id));
    return v;
  });
}
const neighbours = (list, id) => { const i = list.findIndex(w => w.id === id); return { i, w: list[i], prev: list[i - 1], next: list[i + 1] }; };
function setText(ctx, id, text) {
  const { w } = neighbours(words(ctx), id); if (!w) return;
  text = text.replace(/\s+/g, ' ').trim();
  if (text === w.text) return;
  if (!text) { remove(ctx, id); return; }
  commitWords(ctx, `Edit "${w.text}" → "${text}"`, list => list.map(x => (x.id === id ? { ...x, text } : x)), [id]);
}
function setTiming(ctx, id, start, end) {
  const { w } = neighbours(words(ctx), id); if (!w) return;
  start = Number(start.toFixed(4)); end = Number(end.toFixed(4));
  if (Math.abs(start - w.start) < 1e-6 && Math.abs(end - w.end) < 1e-6) return;
  const what = Math.abs(start - w.start) > 1e-6 ? `start of "${w.text}" to ${fmt(start)} s` : `end of "${w.text}" to ${fmt(end)} s`;
  commitWords(ctx, 'Move the ' + what, list => list.map(x => (x.id === id ? { ...x, start, end } : x)), [id]);
}
function remove(ctx, id) {
  const { w } = neighbours(words(ctx), id); if (!w) return;
  if (st.selected === id) st.selected = null;
  commitWords(ctx, `Delete "${w.text}"`, list => list.filter(x => x.id !== id), [id]);
}
function wordAt(list, ctx) { const t = (ctx.editor.frame + 0.5) / fps(ctx); return list.find(w => w.start <= t && t < w.end); }
function split(ctx) {
  const list = words(ctx), w = (st.selected && list.find(x => x.id === st.selected && x.start <= (ctx.editor.frame + 0.5) / fps(ctx) && (ctx.editor.frame + 0.5) / fps(ctx) < x.end)) || wordAt(list, ctx);
  if (!w) { notice('Put the playhead inside a word to split it.', { kind: 'warn', fix: 'Click a word block, step to the frame where the second part starts, then Split.', key: 'words' }); return; }
  const at = Number((ctx.editor.frame / fps(ctx)).toFixed(4)), one = 1 / fps(ctx);
  if (at - w.start < one - 1e-6 || w.end - at < one - 1e-6) { notice('The split point must leave at least one frame on each side.', { kind: 'warn', fix: 'Step the playhead one frame further into the word, then Split.', key: 'words' }); return; }
  const r = (at - w.start) / (w.end - w.start), text = w.text; let a, b, sep = ' ';
  const spaces = [...text.matchAll(/ /g)].map(m => m.index);
  if (spaces.length) { const cut = spaces.reduce((best, i) => (Math.abs(i / text.length - r) < Math.abs(best / text.length - r) ? i : best), spaces[0]); a = text.slice(0, cut); b = text.slice(cut + 1); }
  else if (text.length > 1) { const cut = Math.min(text.length - 1, Math.max(1, Math.round(text.length * r))); a = text.slice(0, cut); b = text.slice(cut); sep = ''; }
  else { a = text; b = text; }
  // The right part remembers what the split removed (split_of = the word both parts came from, split_sep = '' inside a
  // word, ' ' at a space), so "Merge with next" puts the word back together exactly: "and" → "a" + "nd" → "and".
  const id2 = uid(), root = w.split_of || w.id;
  commitWords(ctx, `Split "${w.text}" at ${fmt(at)} s`, list2 => list2.flatMap(x => (x.id === w.id ? [{ ...x, text: a, end: at, split_of: x.split_of || root }, { id: id2, text: b, start: at, end: w.end, split_of: root, split_sep: sep }] : [x])), [w.id, id2]);
  st.selected = id2;
}
function merge(ctx) {
  const list = words(ctx), { w, next } = neighbours(list, st.selected);
  if (!w || !next) { notice(w ? 'This is the last word; there is nothing to merge it with.' : 'Select a word first (click its block).', { kind: 'warn', fix: 'Click the first of the two words, then Merge with next.', key: 'words' }); return; }
  // Rule: two parts of one split word join with what the split removed (nothing inside a word); any other pair joins with a space.
  const sep = next.split_of && next.split_of === (w.split_of || w.id) ? (next.split_sep === '' ? '' : ' ') : ' ';
  commitWords(ctx, `Merge "${w.text}" + "${next.text}"`, list2 => list2.filter(x => x.id !== next.id).map(x => (x.id === w.id ? { ...x, text: x.text + sep + next.text, end: next.end } : x)), [w.id], [next.id]);
}
/** Where a new word would go: the selected range (clipped to the gap it starts in) or the playhead (up to 0.4 s, until the next word). */
function slotForAdd(ctx) {
  const list = words(ctx), f = fps(ctx), one = 1 / f, r = ctx.editor.range, total = ctx.editor.frames / f;
  let start = r ? r.from / f : ctx.editor.frame / f, end = r ? (r.to + 1) / f : start + Math.max(one, 0.4);
  const inside = list.find(w => w.start <= start + 1e-6 && start < w.end - 1e-6);
  if (inside) { if (!r) return null; start = inside.end; }
  const next = list.find(w => w.start >= start - 1e-6); if (next) end = Math.min(end, next.start);
  end = Math.min(end, total);
  return end - start >= one - 1e-6 ? { start: snap(start, ctx), end: snap(end, ctx) } : null;
}
function startAdd(ctx) {
  const slot = slotForAdd(ctx);
  if (!slot) { notice(ctx.editor.range ? 'There is no free time in the selected range for a new word.' : 'There is already a word at the playhead.', { kind: 'warn', fix: 'Move the playhead (or the range) to a gap between words, or shorten a neighbour first.', key: 'words' }); return; }
  st.adding = slot; st.editing = null; draw(); render();
}
function finishAdd(ctx, text) {
  const slot = st.adding; st.adding = null;
  text = (text || '').replace(/\s+/g, ' ').trim();
  if (slot && text) { const id = uid(); commitWords(ctx, `Add "${text}" at ${fmt(slot.start)} s`, list => [...list, { id, text, start: slot.start, end: slot.end }], [id]); st.selected = id; }
  draw(); render();
}

// ---------------------------------------------------------------- transcription
function engineInfo(name) { return ((st.info && st.info.engines) || []).find(e => e.name === name) || null; }
async function transcribe(ctx, { confirm = false } = {}) {
  const engine = engineInfo(st.engine) || engineInfo('local'); if (!engine || st.busy) return;
  st.busy = true; st.status = engine.paid ? 'Transcribing with ' + engine.label + '…' : 'Transcribing on this Mac… the first run loads the model (about 10 s for a short clip).'; render();
  const body = { engine: engine.name, singing: singing(ctx) ? 'true' : '' }; if (confirm) body.confirm_cost = 'true';
  try {
    const r = await send('/jobs/' + ctx.jobId + '/words/transcribe', body);
    const list = r.words.map(w => ({ id: uid(), text: w.text, start: w.start, end: w.end }));
    st.status = `${plural(r.words.length, 'word')} from ${r.engine_label}` + (r.cached ? ' (from the cache, instant and free)' : ` in ${Number(r.seconds).toFixed(1)} s`) + (r.written ? '; saved as this run\'s words.json.' : '.');
    const current = words(ctx).map(w => [w.text, w.start, w.end].join('|')).join(' '), incoming = r.words.map(w => [w.text, w.start, w.end].join('|')).join(' ');
    if (layerValue(ctx) || (!r.written && current !== incoming)) {   // the run already has a transcript (or pending edits): the new one is a pending edit, undoable, saved with "Save edits"
      await ctx.edits.commit(`Transcribe again${r.singing ? ' (singing mode)' : ''}`, 'words', () => ({ words: list, singing: !!r.singing, edited: [], replaced: { engine: r.engine_name, language: r.language } }));
      st.status += ' It is a pending edit: Save edits keeps it in a new version.';
    }
    st.busy = false;
    if (r.written && window.puppeteer && window.puppeteer.loadJob) await window.puppeteer.loadJob({ quiet: true });
    await loadInfo(ctx, true);
  } catch (e) {
    st.busy = false; st.status = '';
    const p = plain(e);
    showError(e, { key: 'words', actions: p.status === 402 ? [{ label: 'Transcribe anyway · ' + usd(p.body.estimated_cost_usd), run: () => transcribe(ctx, { confirm: true }) }] : [] });
  }
  render();
}

// ---------------------------------------------------------------- lane: one DOM block per word (data-tl-item handles its own pointer events)
function ensureLayer(lane) {
  if (st.layerBox && st.layerBox.isConnected && st.layerBox.parentElement === lane) return st.layerBox;
  st.layerBox = el('div', { class: 'wb-layer' }); lane.append(st.layerBox); st.blocksKey = ''; return st.layerBox;
}
function blockFor(w, ctx) {
  const b = el('div', { class: 'wb', 'data-tl-item': true, dataset: { id: w.id }, title: `${w.text} · ${fmt(w.start)}–${fmt(w.end)} s · double-click to edit, drag the edges to fix the timing` },
    el('span', { class: 'wb-h l', 'data-edge': 'start', 'aria-hidden': 'true' }), el('span', { class: 'wb-t', text: w.text }), el('span', { class: 'wb-h r', 'data-edge': 'end', 'aria-hidden': 'true' }));
  b.addEventListener('pointerdown', e => onBlockDown(e, w.id));
  b.addEventListener('dblclick', e => { e.preventDefault(); if (!running(st.ctx)) { st.editing = w.id; st.selected = w.id; draw(); } });
  return b;
}
function inlineInput(value, onDone) {
  const input = el('input', { type: 'text', class: 'wb-input', value, 'aria-label': 'Word text', maxlength: '120', 'data-tl-item': true });
  let done = false; const finish = keep => { if (done) return; done = true; onDone(keep ? input.value : null); };
  input.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false); });
  input.addEventListener('blur', () => finish(true));
  input.addEventListener('pointerdown', e => e.stopPropagation());
  setTimeout(() => { input.focus(); input.select(); }, 0);
  return input;
}
let lastView = null;
function draw(lane, v) {
  if (lane) lastView = { lane, v }; else if (lastView) ({ lane, v } = lastView); else return;
  const ctx = st.ctx; if (!ctx) return;
  const box = ensureLayer(lane), list = words(ctx), c = v.ctx2d;
  if (!list.length && !st.adding && c) { c.fillStyle = '#9a9eab'; c.font = '11px sans-serif'; c.textBaseline = 'middle'; c.fillText(st.busy ? 'Transcribing…' : 'No transcript yet · select Words and click Transcribe', 8, v.height / 2); }
  const key = list.map(w => w.id + w.text).join('|') + '|' + (st.editing || '') + '|' + (st.adding ? 'add' : '');
  if (key !== st.blocksKey) {
    st.blocksKey = key; box.replaceChildren();
    for (const w of list) {
      const b = blockFor(w, ctx);
      if (st.editing === w.id) { b.classList.add('editing'); b.querySelector('.wb-t').replaceWith(inlineInput(w.text, text => { st.editing = null; st.blocksKey = ''; if (text != null) setText(ctx, w.id, text); draw(); })); }
      box.append(b);
    }
    if (st.adding) box.append(el('div', { class: 'wb adding', 'data-tl-item': true, dataset: { id: '_new' } }, inlineInput('', text => finishAdd(ctx, text))));
  }
  const f = fps(ctx), live = st.drag && st.drag.moved ? st.drag : null;
  for (const b of box.children) {
    const id = b.dataset.id, w = id === '_new' ? st.adding : list.find(x => x.id === id); if (!w) continue;
    const s = live && live.id === id ? live.start : w.start, e = live && live.id === id ? live.end : w.end;
    const x0 = v.x(s * f), x1 = v.x(e * f), editing = id === '_new' || st.editing === id;
    const width = Math.max(editing ? 90 : 3, x1 - x0);
    b.hidden = x0 + width < -40 || x0 > v.width + 40;
    b.style.left = Math.round(x0) + 'px'; b.style.width = Math.round(width) + 'px';
    b.classList.toggle('sel', id === st.selected); b.classList.toggle('narrow', x1 - x0 < 26);
    b.classList.toggle('here', w.start * f <= ctx.editor.frame + 0.5 && ctx.editor.frame + 0.5 < w.end * f);
  }
}

function onBlockDown(e, id) {
  const ctx = st.ctx; if (!ctx || e.button !== 0) return;
  e.stopPropagation();
  const edge = e.target.dataset && e.target.dataset.edge;
  const list = words(ctx), { w, prev, next } = neighbours(list, id); if (!w) return;
  if (!edge || running(ctx)) { st.selected = id; ctx.editor.setRange(null); ctx.editor.seek(frameOf(w.start, ctx)); render(); draw(); return; }
  e.preventDefault();
  const one = 1 / fps(ctx), total = ctx.editor.frames / fps(ctx);
  st.selected = id;
  st.drag = { id, edge, moved: false, x0: e.clientX, start: w.start, end: w.end, min: edge === 'start' ? (prev ? prev.end : 0) : w.start + one, max: edge === 'start' ? w.end - one : (next ? next.start : total), orig: { start: w.start, end: w.end } };
  const target = e.currentTarget;
  try { target.setPointerCapture(e.pointerId); } catch { /* capture is a convenience */ }
  const move = ev => {
    const d = st.drag; if (!d) return;
    if (!d.moved && Math.abs(ev.clientX - d.x0) < 3) return;
    d.moved = true;
    const t = Math.min(d.max, Math.max(d.min, snap(ctx.editor.timeline.frameAt(ev.clientX) / fps(ctx), ctx)));
    if (d.edge === 'start') d.start = t; else d.end = t;
    draw(); renderTimes(d);
  };
  const up = () => {
    target.removeEventListener('pointermove', move); target.removeEventListener('pointerup', up); target.removeEventListener('pointercancel', up);
    const d = st.drag; st.drag = null;
    if (d && d.moved) setTiming(ctx, d.id, d.start, d.end);   // one commit per drag
    else if (d) ctx.editor.seek(frameOf(d.orig.start, ctx));
    draw(); render();
  };
  target.addEventListener('pointermove', move); target.addEventListener('pointerup', up); target.addEventListener('pointercancel', up);
}

// ---------------------------------------------------------------- panel
const button = (text, title, onclick, cls = 'small secondary', disabled = false) => el('button', { type: 'button', class: cls, text, title, 'aria-label': ariaFor(text, title), onclick, disabled });
function renderTimes(d) { const out = st.panel && st.panel.querySelector('[data-times]'); if (out) out.textContent = `${fmt(d.start)}–${fmt(d.end)} s (frames ${frameOf(d.start, st.ctx)}–${Math.max(frameOf(d.start, st.ctx), Math.ceil(d.end * fps(st.ctx) - 1e-3) - 1)})`; }
function render() {
  const ctx = st.ctx, box = st.panel; if (!ctx || !box) return;
  if (box.contains(document.activeElement) && document.activeElement.tagName === 'INPUT' && document.activeElement.type === 'text') return;   // keep a field being typed in alive
  const list = words(ctx), pending = !!layerValue(ctx), info = st.info, sel = list.find(w => w.id === st.selected) || null, here = wordAt(list, ctx);
  const can = !running(ctx);
  const source = !info ? 'Loading…' : info.failed ? 'The words could not be loaded.' : !list.length ? 'No transcript yet.' :
    `${plural(list.length, 'word')} · ` + (pending ? 'pending edits (saved with "Save edits")' : `from words.json${info.meta && info.meta.engine ? ' (' + info.meta.engine + (info.meta.language ? ', ' + info.meta.language : '') + (info.meta.singing ? ', singing mode' : '') + ')' : ''}`);
  // transcribe row
  const engines = (info && info.engines) || [];
  if (!engines.some(e => e.name === st.engine)) st.engine = 'local';
  const eng = engineInfo(st.engine);
  const select = el('select', { 'aria-label': 'Transcription engine', disabled: st.busy }, engines.map(e => el('option', { value: e.name, text: e.label + (e.paid ? ' · paid · ' + usd(e.estimated_cost_usd) : ' · free, runs locally') })));
  select.value = st.engine; select.onchange = () => { st.engine = select.value; render(); };
  const sing = el('input', { type: 'checkbox', 'aria-label': 'Singing mode' }); sing.checked = singing(ctx); sing.disabled = st.busy;
  sing.onchange = () => { st.singing = sing.checked; render(); };
  const label = !eng ? 'Transcribe' : st.busy ? 'Transcribing…' : eng.paid ? 'Transcribe · ' + usd(eng.estimated_cost_usd) : 'Transcribe · free, runs locally';
  const go = button(label, eng && eng.paid ? 'Paid: sends the audio to ' + eng.label + '; the estimate is on the button' : 'Whisper on this Mac; nothing leaves the computer', () => transcribe(ctx, { confirm: !!(eng && eng.paid) }), 'small', !eng || st.busy || !can || !(info && info.has_audio) || (eng && !eng.paid && !eng.ready) || (eng && eng.offline_blocked));
  const problem = eng && !eng.paid && eng.problem ? el('p', { class: 'line warn', text: eng.problem.message + ' ' + eng.problem.fix }) : eng && eng.offline_blocked ? el('p', { class: 'line warn', text: 'Offline mode (PUPPETEER_OFFLINE=1) blocks the paid engine; nothing would be sent. Use the free local engine, or start the app without PUPPETEER_OFFLINE.' }) : info && !info.has_audio ? el('p', { class: 'line warn', text: 'This run has no audio track to transcribe; add words by hand.' }) : null;
  const tRow = el('div', { class: 'mt-row' }, select, el('label', { class: 'wand-inline', title: 'Looser auto-timing for songs: no conditioning on earlier lyrics, longer minimum word length, held notes fill short gaps. Expect to drag edges afterwards.' }, sing, ' Singing mode'), go);
  // selected word
  const target = sel || here;
  const times = target ? el('span', { class: 'hint mono', 'data-times': true, text: `${fmt(target.start)}–${fmt(target.end)} s (frames ${frameOf(target.start, ctx)}–${Math.max(frameOf(target.start, ctx), Math.ceil(target.end * fps(ctx) - 1e-3) - 1)})` }) : null;
  const text = el('input', { type: 'text', 'aria-label': 'Selected word', value: target ? target.text : '', placeholder: 'select a word', maxlength: '120', disabled: !target || !can, style: 'max-width:200px' });
  text.addEventListener('keydown', e => { if (e.key === 'Enter') { setText(ctx, target.id, text.value); text.blur(); } else if (e.key === 'Escape') { text.value = target.text; text.blur(); } });
  text.addEventListener('change', () => target && setText(ctx, target.id, text.value));
  text.addEventListener('blur', () => setTimeout(render, 0));   // render() skips while a field is focused
  const idx = target ? list.findIndex(w => w.id === target.id) : -1;
  const wRow = el('div', { class: 'mt-row' }, el('strong', { text: target ? (sel ? 'Selected' : 'At the playhead') : 'No word selected' }), text, times);
  const eRow = el('div', { class: 'mt-row' },
    button('Split at playhead', 'Split the word under the playhead into two (each keeps at least one frame)', () => split(ctx), 'small secondary', !can || !list.length),
    button('Merge with next', 'Join the selected word with the next one', () => { if (!sel && here) st.selected = here.id; merge(ctx); }, 'small secondary', !can || !target || idx >= list.length - 1),
    button(ctx.editor.range ? 'Add word in range' : 'Add word at playhead', 'Type the missing word; it fills the selected range or up to 0.4 s from the playhead', () => startAdd(ctx), 'small secondary', !can),
    button('Delete', 'Remove the selected word', () => target && remove(ctx, target.id), 'small secondary', !can || !target),
    button('◀ Prev', 'Previous word', () => { const p = list[idx > 0 ? idx - 1 : 0]; if (p) { st.selected = p.id; ctx.editor.seek(frameOf(p.start, ctx)); } }, 'small secondary', !list.length || idx === 0),
    button('Next ▶', 'Next word', () => { const n = idx < 0 ? list.find(w => w.start * fps(ctx) > ctx.editor.frame) : list[idx + 1]; if (n) { st.selected = n.id; ctx.editor.seek(frameOf(n.start, ctx)); } }, 'small secondary', !list.length || idx >= list.length - 1));
  const exports = el('div', { class: 'mt-row' }, el('span', { class: 'hint', text: 'Export' }),
    list.length ? el('a', { class: 'button small secondary', href: '/jobs/' + ctx.jobId + '/subtitles.srt', download: '', text: 'Export subtitles (.srt) ↓', title: pending ? 'From your pending edits' : 'From words.json' }) : button('Export subtitles (.srt) ↓', 'Transcribe first', null, 'small secondary', true),
    ctx.files.has('words.json') ? el('a', { class: 'button small secondary', href: '/runs/' + ctx.jobId + '/words.json', download: 'words.json', text: 'words.json ↓' }) : null,
    ctx.files.has('mouth-guidance.json') ? el('a', { class: 'button small secondary', href: '/runs/' + ctx.jobId + '/mouth-guidance.json', download: 'mouth-guidance.json', text: 'mouth-guidance.json ↓' }) : null);
  const help = el('p', { class: 'hint', text: running(ctx) ? 'The run is still preparing; the words open when it finishes.' : 'Click a word to select it, double-click to edit its text, drag its edges to fix the timing (snaps to frames, never overlaps a neighbour). Every change is a pending edit (Undo / Redo / Save edits); this run is never changed.' });
  const status = st.status ? el('p', { class: 'line ' + (st.busy ? 'info' : 'ok'), 'aria-live': 'polite', text: st.status }) : null;
  box.replaceChildren(...[help, el('p', { class: 'hint ft-where', text: source }), tRow, problem, status, wRow, eRow, exports].filter(Boolean));
}

// ---------------------------------------------------------------- overlay: the current word as a caption while the track is selected
function drawCanvas(c, box, frame) {
  const ctx = st.ctx; if (!ctx || ctx.editor.selected !== 'words') return;
  const t = (frame + 0.5) / fps(ctx), w = words(ctx).find(x => x.start <= t && t < x.end); if (!w) return;
  const size = Math.max(12, Math.round(box.height * 0.06)); c.font = `600 ${size}px sans-serif`; c.textAlign = 'center'; c.textBaseline = 'bottom';
  c.lineWidth = Math.max(2, size / 6); c.strokeStyle = 'rgba(0,0,0,.85)'; c.fillStyle = '#fff';
  c.strokeText(w.text, box.width / 2, box.height - size * 0.6); c.fillText(w.text, box.width / 2, box.height - size * 0.6);
}

function reset0(ctx) { Object.assign(st, { jobId: ctx.jobId, info: null, infoKey: null, selected: null, drag: null, editing: null, adding: null, busy: false, singing: null, blocksKey: '', status: '' }); }
registerTrack({
  id: 'words', label: 'Words', order: 30, height: 36, markerColor: '#1f18c0',
  available: ctx => ctx.files.has('original.mp4') || ctx.files.has('seedance-input.mp4'),
  mount(row, panel, ctx) {
    if (st.jobId !== ctx.jobId) reset0(ctx);
    st.ctx = ctx; st.panel = el('div', { class: 'mask-track words-track' }); panel.append(st.panel); ensureLayer(row);
    loadInfo(ctx); render();
    window.puppeteer = Object.assign(window.puppeteer || {}, { wordsTrack: { st, words: () => st.ctx && words(st.ctx) } });   // for the console and browser checks
  },
  update(ctx) {
    if (st.jobId !== ctx.jobId) reset0(ctx);
    st.ctx = ctx; loadInfo(ctx); st.blocksKey = st.drag || st.editing || st.adding ? st.blocksKey : ''; render();
  },
  onFrame(frame, ctx) { st.ctx = ctx; if (ctx.editor.playing) return; render(); },
  markers(ctx) { return words(ctx).map(w => frameOf(w.start, ctx)); },
  draw(lane, v) { draw(lane, v); },
  canvas(c, box, frame) { drawCanvas(c, box, frame); },
});
