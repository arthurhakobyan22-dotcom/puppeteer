// World stage (Agent 1): set plates / look images (runs/_assets), the Background row on the composite card, and the
// Set / Look / Light slots panel in the draft step (slots.json via GET/PUT /jobs/{id}/slots). Agents 2 and 3 mount the
// prompt builder and the generator picker into [data-slot=prompt-builder] / [data-slot=generator] inside tpl-slots.
import { api, plain, getJSON, send } from './api.js';
import { $, el, showError, notice, tpl } from './ui.js';
import { state, navigate, hrefFor } from './state.js';

export const BACKGROUNDS = [
  ['original', 'Original frames', 'The depth person over the real frames (today’s output).'],
  ['full_depth', 'Full depth', 'The whole frame is the depth video.'],
  ['plain', 'Plain colour', 'A flat black or gray background.'],
  ['set_image', 'Set image', 'A set plate behind the person, fitted to the frame.'],
];
export const BACKGROUND_LABEL = Object.fromEntries(BACKGROUNDS.map(b => [b[0], b[1]]));
export const BACKGROUND_PARAMS = ['background', 'plain_color', 'set_image', 'set_fit'];
export const SET_MODES = [
  ['original', 'Original', 'Keep the room as it is in the clip.'],
  ['original_depth', 'Depth only', 'Keep the room’s geometry as depth and regenerate its look (needs the Full depth background).'],
  ['set_ref', 'Set reference', 'Attach a set image as a reference (@ImageN, set fence).'],
  ['prompt', 'Described', 'Say what the set is in words.'],
  ['true_swap', 'True swap', 'The set image is composited behind the person (needs the Set image background).'],
];
export const LOOK_MODES = [
  ['follow', 'Follow the references', 'The references decide the look.'],
  ['style_ref', 'Style image', 'A style image defines palette, grain and contrast (@ImageN, look fence).'],
  ['prompt', 'Described', 'Say what the rendering style is in words.'],
];
const BACKGROUND_FOR = { original_depth: 'full_depth', true_swap: 'set_image' };
const FIT_DEFAULT = { x: 0, y: 0, scale: 1 };

/** Same maths as stages/plates.py fit_rect: cover the frame (scale to fill, centred), then fit.scale around the centre and fit.x / fit.y as frame fractions. */
export function fitRect(plateW, plateH, frameW, frameH, fit) {
  const f = parseFit(fit);
  const s = Math.max(frameW / plateW, frameH / plateH) * f.scale, w = plateW * s, h = plateH * s;
  return { x: (frameW - w) / 2 + f.x * frameW, y: (frameH - h) / 2 + f.y * frameH, w, h };
}
export function parseFit(value) {
  let data = value;
  if (typeof value === 'string') { try { data = value.trim() ? JSON.parse(value) : {}; } catch { data = {}; } }
  if (!data || typeof data !== 'object') data = {};
  const n = (v, d) => (Number.isFinite(Number(v)) && v !== null && v !== '' ? Number(v) : d);
  return { x: Math.max(-1, Math.min(1, n(data.x, 0))), y: Math.max(-1, Math.min(1, n(data.y, 0))), scale: Math.max(0.2, Math.min(5, n(data.scale, 1))) };
}
const fitText = fit => { const f = parseFit(fit); return f.x === 0 && f.y === 0 && f.scale === 1 ? '' : JSON.stringify({ scale: +f.scale.toFixed(4), x: +f.x.toFixed(4), y: +f.y.toFixed(4) }); };

// ---------------------------------------------------------------- assets

let assetCache = null;
export async function loadAssets(force = false) {
  if (assetCache && !force) return assetCache;
  try { assetCache = (await getJSON('/assets')).assets || []; } catch { assetCache = assetCache || []; }
  return assetCache;
}

/** Upload one image into the asset store; returns {name, width, height, url, …}. */
export async function uploadAsset(file, kind) {
  const data = new FormData(); data.set('file', file); data.set('kind', kind);
  const meta = await send('/jobs/' + state.jobId + '/assets', data);
  assetCache = [meta, ...(assetCache || []).filter(a => a.name !== meta.name)];
  return meta;
}

