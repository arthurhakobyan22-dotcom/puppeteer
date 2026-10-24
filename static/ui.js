// DOM helpers, formatting, plain names, remembered panels, page notices (toasts). Page notices are separate from the
// run banner (see jobdata.js): a notice is about something the page did (an upload that failed, a saved preset); the
// banner is only ever a failure of the run in the URL.
import { plain } from './api.js';

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export function tpl(id) {
  const template = document.getElementById(id);
  if (!template) throw new Error('Missing template ' + id);
  return template.content.firstElementChild.cloneNode(true);
}

/** el('button', {class: 'sm', onclick: fn, text: 'Go'}, child...) */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** An inline SVG icon from the small set used in the templates: arrow, back, plus, info, pencil, check, warn, copy. */
const ICONS = { arrow: 'M5 12h14m-6-6 6 6-6 6', back: 'm15 6-6 6 6 6', plus: 'M12 5v14M5 12h14', info: 'M12 11v5M12 8h.01', pencil: 'M4 20h4l10-10-4-4L4 16zM13 7l4 4', check: 'm5 13 4 4L19 7', warn: 'M12 9v4M12 17h.01M10.3 3.9 2.6 17.3A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.7L13.7 3.9a2 2 0 0 0-3.4 0z', copy: 'M8 8h12v12H8zM4 16V4h12' };
export function icon(name) {
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'), path = document.createElementNS(ns, 'path');
  svg.setAttribute('class', 'i'); svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  if (name === 'info') { const c = document.createElementNS(ns, 'circle'); c.setAttribute('cx', '12'); c.setAttribute('cy', '12'); c.setAttribute('r', '9'); svg.append(c); }
  path.setAttribute('d', ICONS[name] || ICONS.arrow); svg.append(path);
  return svg;
}

/** A button whose label ends with the price: btnCost('Create draft', 'about $2.15') → "Create draft · about $2.15". */
export function withCost(button, text, cost) {
  button.replaceChildren(...[text, cost ? el('span', { class: 'cost', text: ' · ' + cost }) : null].filter(x => x != null && x !== ''));
  return button;
}

/** The accessible name of a tool button: its visible label (arrows and other glyphs dropped), so a screen reader and
 *  voice control say what the eye reads; the long `title` stays as the tooltip / description. A label that is only a
 *  symbol ("−", "+") takes the first clause of the title instead ("Zoom out"). */
export function ariaFor(text, title = '') {
  const words = String(text || '').replace(/[◀▶❚◆●▨↓→←·…]/g, ' ').replace(/\s+/g, ' ').trim();
  return /[A-Za-z0-9]{2,}/.test(words) ? words : String(title || text || '').split(' (')[0].trim();
}

