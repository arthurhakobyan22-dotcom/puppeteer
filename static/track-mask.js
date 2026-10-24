// Mask lane: the ONE mask tool (docs/TIMELINE-SPEC.md §4, §A2; the classic wand was merged into it in the tidy pass).
//
// Clicks on the picture (+ include; Alt-click, right-click or the "− exclude" toggle = exclude) and brush strokes only
// add UNSAVED fixes to the edit layer (layer.mask.points / .strokes); each one previews on its own frame at once
// (POST /jobs/{id}/edits/mask/preview: the free seed step, nothing paid, no new version). "Apply to the clip" sends
// every unsaved fix of every frame in one pass (POST /jobs/{id}/edits/mask/apply) at the quality picked in Tool
// settings: quick (240 px, free, local even for a paid method) or full (480 px; the paid methods show their price on
// the button). After a quick apply, "Accept at full quality" re-runs the same fixes and replaces that entry.
// Level 1: fix type, the fix count, Apply, the flagged frames. Level 2 ("Tool settings", remembered): the method
// (free local · SAM 3 on fal · SAM 2 on Replicate · Brush), the quality, Find hands, Clear all fixes.
// Views: Mask (B/W; your applied fixes once applied) and Overlay (the original with the mask tinted green, level 2).
import { send, getJSON, plain } from './api.js';
import { el, ariaFor, usd, showError, stored, costActions, withCost } from './ui.js';
import { registerTrack } from './timeline.js';

const TOOLS = [['local_propagate', 'Free, local (rougher edges)', false], ['sam3_points_fal', 'SAM 3 on fal · paid', true], ['sam2_points_replicate', 'SAM 2 on Replicate · paid', true], ['brush', 'Brush · paint or erase by hand', false]];
const TINT = { mixBlendMode: 'screen', opacity: '0.8', filter: 'url(#mask-tint)' };
const MASK_VIEWS = ['mask.mp4', 'mask-tint'];
const st = {
  jobId: null, ctx: null, panel: null, mode: 'include', tool: stored('mask-method') || 'local_propagate', quality: stored('mask-quality') || 'quick', brush: { mode: 'paint', radius: 0.03, frames: 5 }, stroke: null,
  previews: new Map(), tokens: new Map(), problems: null, problemsKey: null, busy: '', info: '', estimate: null, estimateKey: '', viewKey: '', lastLatency: null,
};
if (!TOOLS.some(t => t[0] === st.tool)) st.tool = 'local_propagate';
const isBrush = () => st.tool === 'brush';
const applyTool = () => (isBrush() ? 'local_propagate' : st.tool);

// ---------------------------------------------------------------- layer helpers
const value = ctx => { const v = ctx && ctx.edits.layer.mask; return v && typeof v === 'object' ? v : {}; };
const pending = ctx => { const v = value(ctx); return { points: Array.isArray(v.points) ? v.points : [], strokes: Array.isArray(v.strokes) ? v.strokes : [], applied: Array.isArray(v.applied) ? v.applied : [] }; };
const lastApplied = ctx => { const a = pending(ctx).applied; return a.length ? a[a.length - 1] : null; };
const resultKey = ctx => { const a = lastApplied(ctx); return a ? a.result : null; };
const sessionPath = (job, key) => `_sessions/${job}/mask/results/${key}/mask.mp4`;
const pointsOn = (ctx, f) => pending(ctx).points.filter(p => p.frame === f);
const strokesOn = (ctx, f) => pending(ctx).strokes.filter(s => s.frame_from <= f && f <= s.frame_to);
const fixKey = (ctx, f) => JSON.stringify([pointsOn(ctx, f).map(p => [p.x, p.y, p.label]), strokesOn(ctx, f).map(s => [s.mode, s.radius, s.points.length, s.points[0]])]);
const uid = p => p + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
const plural = (n, w, many) => `${n} ${n === 1 ? w : many || w + 's'}`;
const editable = ctx => !!ctx && !(ctx.state.job && ctx.state.job.state === 'running') && (ctx.files.has('clean-masks/mask_00000.png') || ctx.files.has('raw-masks/mask_00000.png'));
const toolInfo = name => TOOLS.find(t => t[0] === name) || TOOLS[0];