/** A picker: the stored images of `kind` as thumbnails plus an upload input. `onChange(name|null, meta)` on every choice. */
export function assetPicker({ kind, value, label, onChange }) {
  const grid = el('div', { class: 'asset-grid', role: 'listbox', 'aria-label': label || kind + ' images' });
  const input = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', 'aria-label': 'Upload a ' + (kind === 'look' ? 'style image' : 'set plate') });
  const status = el('span', { class: 'hint' });
  const node = el('div', { class: 'asset-picker' }, grid, el('div', { class: 'row' }, el('label', { class: 'button small secondary asset-upload' }, 'Upload image…', input), status));
  let current = value || null;
  function draw(assets) {
    grid.replaceChildren();
    const mine = assets.filter(a => !kind || a.kind === kind || a.name === current);
    if (!mine.length) grid.append(el('span', { class: 'hint', text: 'No ' + (kind === 'look' ? 'style images' : 'set plates') + ' yet. Upload a PNG, JPEG or WebP (up to 30 MB).' }));
    for (const a of mine) {
      const b = el('button', { type: 'button', class: 'asset' + (a.name === current ? ' active' : ''), role: 'option', 'aria-selected': a.name === current ? 'true' : 'false', title: a.filename + ' · ' + a.width + '×' + a.height,
        onclick: () => { current = a.name === current ? null : a.name; draw(assets); onChange(current, current ? a : null); } },
        el('img', { src: a.url, alt: a.filename }), el('span', { text: a.filename }));
      grid.append(b);
    }
  }
  loadAssets().then(draw);
  input.onchange = async () => {
    const file = input.files && input.files[0]; if (!file) return;
    status.textContent = 'Uploading…';
    try { const meta = await uploadAsset(file, kind); current = meta.name; status.textContent = ''; draw(await loadAssets()); onChange(current, meta); }
    catch (e) { status.textContent = ''; showError(e, { key: 'asset-' + kind }); }
    finally { input.value = ''; }
  };
  return { node, set(name) { current = name || null; loadAssets().then(draw); }, get() { return current; } };
}

// ---------------------------------------------------------------- Background row (composite card, Studio)

/** Draws the Background controls into `box` for the depth_cutout tool: the four choices, the plain colour, the set-plate
 *  picker and a canvas with the plate under the first frame (drag = move, slider = scale). `params` is the card's live
 *  param object; `set(name, value)` is the card's setter (it resets the estimate). */