export const usd = x => { const n = Number(x || 0); return n < 0.005 ? 'free' : 'about $' + n.toFixed(2); };
export const spent = x => '$' + Number(x || 0).toFixed(2);
export const when = iso => { if (!iso) return ''; try { return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }); } catch { return String(iso); } };
export const dateShort = iso => { if (!iso) return ''; try { return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' }); } catch { return String(iso); } };
/** "2 hours ago", "yesterday", "3 days ago", else the short date. */
export function ago(iso) {
  if (!iso) return '';
  const t = new Date(iso).getTime(); if (!Number.isFinite(t)) return String(iso);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.round(s / 60) + ' min ago';
  if (s < 86400) { const h = Math.round(s / 3600); return h + (h === 1 ? ' hour ago' : ' hours ago'); }
  if (s < 172800) return 'yesterday';
  if (s < 7 * 86400) return Math.round(s / 86400) + ' days ago';
  return dateShort(iso);
}
export const duration = s => s == null ? '' : Number(s) >= 90 ? (Number(s) / 60).toFixed(1) + ' min' : Number(s).toFixed(1) + ' s';
/** "0.42–0.71 s and 2.08–2.58 s" */
export const ranges = gaps => (gaps || []).map(g => `${g.start_s}–${g.end_s} s`).join(' and ');
export const shortId = id => (id || '').slice(0, 8);
export const isHex = id => /^[0-9a-f]{32}$/.test(id || '');
export const bytes = n => n == null ? '' : n > 1e9 ? (n / 1e9).toFixed(2) + ' GB' : n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.round(n / 1e3) + ' kB';

// ---------------------------------------------------------------- plain names (docs/GLOSSARY.md)
export const MODES = { depth: 'Motion clip', face_mesh: 'Face mesh only', depth_mesh: 'Motion clip + face mesh', original: 'Original video only', unknown: 'Unknown method' };
export const modeLabel = mode => MODES[mode] || MODES.unknown;
/** Stage names as the UI says them (the registry keeps its own labels). */
export const STAGE_NAMES = { input_doctor: 'Input check', audio: 'Audio', depth: 'Depth', mask: 'Mask', composite: 'Motion clip', face: 'Face mesh', prompt: 'Prompt', generate: 'Generate', finish: 'Finish' };
export const stageName = (name, fallback = '') => STAGE_NAMES[name] || fallback || name;
/** Method labels as the UI says them (the registry's label otherwise). */
const METHOD_NAMES = { depth_cutout: 'Depth person over a background', original: 'Original frames', local_propagate: 'Free, local (rougher edges)', sam3_points_fal: 'SAM 3 on fal', sam2_points_replicate: 'SAM 2 on Replicate', brush: 'Brush', edit_layer: 'Timeline edits', mesh_edit: 'Timeline mesh edits', import_depth: 'My own depth video', import_mask: 'My own mask', import_face: 'My own face overlay or landmarks', import_control: 'My own motion clip', complete_draft: 'Make the final at 1080p', restore_original_audio: 'Restore the original audio', identity_only: 'Identity-only prompt', probe: 'Check and normalize', doctor: 'Input check (checks + safe fixes)' };
export const methodName = (name, fallback = '') => METHOD_NAMES[name] || fallback || name;
/** Preset name when the run has one, else the prep method. */
export const runLabel = summary => (summary && summary.preset) || modeLabel(summary && summary.mode);
/** The name shown for a run: the stored name, else "<preset or prep method> · <date>" plus the first clause of what changed. */
export function runName(summary) {
  if (!summary) return 'Run';
  if (summary.name) return summary.name;
  let base = runLabel(summary) + (summary.created ? ' · ' + dateShort(summary.created) : '');
  if (summary.parent && summary.changed) base += ' · ' + firstClause(summary.changed);
  return base;
}
export const firstClause = text => String(text || '').split(/[;.(]/)[0].split(' → ')[0].trim().slice(0, 60);
/** One status word for a run summary: preparing · failed · final done · draft done · ready (approved) · needs review · imported. */
export function runStatus(r) {
  if (!r) return { key: 'unknown', text: 'unknown' };
  if (r.state === 'running') return { key: 'preparing', text: 'preparing' };
  if (r.state === 'error') return { key: 'failed', text: 'failed' };
  if (r.final) return { key: 'final', text: 'final done' };
  if (r.draft) return { key: 'draft', text: 'draft done' };
  if (r.request) return { key: 'draft', text: 'draft submitted' };
  if (r.reviewed) return { key: 'ready', text: 'ready' };
  if (r.state === 'done') return { key: 'review', text: 'needs review' };
  return { key: 'unknown', text: r.state || 'unknown' };
}

export function setChip(node, state, text) {
  node.className = 'chip ' + (state || 'unknown');
  node.textContent = text || state || 'unknown';
}

/** Placeholder for the help tooltips Agent 4 adds: returns the glossary term's short text when known. */
const HELP = {};
export function help(term) { return HELP[term] || ''; }

/** A CSS token's current value (for canvas drawing). */
export const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------------------------------------------------------------- level-2 panels remember their state
const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } };
/** Wire every <details data-remember="key"> under root: open / closed is stored per panel (not per run). */
export function remember(root) {
  for (const d of $$('details[data-remember]', root)) {
    if (d.dataset.wired) continue; d.dataset.wired = '1';
    const key = 'pp-open-' + d.dataset.remember, saved = LS(key);
    if (saved === '1') d.open = true; else if (saved === '0') d.open = false;
    d.addEventListener('toggle', () => LS(key, d.open ? '1' : '0'));
  }
  return root;
}
export const stored = (key, value) => LS('pp-' + key, value);

// ---------------------------------------------------------------- notices (toasts)
// #notices is a fixed toast stack at the bottom of the viewport, so a notice raised from anywhere is visible where the
// user is. Errors and notices with action buttons stay until dismissed (×, Esc while focused, or an action); "ok"
// notices fade after 10 s and plain warnings after 16 s, paused while hovered or focused. At most MAX_NOTICES show.

const MAX_NOTICES = 4;
const LIFETIME = { ok: 10000, warn: 16000 };

export function clearNotices() { const box = $('#notices'); if (box) box.replaceChildren(); }

/** Show a page notice: a sentence, a fix, optional action buttons [{label, run, secondary?, primary?}]. `key` replaces an earlier notice with the same key. */
export function notice(message, { fix = '', kind = 'error', actions = [], key = null } = {}) {
  const box = $('#notices');
  if (!box) return null;
  if (key) $$('[data-key]', box).filter(n => n.dataset.key === key).forEach(n => n.remove());
  let timer = 0;
  const close = () => { clearTimeout(timer); node.remove(); };
  const node = el('div', { class: 'toast ' + kind, role: kind === 'error' ? 'alert' : 'status', dataset: key ? { key } : {} },
    el('div', { class: 'body' }, el('span', { class: 'wrap', text: message }), fix ? el('span', { class: 'fix', text: fix }) : null,
      actions.length ? el('div', { class: 'actions-inline' }, actions.map((a, i) => el('button', { type: 'button', class: 'sm ' + (a.primary || (i === 0 && !a.secondary) ? 'primary' : ''), onclick: e => runAction(a, e.currentTarget), text: a.label }))) : null),
    el('button', { type: 'button', class: 'close', 'aria-label': 'Dismiss', title: 'Dismiss', onclick: close, text: '×' }));
  async function runAction(a, button) {   // the notice stays (buttons disabled, "…") while the action runs, so a slow Apply shows it is working
    const buttons = $$('.actions-inline button', node); buttons.forEach(b => { b.disabled = true; }); button.textContent = a.label + '…';
    try { await a.run(); close(); }
    catch (e) { buttons.forEach(b => { b.disabled = false; }); button.textContent = a.label; showError(e); }
  }
  node.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } });
  const life = !actions.length && LIFETIME[kind];
  if (life) {
    const arm = () => { clearTimeout(timer); timer = setTimeout(() => { if (!node.matches(':hover') && !node.contains(document.activeElement)) node.remove(); else arm(); }, life); };
    node.addEventListener('mouseenter', () => clearTimeout(timer)); node.addEventListener('mouseleave', arm);
    node.addEventListener('focusin', () => clearTimeout(timer)); node.addEventListener('focusout', arm);
    arm();
  }
  box.append(node);   // newest at the bottom, nearest the user's eye in a bottom stack
  const all = [...box.children]; for (const old of all.slice(0, Math.max(0, all.length - MAX_NOTICES))) old.remove();
  return node;
}