function tintFilter() {   // white mask → green, black → nothing (screen blend leaves the picture as is there)
  if (document.getElementById('mask-tint')) return;
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'), filter = document.createElementNS(ns, 'filter'), matrix = document.createElementNS(ns, 'feColorMatrix');
  svg.setAttribute('width', '0'); svg.setAttribute('height', '0'); svg.setAttribute('aria-hidden', 'true'); svg.style.position = 'absolute';
  filter.id = 'mask-tint'; filter.setAttribute('color-interpolation-filters', 'sRGB');
  matrix.setAttribute('type', 'matrix'); matrix.setAttribute('values', '0.1 0 0 0 0  0 0.85 0 0 0  0 0 0.3 0 0  0 0 0 1 0');
  filter.append(matrix); svg.append(filter); document.body.append(svg);
}

// ---------------------------------------------------------------- views: Mask (B/W, session aware) and Overlay
function syncViews(ctx) {
  const key = resultKey(ctx) || '', id = ctx.jobId + '|' + key;
  if (st.viewKey === id && st.viewEditor === ctx.editor) return;   // a re-render of the same run mounts a new editor: add the views to it again
  st.viewKey = id; st.viewEditor = ctx.editor; tintFilter();
  const session = key ? sessionPath(ctx.jobId, key) : null;
  const mask = session ? { src: '/runs/' + session } : { file: 'mask.mp4' };
  const download = session ? '../' + session : 'mask.mp4';
  ctx.editor.addView({ id: 'mask.mp4', label: 'Mask', order: 30, layers: [mask], download, available: c => c.files.has('mask.mp4') || !!key,
    caption: session ? 'Mask with your applied fixes · not saved yet' : 'White where the person is, black elsewhere' });
  ctx.editor.addView({ id: 'mask-tint', label: 'Overlay', order: 45, more: true, layers: [{ file: 'original.mp4' }, { ...mask, style: TINT }], download, available: c => c.files.has('original.mp4') && (c.files.has('mask.mp4') || !!key),
    caption: session ? 'Original with your edited mask as a green overlay · not saved yet' : 'Original with the mask as a green overlay' });
  if (MASK_VIEWS.includes(ctx.editor.view)) ctx.editor.setView(ctx.editor.view);
}

// ---------------------------------------------------------------- flagged frames (ticks + area sparkline)
async function loadProblems(ctx, force = false) {
  const key = ctx.jobId + '|' + (resultKey(ctx) || '');
  if (!force && st.problemsKey === key) return;
  st.problemsKey = key;
  try { const body = await getJSON('/jobs/' + ctx.jobId + '/mask/problems'); if (st.problemsKey === key && st.jobId === ctx.jobId) { st.problems = body; render(); ctx.editor.redraw(); } }
  catch (e) { if (st.problemsKey === key) { st.problems = { frames: [], areas: [], flagged: [], failed: true }; showError(e, { key: 'mask-problems' }); } }
}
const ticks = () => [...new Set(((st.problems && st.problems.frames) || []).map(p => p.frame))].sort((a, b) => a - b);

// ---------------------------------------------------------------- previews (one frame, nothing else)
async function preview(ctx, frame, t0 = null) {
  const points = pointsOn(ctx, frame), strokes = strokesOn(ctx, frame), key = fixKey(ctx, frame);
  if (!points.length && !strokes.length) { st.previews.delete(frame); ctx.editor.redraw(); return; }
  const have = st.previews.get(frame); if (have && have.key === key && t0 == null) return;
  const token = (st.tokens.get(frame) || 0) + 1; st.tokens.set(frame, token);
  try {
    const r = await send('/jobs/' + ctx.jobId + '/edits/mask/preview', { frame, points: points.map(({ frame, x, y, label }) => ({ frame, x, y, label })), strokes: strokes.map(({ frame_from, frame_to, mode, points, radius }) => ({ frame_from, frame_to, mode, points, radius })) });
    if (st.tokens.get(frame) !== token || st.jobId !== ctx.jobId) return;
    const img = new Image();
    img.onload = () => {
      if (st.tokens.get(frame) !== token) return;
      st.previews.set(frame, { key, img, selections: r.selections });
      if (t0 != null) { st.lastLatency = (performance.now() - t0) / 1000; st.info = `Frame ${frame}: ` + r.selections.map(s => (s.mode === 'include' ? 'adds ' : 'removes ') + (s.fraction * 100).toFixed(1) + '% of the frame').join(' · ') + '. This frame only; apply to follow it through the clip.'; render(); }
      ctx.editor.redraw();
    };
    img.onerror = () => { if (st.tokens.get(frame) === token) showError(new Error('The preview picture could not be loaded.'), { key: 'mask-track' }); };
    img.src = r.url;
  } catch (e) { if (st.tokens.get(frame) === token) showError(e, { key: 'mask-track' }); }
}

