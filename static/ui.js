// DOM helpers, formatting, page notices. Page notices are separate from the job banner (see app.js): a notice is
// about something the page did (an upload that failed, a saved preset); the banner is only ever the job in the URL.
import { plain } from './api.js';

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export function tpl(id) {
  const template = document.getElementById(id);
  if (!template) throw new Error('Missing template ' + id);
  return template.content.firstElementChild.cloneNode(true);
}

/** el('button', {class: 'small', onclick: fn, text: 'Go'}, child...) */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
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
export const duration = s => s == null ? '' : Number(s) >= 90 ? (Number(s) / 60).toFixed(1) + ' min' : Number(s).toFixed(1) + ' s';
/** "0.42–0.71 s and 2.08–2.58 s" */
export const ranges = gaps => (gaps || []).map(g => `${g.start_s}–${g.end_s} s`).join(' and ');
export const shortId = id => (id || '').slice(0, 8);
export const isHex = id => /^[0-9a-f]{32}$/.test(id || '');

export const MODES = { depth: 'Advanced · Depth + SAM', face_mesh: 'Fast · Face mesh', depth_mesh: 'Advanced + Face mesh', original: 'Original video only', unknown: 'Unknown method' };
export const modeLabel = mode => MODES[mode] || MODES.unknown;
/** Preset name when the run has one, else the method label. */
export const runLabel = summary => (summary && summary.preset) || modeLabel(summary && summary.mode);

export function setChip(node, state, text) {
  node.className = 'chip ' + (state || 'unknown');
  node.textContent = text || state || 'unknown';
}

// ---------------------------------------------------------------- notices
// #notices is a fixed toast stack at the bottom of the viewport (app.css), so a notice raised from anywhere (the
// editor's Save bar at the bottom of a long page, a track tool, an upload) is visible where the user is. Errors and
// notices with action buttons stay until dismissed (×, Esc while focused, or an action); "ok" notices fade after
// 10 s and plain warnings after 16 s, paused while hovered or focused. At most MAX_NOTICES show; the oldest goes.

const MAX_NOTICES = 4;
const LIFETIME = { ok: 10000, warn: 16000 };

export function clearNotices() { const box = $('#notices'); if (box) box.replaceChildren(); }

/** Show a page notice: a sentence, a fix, optional action buttons [{label, run}]. `key` replaces an earlier notice with the same key. */
export function notice(message, { fix = '', kind = 'error', actions = [], key = null } = {}) {
  const box = $('#notices');
  if (!box) return null;
  if (key) $$('[data-key]', box).filter(n => n.dataset.key === key).forEach(n => n.remove());
  let timer = 0;
  const close = () => { clearTimeout(timer); node.remove(); };
  const node = el('div', { class: 'notice ' + kind, role: kind === 'error' ? 'alert' : 'status', dataset: key ? { key } : {} },
    el('div', { class: 'body' }, el('span', { class: 'wrap', text: message }), fix ? el('span', { class: 'fix', text: fix }) : null,
      actions.length ? el('div', { class: 'actions-inline' }, actions.map(a => el('button', { type: 'button', class: 'small ' + (a.secondary ? 'secondary' : ''), onclick: e => runAction(a, e.currentTarget), text: a.label }))) : null),
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
