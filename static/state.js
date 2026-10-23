// Shared state, the URL (?job=<id>&view=quick|studio|lab|runs) and timers.
//
// Every timer and every async job load carries the token that was current when it started. `render()` bumps the
// token and clears the timers, so a poll started for one run can never write into the page after the user moved
// to another run: that is the fix for the stale banner.
import { isHex } from './ui.js';

export const VIEWS = ['quick', 'studio', 'lab', 'runs'];

export const state = {
  jobId: null, view: 'quick', query: new URLSearchParams(location.search),
  registry: null, presets: [], providers: {}, providerDefault: '', costs: null,
  // the job in the URL
  job: null, run: null, files: new Set(), review: null, tracking: null, generation: null, hd: null,
  selectedPreview: '', previewChosen: false,   // previewChosen: the user clicked a tab, so keep it; otherwise follow the best preview available
  // lab
  labRuns: [], labStage: 'seedance-input.mp4',
  token: 0, timers: new Set(),
};

let renderFn = null;
export function onRender(fn) { renderFn = fn; }

export function readUrl() {
  const q = new URLSearchParams(location.search);
  state.query = q;
  const nextJob = isHex(q.get('job')) ? q.get('job') : null;
  if (nextJob !== state.jobId) { state.previewChosen = false; }   // a new run starts on its best preview again
  state.jobId = nextJob;
  const view = q.get('view');
  state.view = VIEWS.includes(view) ? view : 'quick';
  const runs = (q.get('runs') || '').split(',').map(s => s.trim()).filter(isHex);
  if (runs.length) state.labRuns = runs.slice(0, 4);
  else { try { state.labRuns = JSON.parse(sessionStorage.getItem('labRuns') || '[]').filter(isHex).slice(0, 4); } catch { state.labRuns = []; } }
  if (q.get('stage')) state.labStage = q.get('stage');
}

export function hrefFor(params) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value != null && value !== '' && value !== false) q.set(key, Array.isArray(value) ? value.join(',') : String(value));
  const text = q.toString();
  return '/' + (text ? '?' + text : '');
}

export function navigate(params, { replace = false, hash = '' } = {}) {
  const href = hrefFor(params) + (hash ? '#' + hash : '');
  history[replace ? 'replaceState' : 'pushState'](null, '', href);
  render();
}

export function render() {
  stopTimers();
  readUrl();
  if (renderFn) renderFn();
}

export function stopTimers() {
  state.token++;
  for (const t of state.timers) clearTimeout(t);
  state.timers.clear();
}

/** setTimeout that is cancelled by the next render and ignored when the page moved on. */
export function later(fn, ms) {
  const token = state.token;
  const t = setTimeout(() => { state.timers.delete(t); if (token !== state.token) return; fn(); }, ms);
  state.timers.add(t);
  return t;
}

/** True when nothing changed since `token` was taken (and, when given, the job in the URL is still `jobId`). */
export function current(token, jobId) {
  return token === state.token && (jobId === undefined || jobId === state.jobId);
}

export function setLabRuns(ids) {
  state.labRuns = [...new Set(ids.filter(isHex))].slice(0, 4);
  try { sessionStorage.setItem('labRuns', JSON.stringify(state.labRuns)); } catch { /* private mode: the URL still carries the selection */ }
}
