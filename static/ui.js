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

export function clearNotices() { const box = $('#notices'); if (box) box.replaceChildren(); }

/** Show a page notice: a sentence, a fix, optional action buttons [{label, run}]. `key` replaces an earlier notice with the same key. */
export function notice(message, { fix = '', kind = 'error', actions = [], key = null } = {}) {
  const box = $('#notices');
  if (!box) return null;
  if (key) $$('[data-key]', box).filter(n => n.dataset.key === key).forEach(n => n.remove());
  const node = el('div', { class: 'notice ' + kind, role: kind === 'error' ? 'alert' : 'status', dataset: key ? { key } : {} },
    el('div', { class: 'body' }, el('span', { class: 'wrap', text: message }), fix ? el('span', { class: 'fix', text: fix }) : null,
      actions.length ? el('div', { class: 'actions-inline' }, actions.map(a => el('button', { type: 'button', class: 'small ' + (a.secondary ? 'secondary' : ''), onclick: async () => { try { await a.run(); node.remove(); } catch (e) { showError(e); } }, text: a.label }))) : null),
    el('button', { type: 'button', class: 'close', 'aria-label': 'Dismiss', onclick: () => node.remove(), text: '×' }));
  box.prepend(node);
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