export function showError(error, options = {}) {
  const p = plain(error);
  return notice(p.message, { fix: p.fix, kind: 'error', ...options });
}

/** The 402 action for a refused price: one wording everywhere ("Yes, spend about $x"). */
export function costActions(error, resend) {
  const p = plain(error);
  if (p.status !== 402) return [];
  return [{ label: 'Yes, spend ' + usd(p.body.estimated_cost_usd), run: resend, primary: true }, { label: 'Not now', secondary: true, run: async () => {} }];
}

// ---------------------------------------------------------------- file inputs

/** Show the chosen file name (and an image thumbnail) inside every .upload label under `root`. */
export function wireUploads(root, onchange) {
  for (const input of $$('input[type=file]', root)) {
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      const label = input.closest('.upload');
      if (file && label) {
        const name = label.querySelector('[data-filename]'); if (name) name.textContent = file.name;
        const img = label.querySelector('img');
        if (img) { if (!file.type.startsWith('video/')) { img.src = URL.createObjectURL(file); img.hidden = false; } else img.hidden = true; }
        label.classList.add('has');
      }
      if (onchange) onchange(input, file);
    });
  }
}

/** Length of a chosen video file in seconds (reads its metadata locally), or null. */
export function videoSeconds(file) {
  return new Promise(resolve => {
    if (!file || !file.type.startsWith('video/')) return resolve(null);
    const video = document.createElement('video'); const url = URL.createObjectURL(file);
    const done = value => { URL.revokeObjectURL(url); resolve(value); };
    video.preload = 'metadata';
    video.onloadedmetadata = () => done(Number.isFinite(video.duration) ? video.duration : null);
    video.onerror = () => done(null);
    setTimeout(() => done(null), 4000);
    video.src = url;
  });
}

/** A thumbnail element for a run: preview.jpg → the first frame (GET /jobs/{id}/mask/frame) → the original video's
 *  poster → a grey tile. `files` (a Set, or a promise of one from GET /jobs/{id}/files) decides without probing. */
const fileLists = new Map();
export function filesOf(id) {
  if (!fileLists.has(id)) fileLists.set(id, fetch('/jobs/' + id + '/files', { cache: 'no-store' }).then(r => (r.ok ? r.json() : { files: [] })).then(j => new Set(j.files || [])).catch(() => new Set()));
  return fileLists.get(id);
}
export function runThumb(id, { files = null, state: text = '' } = {}) {
  const box = el('div', { class: 'thumb' });
  const blank = () => box.prepend(el('span', { class: 'blank', text: text || 'no picture' }));
  Promise.resolve(files || filesOf(id)).then(set => {
    if (set.has('preview.jpg')) box.prepend(el('img', { alt: '', loading: 'lazy', src: '/runs/' + id + '/preview.jpg', onerror: e => { e.currentTarget.remove(); blank(); } }));
    else if (set.has('original.mp4')) box.prepend(el('img', { alt: '', loading: 'lazy', src: '/jobs/' + id + '/mask/frame?i=0', onerror: e => { e.currentTarget.replaceWith(el('video', { src: '/runs/' + id + '/original.mp4#t=0.5', preload: 'metadata', muted: true, playsinline: true, 'aria-hidden': 'true' })); } }));
    else blank();
  });
  return box;
}