// ---------------------------------------------------------------- unsaved fixes (edit layer commits)
function commitMask(ctx, label, fn) {
  return ctx.edits.commit(label, 'mask', d => { const v = d && typeof d === 'object' ? d : {}; v.points = v.points || []; v.strokes = v.strokes || []; v.applied = v.applied || []; fn(v); return v; });
}
function addPoint(ctx, pt, exclude) {
  const t0 = performance.now(), p = { id: uid('p'), frame: pt.frame, x: Number(pt.x.toFixed(4)), y: Number(pt.y.toFixed(4)), label: exclude ? 0 : 1, t: Date.now() };
  commitMask(ctx, `Add ${exclude ? '−' : '+'} fix on frame ${p.frame}`, v => { v.points.push(p); });
  preview(ctx, p.frame, t0); render();
}
function addStroke(ctx, s) {
  const t0 = performance.now(), stroke = { id: uid('s'), ...s, t: Date.now() };
  commitMask(ctx, `Add brush ${s.mode} on frames ${s.frame_from}–${s.frame_to}`, v => { v.strokes.push(stroke); });
  preview(ctx, ctx.editor.frame, t0); render();
}
function removeItem(ctx, item) {
  const isStroke = 'frame_from' in item;
  commitMask(ctx, isStroke ? `Remove brush stroke on frames ${item.frame_from}–${item.frame_to}` : `Remove fix on frame ${item.frame}`, v => { if (isStroke) v.strokes = v.strokes.filter(s => s.id !== item.id); else v.points = v.points.filter(p => p.id !== item.id); });
  st.previews.delete(isStroke ? ctx.editor.frame : item.frame); preview(ctx, ctx.editor.frame); render();
}
function undoLast(ctx) {
  const { points, strokes } = pending(ctx); const all = [...points, ...strokes].sort((a, b) => (a.t || 0) - (b.t || 0));
  if (all.length) removeItem(ctx, all[all.length - 1]);
}
function clearAll(ctx) { commitMask(ctx, 'Clear the unsaved mask fixes', v => { v.points = []; v.strokes = []; }); st.previews.clear(); ctx.editor.redraw(); render(); }