export function backgroundControls(box, { tool, params, set, jobId }) {
  const spec = tool.params || {};
  const value = name => (params[name] !== undefined && params[name] !== null ? params[name] : (spec[name] || {}).default);
  const current = { background: value('background') || 'original', plain_color: value('plain_color') || 'black', set_image: value('set_image') || '', fit: parseFit(value('set_fit')) };
  const choice = el('select', { 'aria-label': 'Background' });
  for (const [name, label, hint] of BACKGROUNDS) choice.append(el('option', { value: name, text: label + ' · ' + hint }));
  choice.value = current.background;
  const plain = el('select', { 'aria-label': 'Plain colour' }); for (const c of ['black', 'gray']) plain.append(el('option', { value: c, text: c })); plain.value = current.plain_color;
  const plainRow = el('label', { class: 'field' }, 'Plain colour', plain);
  const canvas = el('canvas', { class: 'bg-canvas', width: 480, height: 270, 'aria-label': 'Set plate position preview: drag to move' });
  const scale = el('input', { type: 'range', min: '0.2', max: '3', step: '0.01', 'aria-label': 'Set plate scale' }); scale.value = String(current.fit.scale);
  const fitLine = el('span', { class: 'hint' });
  const reset = el('button', { type: 'button', class: 'small secondary', text: 'Centre & cover' });
  const picker = assetPicker({ kind: 'set', value: current.set_image, label: 'Set plates', onChange: name => { current.set_image = name || ''; set('set_image', current.set_image); draw(); } });
  const plateRow = el('div', { class: 'bg-plate' }, picker.node, canvas, el('div', { class: 'row' }, el('label', { class: 'field', style: 'flex:1 1 160px' }, 'Scale', scale), reset), fitLine);
  box.append(el('label', { class: 'field' }, 'Background', choice, el('span', { class: 'hint', text: (spec.background || {}).hint || '' })), plainRow, plateRow);

  let frame = null, plate = null;
  const frameImage = new Image(); frameImage.onload = () => { frame = frameImage; fitCanvas(); draw(); }; frameImage.onerror = () => { frame = null; draw(); };
  frameImage.src = '/jobs/' + jobId + '/mask/frame?i=0';
  const plateImage = new Image(); plateImage.onload = () => { plate = plateImage; draw(); }; plateImage.onerror = () => { plate = null; draw(); };
  function fitCanvas() { if (frame && frame.naturalWidth) { const w = Math.min(480, frame.naturalWidth); canvas.width = w; canvas.height = Math.round(w * frame.naturalHeight / frame.naturalWidth); } }
  function draw() {
    const want = current.set_image ? '/assets/' + current.set_image : '';
    if (want && plateImage.dataset.src !== want) { plateImage.dataset.src = want; plate = null; plateImage.src = want; }
    const ctx = canvas.getContext('2d'); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (plate && plate.naturalWidth) { const r = fitRect(plate.naturalWidth, plate.naturalHeight, canvas.width, canvas.height, current.fit); ctx.drawImage(plate, r.x, r.y, r.w, r.h); }
    if (frame && frame.naturalWidth) { ctx.globalAlpha = 0.45; ctx.drawImage(frame, 0, 0, canvas.width, canvas.height); ctx.globalAlpha = 1; }
    const f = current.fit;
    fitLine.textContent = current.set_image ? `Plate covers the frame, centred; moved ${(f.x * 100).toFixed(0)}% / ${(f.y * 100).toFixed(0)}%, scale ×${f.scale.toFixed(2)}. Drag the picture to move it. The first frame is shown half transparent over the plate; the person is cut out at full quality when it runs.` : 'Pick or upload a set plate; it is fitted to cover the frame and the person is placed over it.';
  }
  function show() {
    plainRow.hidden = current.background !== 'plain'; plateRow.hidden = current.background !== 'set_image';
  }
  function commitFit() { set('set_fit', fitText(current.fit)); draw(); }
  choice.onchange = () => { current.background = choice.value; set('background', current.background); show(); draw(); };
  plain.onchange = () => { current.plain_color = plain.value; set('plain_color', current.plain_color); };
  scale.oninput = () => { current.fit.scale = Number(scale.value); draw(); }; scale.onchange = commitFit;
  reset.onclick = () => { current.fit = { ...FIT_DEFAULT }; scale.value = '1'; commitFit(); };
  let drag = null;
  canvas.onpointerdown = e => { drag = { x: e.clientX, y: e.clientY, fx: current.fit.x, fy: current.fit.y }; canvas.setPointerCapture(e.pointerId); };
  canvas.onpointermove = e => { if (!drag) return; const r = canvas.getBoundingClientRect(); current.fit.x = Math.max(-1, Math.min(1, drag.fx + (e.clientX - drag.x) / r.width)); current.fit.y = Math.max(-1, Math.min(1, drag.fy + (e.clientY - drag.y) / r.height)); draw(); };
  canvas.onpointerup = canvas.onpointercancel = e => { if (!drag) return; drag = null; try { canvas.releasePointerCapture(e.pointerId); } catch { /* already released */ } commitFit(); };
  show(); draw();
  return { refresh() { frameImage.src = '/jobs/' + jobId + '/mask/frame?i=0&t=' + Date.now(); } };
}

/** The Background chip for the review panel: "Background · Set image", a deep link to the composite card in Studio. */
export function backgroundChip(chain, jobId) {
  const entry = (chain && chain.composite) || {};
  if (entry.tool !== 'depth_cutout') return null;
  const background = (entry.params || {}).background || 'original';
  return el('a', { class: 'chip bg-chip', href: hrefFor({ job: jobId, view: 'studio' }) + '#stage-composite', 'data-nav': true, title: 'Change it on the composite card in Studio', text: 'Background · ' + (BACKGROUND_LABEL[background] || background) });
}

// ---------------------------------------------------------------- Set / Look / Light panel (draft step)

