// Shared state, the URL and timers.
//
// URL shape (tidy pass): `/` and `/?view=runs` = the Runs page; `/?view=new` = New run (Quick start);
// `/?job=<id>&step=prep|edit|world|generate|export` = the workspace of one run (no step = the most useful one);
// `/?view=compare&runs=a,b&stage=<file>` = Compare. Old links keep working: view=quick → the workspace (or New run
// without a job), view=studio → the workspace with the Details drawer on Stages, view=lab → Compare.
//
// Every timer and every async job load carries the token that was current when it started. `stopTimers()` bumps the
// token and clears the timers, so a poll started for one run can never write into the page after the user moved
// to another run: that is the fix for the stale banner. A step switch inside the same run does not bump the token.
import { isHex } from './ui.js';

export const VIEWS = ['runs', 'workspace', 'compare', 'new'];
export const STEPS = ['prep', 'edit', 'world', 'generate', 'export'];
const OLD = { quick: 'workspace', studio: 'workspace', lab: 'compare' };

export const state = {
  jobId: null, view: 'runs', step: null, query: new URLSearchParams(location.search), details: null, flat: false,
  registry: null, presets: [], providers: {}, providerDefault: '', costs: null,
  // the run in the URL
  job: null, run: null, files: new Set(), review: null, tracking: null, generation: null, hd: null,
  selectedPreview: '', previewChosen: false,   // previewChosen: the user clicked a view, so keep it; otherwise follow the best one available
  // compare
  labRuns: [], labStage: 'seedance-input.mp4',
  token: 0, timers: new Set(),
};

let renderFn = null;
export function onRender(fn) { renderFn = fn; }

export function readUrl() {
  const q = new URLSearchParams(location.search);
  state.query = q;
  const nextJob = isHex(q.get('job')) ? q.get('job') : null;
  if (nextJob !== state.jobId) { state.previewChosen = false; }   // a new run starts on its best view again
  state.jobId = nextJob;
  let view = q.get('view') || '';
  if (OLD[view]) { state.details = view === 'studio' ? 'stages' : null; view = OLD[view]; }
  else state.details = q.get('details') || null;
  if (view === 'workspace' && !nextJob) view = 'new';
  if (!VIEWS.includes(view)) view = nextJob ? 'workspace' : 'runs';
  if (view === 'new' && nextJob) view = 'workspace';
  state.view = view;
  const step = q.get('step') || (location.hash && STEPS.includes(location.hash.slice(1)) ? location.hash.slice(1) : '');
  state.step = STEPS.includes(step) ? step : null;
  state.flat = q.get('flat') === '1';
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

/** The URL of a run's workspace (optionally at a step). */
export const runHref = (id, step = null) => hrefFor({ job: id, step });

export function navigate(params, { replace = false, hash = '' } = {}) {
  const href = hrefFor(params) + (hash ? '#' + hash : '');
  history[replace ? 'replaceState' : 'pushState'](null, '', href);
  render();
}

/** Re-read the URL and render (the renderer decides whether the page is remounted or only the step changes). */
export function render() {
  readUrl();
  if (renderFn) renderFn();
}

/** Go to a step of the current run: one history entry per step, so Back / Forward move between steps. */
export function goStep(step, { replace = false } = {}) {
  if (!STEPS.includes(step) || !state.jobId) return;
  history[replace ? 'replaceState' : 'pushState'](null, '', hrefFor({ job: state.jobId, step }));
  render();
}

export function stopTimers() {
  state.token++;
  for (const t of state.timers) clearTimeout(t);
  state.timers.clear();
}

/** setTimeout that is cancelled by the next remount and ignored when the page moved on. */
export function later(fn, ms) {
  const token = state.token;
  const t = setTimeout(() => { state.timers.delete(t); if (token !== state.token) return; fn(); }, ms);
  state.timers.add(t);
  return t;
}

/** True when nothing changed since `token` was taken (and, when given, the run in the URL is still `jobId`). */
export function current(token, jobId) {
  return token === state.token && (jobId === undefined || jobId === state.jobId);
}

export function setLabRuns(ids) {
  state.labRuns = [...new Set(ids.filter(isHex))].slice(0, 4);
  try { sessionStorage.setItem('labRuns', JSON.stringify(state.labRuns)); } catch { /* private mode: the URL still carries the selection */ }
}