// ---------------------------------------------------------------- Apply to the clip, Accept at full quality, Find hands
async function apply(ctx, quality, { replace = null, tool = applyTool(), confirm = false } = {}) {
  await ctx.edits.queue;
  if (st.busy) return false;
  st.busy = replace ? 'Running the same fixes at full quality…' : quality === 'quick' ? 'Applying to the clip (quick)…' : 'Applying to the clip at full quality…'; render();
  const t0 = performance.now();
  try {
    const body = { quality, tool, rev: ctx.edits.rev }; if (replace) body.replace = replace; if (confirm) body.confirm_cost = 'true';
    const r = await send('/jobs/' + ctx.jobId + '/edits/mask/apply', body);
    st.busy = ''; st.previews.clear(); await ctx.edits.load();
    const a = r.apply, secs = ((performance.now() - t0) / 1000).toFixed(1);
    st.info = `${replace ? 'Accepted at full quality' : 'Applied'} in ${secs} s: ${plural(a.frames_changed, 'frame')} of the mask changed${a.reused ? ' (same fixes as before, reused)' : ''}. The Mask and Overlay views show it; nothing is saved until "Save as new version".`;
    if (!MASK_VIEWS.includes(ctx.editor.view)) ctx.editor.setView('mask-tint');
    return true;
  } catch (e) {
    st.busy = ''; const p = plain(e);
    showError(e, { key: 'mask-track', actions: costActions(e, () => apply(ctx, quality, { replace, tool, confirm: true })) });
    if (p.status === 409) await ctx.edits.load();
    return false;
  } finally { st.busy = ''; render(); }
}
async function findHands(ctx, source) {
  await ctx.edits.queue;
  if (st.busy) return;
  const r0 = ctx.editor.range, body = { source, rev: ctx.edits.rev };
  if (source === 'range') { if (!r0) return; body.from = r0.from; body.to = r0.to; }
  st.busy = 'Looking for hands on the ' + (source === 'range' ? `selected frames ${r0.from}–${r0.to}` : 'flagged frames') + '…'; render();
  const t0 = performance.now();
  try {
    const r = await send('/jobs/' + ctx.jobId + '/edits/mask/hands', body);
    st.busy = ''; st.previews.clear(); await ctx.edits.load();
    const h = r.hands; st.info = `Find hands (${((performance.now() - t0) / 1000).toFixed(1)} s): hands found on ${plural(h.hands_on.length, 'frame')} of ${h.frames.length}, ${plural(h.frames_changed, 'frame')} changed. Only those frames were touched; unsaved fixes still apply on top.`;
    if (!MASK_VIEWS.includes(ctx.editor.view)) ctx.editor.setView('mask-tint');
  } catch (e) { st.busy = ''; showError(e, { key: 'mask-track' }); if (plain(e).status === 409) await ctx.edits.load(); }
  finally { st.busy = ''; render(); }
}
async function refreshEstimate(ctx) {   // the paid methods show their price on the button before anything runs
  const { points } = pending(ctx), last = lastApplied(ctx);
  const paidTool = toolInfo(applyTool())[2], acceptPaid = last && last.quality === 'quick' && last.intended_tool;
  const key = [ctx.jobId, applyTool(), st.quality, points.map(p => p.id).join(','), acceptPaid ? last.id : ''].join('|');
  if (st.estimateKey === key) return;
  st.estimateKey = key; st.estimate = null;
  const ask = async body => { try { return await send('/jobs/' + ctx.jobId + '/edits/mask/apply', { ...body, estimate_only: 'true' }); } catch (e) { return { error: plain(e).message }; } };
  const out = {};
  if (paidTool && points.length && st.quality === 'full') out.apply = await ask({ quality: 'full', tool: applyTool() });
  if (acceptPaid) out.accept = await ask({ quality: 'full', replace: last.id, tool: last.intended_tool });
  if (st.estimateKey === key) { st.estimate = out; render(); }
}

async function quietSave(work) {   // "Apply now" / "Save without them": the save moves the session folder, so load nothing from it meanwhile
  st.saving = true; let child = null;
  try { child = await work(); } finally {
    st.saving = false;
    if (!child && st.ctx) { syncViews(st.ctx); loadProblems(st.ctx); render(); }   // still on this run (refused or failed): catch up
  }
}