export function mountSlots(before) {
  const node = tpl('tpl-slots'); before.before(node);
  const q = s => $(s, node);
  const setBox = q('[data-set]'), lookBox = q('[data-look]'), light = q('input[name=light]'), taskLine = q('[data-task]'), saved = q('[data-saved]'), applyRow = q('[data-apply]');
  const setSelect = el('select', { 'aria-label': 'Set' }), lookSelect = el('select', { 'aria-label': 'Look' });
  for (const [name, label, hint] of SET_MODES) setSelect.append(el('option', { value: name, text: label + ' · ' + hint }));
  for (const [name, label, hint] of LOOK_MODES) lookSelect.append(el('option', { value: name, text: label + ' · ' + hint }));
  const setPrompt = el('textarea', { rows: 2, placeholder: 'e.g. a small kitchen with a window on the left, white tiles, wooden counter', 'aria-label': 'Set description' });
  const lookPrompt = el('textarea', { rows: 2, placeholder: 'e.g. 16 mm film, muted palette, soft grain, high contrast', 'aria-label': 'Look description' });
  const setPicker = assetPicker({ kind: 'set', label: 'Set images', onChange: name => { slots.set.image = name; save({ set: { image: name } }); } });
  const lookPicker = assetPicker({ kind: 'look', label: 'Style images', onChange: name => { slots.look.image = name; save({ look: { image: name } }); } });
  const setPickerRow = el('div', {}, setPicker.node), lookPickerRow = el('div', {}, lookPicker.node);
  const setNote = el('p', { class: 'hint' }), applyButton = el('button', { type: 'button', class: 'small', text: 'Apply as background (new run) · free' });
  setBox.append(el('label', { class: 'field' }, 'Set', setSelect), setPickerRow, el('label', { class: 'field' }, 'Set description', setPrompt), setNote);
  lookBox.append(el('label', { class: 'field' }, 'Look', lookSelect), lookPickerRow, el('label', { class: 'field' }, 'Look description', lookPrompt));
  applyRow.append(applyButton);
  let slots = null, loadedFor = null, timer = 0, busy = false;

  async function load(force = false) {
    const id = state.jobId; if (!id || (loadedFor === id && !force)) return;
    try { slots = await getJSON('/jobs/' + id + '/slots'); loadedFor = id; render(); }
    catch (e) { showError(e, { key: 'slots' }); }
  }
  async function save(patch) {
    const id = state.jobId; if (!id) return;
    saved.textContent = 'Saving…';
    try { slots = await send('/jobs/' + id + '/slots', patch, { method: 'PUT' }); saved.textContent = 'Saved with this run (slots.json). Nothing re-runs.'; render(); }
    catch (e) { saved.textContent = ''; showError(e, { key: 'slots' }); }
  }
  const debounced = patch => { clearTimeout(timer); timer = setTimeout(() => save(patch), 500); };
  setSelect.onchange = () => {
    const patch = { mode: setSelect.value };
    const plate = ((((state.run && state.run.run && state.run.run.chain) || {}).composite || {}).params || {}).set_image;
    if (setSelect.value === 'true_swap' && !slots.set.image && plate) patch.image = plate;   // the run already has a plate behind the person: start from it
    slots.set.mode = patch.mode; if (patch.image) slots.set.image = patch.image; save({ set: patch });
  };
  lookSelect.onchange = () => { slots.look.mode = lookSelect.value; save({ look: { mode: lookSelect.value } }); };
  setPrompt.oninput = () => debounced({ set: { prompt: setPrompt.value } });
  lookPrompt.oninput = () => debounced({ look: { prompt: lookPrompt.value } });
  light.oninput = () => debounced({ light: light.value });

  applyButton.onclick = async () => {
    if (!slots) return;
    const needed = BACKGROUND_FOR[slots.set.mode]; if (!needed) return;
    const params = needed === 'set_image' ? { background: 'set_image', set_image: slots.set.image || '', set_fit: fitText(slots.set.fit) } : { background: 'full_depth' };
    if (needed === 'set_image' && !slots.set.image) { notice('Choose or upload the set image first.', { kind: 'warn', fix: 'Pick a plate in the Set images list above; it is composited behind the person.', key: 'slots' }); return; }
    applyButton.disabled = true; busy = true;
    try {
      const r = await api.branch(state.jobId, { stage: 'composite', tool: 'depth_cutout', params });
      const patch = { set: { mode: slots.set.mode, image: slots.set.image, prompt: slots.set.prompt, fit: slots.set.fit }, look: slots.look, light: slots.light, generator: slots.generator };
      try { await send('/jobs/' + r.id + '/slots', patch, { method: 'PUT' }); } catch (e) { showError(e, { key: 'slots' }); }
      navigate({ job: r.id, view: state.view === 'studio' ? 'studio' : 'quick' });
      notice('New run with the ' + BACKGROUND_LABEL[needed].toLowerCase() + ' background (this one). The composite and face stages re-run locally, free; the run you came from stays as it was.', { kind: 'ok', key: 'slots' });
    } catch (e) {
      const p = plain(e);
      showError(e, { key: 'slots', actions: p.status === 402 ? [{ label: 'Run anyway · about $' + Number(p.body.estimated_cost_usd || 0).toFixed(2), run: async () => { const r = await api.branch(state.jobId, { stage: 'composite', tool: 'depth_cutout', params, confirm_cost: 'true' }); navigate({ job: r.id, view: state.view }); } }] : [] });
    } finally { busy = false; applyButton.disabled = false; }
  };

  function render() {
    if (!slots) return;
    const run = (state.run && state.run.run) || {}, chain = run.chain || {}, composite = chain.composite || {};
    setSelect.value = slots.set.mode; lookSelect.value = slots.look.mode;
    if (document.activeElement !== setPrompt) setPrompt.value = slots.set.prompt || '';
    if (document.activeElement !== lookPrompt) lookPrompt.value = slots.look.prompt || '';
    if (document.activeElement !== light) light.value = slots.light || '';
    setPicker.set(slots.set.image); lookPicker.set(slots.look.image);
    const needsImage = ['set_ref', 'true_swap'].includes(slots.set.mode);
    setPickerRow.hidden = !needsImage; setPrompt.closest('label').hidden = slots.set.mode !== 'prompt';
    lookPickerRow.hidden = slots.look.mode !== 'style_ref'; lookPrompt.closest('label').hidden = slots.look.mode !== 'prompt';
    const needed = BACKGROUND_FOR[slots.set.mode];
    const canApply = !!needed && composite.tool === 'depth_cutout';
    applyRow.hidden = !needed;
    applyButton.disabled = busy || !canApply || (state.job && state.job.state === 'running');
    if (!needed) setNote.textContent = slots.set.mode === 'set_ref' ? 'The set image goes with the request as a reference; the prompt builder adds its fence.' : '';
    else if (composite.tool !== 'depth_cutout') setNote.textContent = 'This run has no depth person (composite tool: ' + (composite.tool || 'original') + '), so there is no background to change. Prepare the clip with a depth preset (Full body, Expressive) to use this set mode.';
    else if (slots.background_applied) setNote.textContent = 'Applied in this run: the composite already uses the ' + BACKGROUND_LABEL[needed].toLowerCase() + ' background.';
    else setNote.textContent = 'This set mode needs the ' + BACKGROUND_LABEL[needed].toLowerCase() + ' background in the composite (this run has ' + (slots.background === needed ? 'a different set plate' : (slots.background_label || 'original frames').toLowerCase()) + '). "Apply as background" makes a new run with it and saves these slots there.';
    const provider = (state.generation && state.generation.provider) || (slots.generator && slots.generator.name) || '';
    const caps = state.providers[provider] || (!provider && state.providerDefault === 'enhancor' && !(state.providers.fal && state.providers.fal.configured) ? state.providers.enhancor : null);
    const noTask = !!(caps && Array.isArray(caps.tasks) && !caps.tasks.length);   // from the generator's capabilities (tasks: []), not a hard-coded provider name
    const why = slots.task_source === 'user' ? 'chosen by you' : slots.set.mode === 'original' ? 'original set' : 'set changed';
    taskLine.textContent = 'Task · ' + slots.task + ' (' + why + ')' + (noTask ? '. ' + caps.label + ' has no task setting' + (caps.control === 'pose' ? ' (it always keeps the pose and timing of the prepared clip)' : ' (it always edits the prepared clip)') + ', so this is recorded as not applicable there.' : '');
  }
  return { node, update() { if (state.jobId !== loadedFor) { slots = null; saved.textContent = ''; } load(); if (slots) render(); }, reload: () => load(true) };
}
