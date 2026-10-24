// World helpers: set / look images (runs/_assets), the fit maths shared with stages/plates.py, the Background
// controls of the Motion clip stage (drawn under World & Look → Set and on the stage row in Details), and the plain
// names of the backgrounds and the Set / Look modes. The Set / Look / Light panel itself is static/world.js.
import { getJSON, send } from './api.js';
import { el, showError } from './ui.js';
import { state } from './state.js';

export const BACKGROUNDS = [
  ['original', 'Original frames', 'The depth person over the real frames.'],
  ['full_depth', 'Full depth', 'The whole frame is the depth video.'],
  ['plain', 'Plain colour', 'A flat black or gray background.'],
  ['set_image', 'Set image', 'A set image behind the person, fitted to the frame.'],
];
export const BACKGROUND_LABEL = Object.fromEntries(BACKGROUNDS.map(b => [b[0], b[1]]));
export const BACKGROUND_PARAMS = ['background', 'plain_color', 'set_image', 'set_fit'];
export const SET_MODES = [
  ['original', 'Keep the original', 'The room as it is in the clip.'],
  ['prompt', 'Describe it', 'Say what the place is in words.'],
  ['set_ref', 'Use a set image as reference', 'The generator sees the picture of the place next to the character.'],
  ['true_swap', 'Put the set image behind the person', 'The picture becomes the real background of the motion clip (a new version).'],
  ['original_depth', 'Depth only (regenerate the room)', 'Keep the room’s shape as depth and let the generator redraw its look (a new version with the full-depth background).'],
];
export const LOOK_MODES = [
  ['follow', 'Let the references decide', 'The character and set pictures set the look.'],
  ['style_ref', 'Copy a look image', 'A picture whose colours, grain and contrast the result should copy.'],
  ['prompt', 'Describe it', 'Say what the rendering style is in words.'],
];
export const BACKGROUND_FOR = { original_depth: 'full_depth', true_swap: 'set_image' };
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
export const fitText = fit => { const f = parseFit(fit); return f.x === 0 && f.y === 0 && f.scale === 1 ? '' : JSON.stringify({ scale: +f.scale.toFixed(4), x: +f.x.toFixed(4), y: +f.y.toFixed(4) }); };

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
  const input = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', 'aria-label': 'Upload a ' + (kind === 'look' ? 'look image' : 'set image') });
  const status = el('span', { class: 'hint' });
  const node = el('div', { class: 'asset-picker' }, grid, el('div', { class: 'row' }, el('label', { class: 'button sm asset-upload' }, 'Upload an image…', input), status));
  let current = value || null;
  function draw(assets) {
    grid.replaceChildren();
    const mine = assets.filter(a => !kind || a.kind === kind || a.name === current);
    if (!mine.length) grid.append(el('span', { class: 'hint', text: 'No ' + (kind === 'look' ? 'look images' : 'set images') + ' yet. Upload a PNG, JPEG or WebP (up to 30 MB).' }));
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
  const canvas = el('canvas', { class: 'bg-canvas', width: 480, height: 270, 'aria-label': 'Set image placement: drag to move' });
  const scale = el('input', { type: 'range', min: '0.2', max: '3', step: '0.01', 'aria-label': 'Set image scale' }); scale.value = String(current.fit.scale);
  const fitLine = el('span', { class: 'hint' });
  const reset = el('button', { type: 'button', class: 'sm', text: 'Centre & cover' });
  const picker = assetPicker({ kind: 'set', value: current.set_image, label: 'Set images', onChange: name => { current.set_image = name || ''; set('set_image', current.set_image); draw(); } });
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
    fitLine.textContent = current.set_image ? `The set image covers the frame, centred; moved ${(f.x * 100).toFixed(0)}% / ${(f.y * 100).toFixed(0)}%, scale ×${f.scale.toFixed(2)}. Drag the picture to move it. The first frame is shown half transparent over it; the person is cut out at full quality when it runs.` : 'Pick or upload a set image; it is fitted to cover the frame and the person is placed over it.';
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