// ---------------------------------------------------------------- panel
const button = (text, title, onclick, cls = 'sm', disabled = false) => el('button', { type: 'button', class: cls, text, title, 'aria-label': ariaFor(text, title), onclick, disabled });
const seg = (items, value, onPick, label) => el('div', { class: 'seg-ctl', role: 'group', 'aria-label': label }, items.map(([v, text, cls]) => el('button', { type: 'button', class: (v === value ? 'on ' : '') + (cls || ''), text, 'aria-pressed': v === value ? 'true' : 'false', onclick: () => onPick(v) })));
function render() {
  const ctx = st.ctx, box = st.panel; if (!ctx || !box) return;
  const ed = ctx.editor, can = editable(ctx), busy = !!st.busy, { points, strokes, applied } = pending(ctx), n = points.length + strokes.length;
  const tool = toolInfo(applyTool()), est = st.estimate || {}, last = lastApplied(ctx), brush = isBrush();
  const help = el('p', { class: 'hint', text: can ? (brush ? 'Draw on the picture to paint (green) or erase (red); the stroke covers this frame and the next ones. ' : 'Click on the picture: + adds what you click (a missed hand, a prop), − removes spill. ') + 'Each fix shows on its frame at once; nothing is sent or saved until you apply.' : 'Mask fixes need a finished motion clip with masks.' });
  // level 1: fix type (or brush controls), fixes, apply, flagged frames
  const fixRow = el('div', { class: 'mt-row' });
  if (brush) fixRow.append(seg([['paint', 'Paint'], ['erase', 'Erase', 'minus']], st.brush.mode, v => { st.brush.mode = v; render(); }, 'Brush mode'),
    el('label', { class: 'wand-inline' }, 'radius ', (() => { const r = el('input', { type: 'range', min: '0.005', max: '0.15', step: '0.005', 'aria-label': 'Brush radius' }); r.value = String(st.brush.radius); r.oninput = () => { st.brush.radius = Number(r.value); }; return r; })()),
    el('label', { class: 'wand-inline' }, 'on ', (() => { const i = el('input', { type: 'number', min: '1', max: '500', step: '1', 'aria-label': 'Frames the stroke covers' }); i.value = String(st.brush.frames); i.onchange = () => { st.brush.frames = Math.max(1, Math.round(Number(i.value) || 1)); }; return i; })(), ' frames from here'));
  else fixRow.append(seg([['include', '+ include'], ['exclude', '− exclude', 'minus']], st.mode, v => { st.mode = v; render(); }, 'What a click on the picture does'), el('span', { class: 'hint', text: 'Alt-click = exclude' }));
  const rows = [...points.map(p => ({ ...p, sort: p.frame, text: `frame ${p.frame} · ${p.label ? '+ include' : '− exclude'}` })), ...strokes.map(s => ({ ...s, sort: s.frame_from, text: `frames ${s.frame_from}–${s.frame_to} · brush ${s.mode}` }))].sort((a, b) => a.sort - b.sort || (a.t || 0) - (b.t || 0));
  const list = el('ul', { class: 'mt-list', 'aria-label': 'Unsaved mask fixes' }, rows.map(r => el('li', { class: ed.frame === r.sort ? 'here' : '' },
    el('button', { type: 'button', class: 'mt-jump', title: 'Go to this frame', text: r.text, onclick: () => ed.seek(r.sort) }),
    el('button', { type: 'button', class: 'mt-del', title: 'Remove this fix', 'aria-label': 'Remove ' + r.text, text: '✕', disabled: busy, onclick: () => removeItem(ctx, r) }))));
  const frames = new Set(points.map(p => p.frame));
  const pendingRow = el('div', { class: 'mt-row' }, el('strong', { text: n ? `${plural(n, 'unsaved fix', 'unsaved fixes')}` + (points.length ? ` (${plural(points.length, 'click')} on ${plural(frames.size, 'frame')})` : '') : 'No fixes yet' }),
    button('Undo last', 'Remove the newest fix', () => undoLast(ctx), 'ghost sm', !n || busy));
  const paid = tool[2] && st.quality === 'full';
  const applyLabel = paid ? ['Apply with ' + tool[1].split(' · ')[0], est.apply && est.apply.estimated_cost_usd != null ? usd(est.apply.estimated_cost_usd) : est.apply && est.apply.error ? 'price unknown' : 'working out the price…'] : ['Apply to the clip', st.quality === 'quick' ? 'free · quick' : 'free'];
  const applyButton = el('button', { type: 'button', class: 'primary', title: paid ? 'The price on this button is the confirmation: clicking sends it.' : st.quality === 'quick' ? 'Every unsaved fix of every frame in one pass at a low working size (240 px); free and local' : 'Every unsaved fix in one pass at full working size (480 px)', disabled: !n || busy || !can || (paid && !(est.apply && est.apply.estimated_cost_usd != null)), onclick: () => apply(ctx, st.quality, { confirm: paid }) });
  withCost(applyButton, busy ? st.busy : applyLabel[0], busy ? '' : applyLabel[1]);
  const applyRow = el('div', { class: 'mt-row' }, applyButton, n ? null : el('span', { class: 'reason', text: can ? 'Click the picture to add a fix first.' : '' }));
  const acceptRow = last && last.kind !== 'hands' && last.quality === 'quick' ? el('div', { class: 'mt-row mt-accept' },
    el('span', { class: 'hint', text: `Quick result shown (${plural(last.frames_changed || 0, 'frame')} changed).` }),
    (() => { const paid2 = !!last.intended_tool, e2 = est.accept; const b = button('', paid2 ? 'Runs the same fixes with ' + toolInfo(last.intended_tool)[1] + '; the price on this button is the confirmation.' : 'Runs the same fixes at full quality and replaces this result', () => apply(ctx, 'full', { replace: last.id, tool: last.intended_tool || 'local_propagate', confirm: paid2 }), 'sm', busy || (paid2 && !(e2 && e2.estimated_cost_usd != null)));
      withCost(b, 'Accept at full quality', paid2 ? (e2 && e2.estimated_cost_usd != null ? usd(e2.estimated_cost_usd) : 'working out the price…') : 'free'); return b; })()) : null;
  const tk = ticks(), prob = st.problems, here = prob && (prob.frames || []).filter(p => p.frame === ed.frame);
  const prevTick = tk.slice().reverse().find(f => f < ed.frame), nextTick = tk.find(f => f > ed.frame);
  const flagged = (prob && prob.flagged) || [];
  const problemRow = el('div', { class: 'mt-row' }, el('span', { class: 'mt-ticks', text: !prob ? 'Checking the mask…' : prob.failed ? 'The mask could not be checked.' : tk.length ? `${plural(flagged.length, 'flagged frame')} in ${plural(tk.length, 'place')}` : 'No flagged frames' }),
    button('◀ Prev', 'Previous flagged frame ([)', () => ed.seek(prevTick), 'ghost sm', prevTick == null), button('Next ▶', 'Next flagged frame (])', () => ed.seek(nextTick), 'ghost sm', nextTick == null));
  // level 2: tool settings
  const select = el('select', { 'aria-label': 'Method' }); for (const [name, label] of TOOLS) select.append(el('option', { value: name, text: label })); select.value = st.tool;
  select.onchange = () => { st.tool = select.value; stored('mask-method', st.tool); st.stroke = null; refreshEstimate(ctx); render(); ed.redraw(); };
  const qualitySeg = seg([['quick', 'Quick preview · 240 px'], ['full', 'Full · 480 px']], st.quality, v => { st.quality = v; stored('mask-quality', v); refreshEstimate(ctx); render(); }, 'Apply quality');
  const settings = el('details', { class: 'more', dataset: { remember: 'mask-settings' } }, el('summary', {}, 'Tool settings', el('span', { class: 'hint', text: tool[1].split(' · ')[0] + ' · ' + (st.quality === 'quick' ? 'quick' : 'full') })),
    el('div', { class: 'body' },
      el('label', { class: 'lbl' }, 'Method', select, el('span', { class: 'hint', text: 'How the fix is followed through the clip. The paid methods show their price on the Apply button when the quality is Full; quick applies are always free and local.' })),
      el('label', { class: 'lbl' }, 'Quality', qualitySeg),
      el('div', { class: 'mt-row' },
        button('Find hands on flagged frames · free', 'Finds hands with the local model on the flagged frames only and adds them to the mask', () => findHands(ctx, 'problems'), 'sm', busy || !can || !flagged.length),
        button(ed.range ? `Find hands on ${ed.range.from}–${ed.range.to} · free` : 'Find hands on a range · free', ed.range ? 'Finds hands on the selected frames only' : 'Drag across the ruler to select frames first', () => findHands(ctx, 'range'), 'sm', busy || !can || !ed.range),
        button('Clear all fixes', 'Remove every unsaved fix', () => clearAll(ctx), 'ghost sm', !n || busy)),
      applied.length ? el('p', { class: 'hint', text: `${plural(applied.length, 'applied step')} so far: ` + applied.map(a => a.kind === 'hands' ? `hands on ${plural((a.hands_on || []).length, 'frame')}` : `${plural((a.points || []).length + (a.strokes || []).length, 'fix', 'fixes')} (${a.quality})`).join(' → ') }) : null));
  const saved = (() => { try { return localStorage.getItem('pp-open-mask-settings'); } catch { return null; } })(); if (saved === '1') settings.open = true;
  settings.addEventListener('toggle', () => { try { localStorage.setItem('pp-open-mask-settings', settings.open ? '1' : '0'); } catch { /* private mode */ } });
  const notes = here && here.length ? el('p', { class: 'line warn mt-note', text: 'Frame ' + ed.frame + ': ' + here.map(p => p.note).join('; ') + '.' }) : null;
  const info = st.info ? el('p', { class: 'hint mt-info', 'aria-live': 'polite', text: st.info }) : null;
  box.replaceChildren(...[help, fixRow, pendingRow, rows.length ? list : null, applyRow, acceptRow, problemRow, notes, settings, info].filter(Boolean));
  if (st.busy) box.querySelectorAll('button').forEach(b => { if (!b.classList.contains('mt-jump')) b.disabled = true; });
}

// ---------------------------------------------------------------- overlay drawing
function drawFixes(c, box, frame) {
  const ctx = st.ctx; if (!ctx) return;
  const W = box.width, H = box.height, r = Math.max(5 * box.dpr, W * 0.011);
  const p = st.previews.get(frame);
  if (p && p.img.complete && p.key === fixKey(ctx, frame)) c.drawImage(p.img, 0, 0, W, H);
  const strokes = [...strokesOn(ctx, frame), ...(st.stroke && st.stroke.frame_from === frame ? [st.stroke] : [])];
  for (const s of strokes) {
    c.lineCap = 'round'; c.lineJoin = 'round'; c.lineWidth = Math.max(2, s.radius * 2 * H); c.strokeStyle = s.mode === 'erase' ? 'rgba(230,60,50,.45)' : 'rgba(40,200,80,.45)';
    c.beginPath(); s.points.forEach(([x, y], i) => (i ? c.lineTo(x * W, y * H) : c.moveTo(x * W, y * H))); if (s.points.length === 1) c.lineTo(s.points[0][0] * W + 0.01, s.points[0][1] * H); c.stroke();
  }
  for (const q of pointsOn(ctx, frame)) {
    c.beginPath(); c.arc(q.x * W, q.y * H, r, 0, Math.PI * 2); c.fillStyle = q.label ? 'rgba(40,200,80,.9)' : 'rgba(230,60,50,.9)'; c.fill(); c.lineWidth = 2 * box.dpr; c.strokeStyle = '#fff'; c.stroke();
    c.fillStyle = '#fff'; c.font = 'bold ' + Math.round(r * 1.4) + 'px sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText(q.label ? '+' : '−', q.x * W, q.y * H + 1);
  }
}

// ---------------------------------------------------------------- the lane
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
registerTrack({
  id: 'mask', label: 'Mask', hint: 'what a fix needs, nothing else', order: 10, height: 44, markerColor: '--lane-mask',
  available: ctx => ctx.files.has('mask.mp4') || ctx.files.has('mask-cleanup-report.json'),
  mount(row, panel, ctx) {
    st.ctx = ctx; st.panel = el('div', { class: 'mask-track' }); panel.append(st.panel);
    if (st.jobId !== ctx.jobId) Object.assign(st, { jobId: ctx.jobId, previews: new Map(), tokens: new Map(), problems: null, problemsKey: null, info: '', estimate: null, estimateKey: '', viewKey: '', saving: false });
    (ctx.edits.saveChecks = ctx.edits.saveChecks || {}).mask = () => {   // same wording as MaskTrack.check() on the server
      const { points, strokes } = pending(st.ctx); if (!points.length && !strokes.length) return null;
      const what = [points.length ? plural(points.length, 'mask click') : '', strokes.length ? plural(strokes.length, 'brush stroke') : ''].filter(Boolean).join(' and ');
      const one = points.length + strokes.length === 1, them = one ? 'it' : 'them';
      return { message: `${what} ${one ? 'is' : 'are'} not applied yet. Apply ${them} to the clip first, or remove ${them}.`, fix: `Use "Apply now" to follow ${them} through the clip, or "Save without ${them}" to drop ${them}.` };
    };
    ctx.edits.saveActions.mask = () => [
      { label: 'Apply now', run: () => quietSave(async () => (await apply(st.ctx, 'full', { tool: 'local_propagate' })) && st.ctx.edits.save()) },
      { label: pending(st.ctx).points.length + pending(st.ctx).strokes.length === 1 ? 'Save without it' : 'Save without them', secondary: true, run: () => quietSave(async () => { await commitMask(st.ctx, 'Drop the unapplied mask fixes', v => { v.points = []; v.strokes = []; }); await st.ctx.edits.queue; return st.ctx.edits.save(); }) },
    ];
    ctx.editor.on('range', () => render());
    syncViews(ctx); loadProblems(ctx); render();
  },
  update(ctx) {
    if (st.jobId !== ctx.jobId) Object.assign(st, { jobId: ctx.jobId, previews: new Map(), tokens: new Map(), problems: null, problemsKey: null, info: '', estimate: null, estimateKey: '', viewKey: '', saving: false });
    st.ctx = ctx;
    if (!st.saving) { syncViews(ctx); loadProblems(ctx); refreshEstimate(ctx); }   // "Apply now" + save: the session folder moves into the record, so load nothing from it meanwhile
    render();
  },
  onFrame(frame, ctx) { st.ctx = ctx; if (ctx.editor.playing) return; preview(ctx, frame); render(); },   // no DOM work per frame during playback
  markers(ctx) { const { points, strokes } = pending(ctx); return [...new Set([...points.map(p => p.frame), ...strokes.map(s => s.frame_from), ...ticks()])].sort((a, b) => a - b); },
  draw(lane, v) {
    const c = v.ctx2d, prob = st.problems, areas = (prob && prob.areas) || [], accent = css('--lane-mask') || css('--accent') || '#7cc4ff', ok = css('--ok') || '#6fd39a', danger = css('--danger') || '#ff7b72', muted = css('--muted') || '#9aa1b0';
    if (!areas.length) { c.fillStyle = muted; c.font = '11px sans-serif'; c.textBaseline = 'middle'; c.fillText(prob && prob.failed ? 'The mask could not be checked' : prob ? 'No masks in this run' : 'Checking the mask…', 8, v.height / 2); return; }
    const first = Math.max(0, v.frameAt(0)), last = Math.min(areas.length - 1, v.frameAt(v.width) + 1), H = v.height - 10, max = Math.max(1, ...areas);
    c.save(); c.globalAlpha = 0.12; c.fillStyle = danger;
    for (const p of prob.frames || []) { const x0 = v.x(p.span[0]), x1 = v.x(p.span[1] + 1); if (x1 >= 0 && x0 <= v.width) c.fillRect(x0, 8, x1 - x0, v.height - 8); }
    c.restore();
    c.beginPath(); c.moveTo(v.x(first), v.height);
    for (let f = first; f <= last; f++) { const y = v.height - 2 - ((areas[f] || 0) / max) * H; c.lineTo(v.x(f), y); c.lineTo(v.x(f + 1), y); }
    c.lineTo(v.x(last + 1), v.height); c.closePath(); c.save(); c.globalAlpha = 0.16; c.fillStyle = resultKey(st.ctx) ? ok : accent; c.fill(); c.restore(); c.strokeStyle = resultKey(st.ctx) ? ok : accent; c.lineWidth = 1.2; c.stroke();
    c.fillStyle = danger;
    for (const f of ticks()) { const x = v.x(f); if (x < -2 || x > v.width + 2) continue; c.fillRect(Math.round(x), 8, Math.max(1.5, Math.min(3, v.pxPerFrame)), v.height - 8); }
    const { points, strokes } = pending(st.ctx); c.fillStyle = accent;
    for (const f of new Set([...points.map(p => p.frame), ...strokes.map(s => s.frame_from)])) { const x = v.x(f) + v.pxPerFrame / 2; if (x < -6 || x > v.width + 6) continue; c.beginPath(); c.arc(x, v.height - 6, 3.5, 0, Math.PI * 2); c.fill(); }
  },
  canvas(c, box, frame) { drawFixes(c, box, frame); },
  pointer: {
    down(e, pt) {
      const ctx = st.ctx; if (!editable(ctx) || st.busy) return;
      if (isBrush()) { st.stroke = { frame_from: pt.frame, frame_to: Math.min(ctx.editor.frames - 1, pt.frame + Math.max(1, st.brush.frames) - 1), mode: st.brush.mode, points: [[Number(pt.x.toFixed(4)), Number(pt.y.toFixed(4))]], radius: st.brush.radius }; ctx.editor.redraw(); return; }
      addPoint(ctx, pt, e.altKey || e.button === 2 || st.mode === 'exclude');
    },
    move(e, pt) {
      if (!st.stroke) return;
      const last = st.stroke.points[st.stroke.points.length - 1];
      if (Math.hypot(pt.x - last[0], pt.y - last[1]) > 0.004) { st.stroke.points.push([Number(pt.x.toFixed(4)), Number(pt.y.toFixed(4))]); st.ctx.editor.redraw(); }
    },
    up() { if (!st.stroke) return; const s = st.stroke; st.stroke = null; addStroke(st.ctx, s); },
  },
});
