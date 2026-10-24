// Loading and polling the run named in the URL. The run banner is written only from here, only after checking
// that the answer still belongs to the run in the URL (token + id), so another run's status can never leak in.
// The banner shows failures only (the step rail and the status line carry the running state).
import { api, plain } from './api.js';
import { $, el, usd, showError } from './ui.js';
import { state, later, current, navigate } from './state.js';

const POLL_MS = 2500;
let listeners = [];
/** The workspace registers one callback that re-renders its step bodies after a (re)load. */
export function onJobData(fn) { listeners = [fn]; }
export function clearJobListeners() { listeners = []; }

export function resetJob() {
  Object.assign(state, { job: null, run: null, files: new Set(), review: null, tracking: null, generation: null, hd: null });
  renderBanner();
}

/** The status dict of the run: the live job, else the saved status, else what run.json says. */
async function fetchStatus(id) {
  try { return await api.job(id); }
  catch (e) {
    const p = plain(e);
    if (p.status === 404) {
      if (state.run && state.run.status) return state.run.status;
      return { state: 'unknown', status: 'No status was saved for this run (it was interrupted before preparation finished).', fix: 'Open Details · Stages and make a new version from the stage that did not finish.' };
    }
    throw e;
  }
}

/** Load everything the steps need for the run in the URL. Safe to call again; results are dropped when the page moved on. */
export async function loadJob({ quiet = false } = {}) {
  const id = state.jobId; const token = state.token;
  if (!id) return;
  try {
    const [run, files, review] = await Promise.all([api.run(id), api.files(id), api.review(id)]);
    if (!current(token, id)) return;
    state.run = run; state.files = new Set(files.files || []); state.review = review;
    state.job = await fetchStatus(id);
    if (!current(token, id)) return;
    const extras = await Promise.all([
      state.files.has('face-tracking.json') ? api.runFile(id, 'face-tracking.json').catch(() => null) : null,
      state.files.has('generation.json') ? api.runFile(id, 'generation.json').catch(() => null) : null,
      api.hd(id).catch(() => null),
    ]);
    if (!current(token, id)) return;
    [state.tracking, state.generation, state.hd] = extras;
  } catch (e) {
    if (!current(token, id)) return;
    const p = plain(e);
    state.job = { state: 'error', status: p.message, fix: p.fix, unreachable: p.status === 0 };
  }
  renderBanner();
  for (const fn of listeners) fn();
  if (state.job && state.job.state === 'running') later(() => poll(), POLL_MS);
  if (state.hd && state.hd.state === 'running') later(() => pollHD(), 4000);
  void quiet;
}

/** While the run prepares: refresh its status (and the stage reports) every few seconds; on completion reload everything. */
async function poll() {
  const id = state.jobId; const token = state.token;
  if (!id) return;
  let status;
  try { status = await fetchStatus(id); }
  catch (e) { if (!current(token, id)) return; later(() => poll(), POLL_MS * 2); return; }   // a glitch: keep polling, never show another run's words
  if (!current(token, id)) return;
  if (status.state === 'running') {
    state.job = status;
    try { const run = await api.run(id); if (current(token, id)) state.run = run; } catch { /* reports refresh on the next poll */ }
    if (!current(token, id)) return;
    renderBanner();
    for (const fn of listeners) fn();
    later(() => poll(), POLL_MS);
  } else await loadJob();
}

export async function pollHD() {
  const id = state.jobId; const token = state.token;
  if (!id) return;
  try {
    const hd = await api.hd(id);
    if (!current(token, id)) return;
    state.hd = hd;
    if (hd.state === 'running') { for (const fn of listeners) fn(); later(() => pollHD(), 4000); }
    else await loadJob();
  } catch { if (current(token, id)) later(() => pollHD(), 8000); }
}

export function isBusy() { return !!(state.job && state.job.state === 'running'); }

/** Stage whose report is in error (for fix buttons), or null. */
export function failedStage() {
  const reports = (state.run && state.run.reports) || {};
  for (const [stage, report] of Object.entries(reports)) if (report && report.state === 'error') return stage;
  return null;
}

/** Fix actions for a failed run: re-run leniently (free) for a strict face-tracking failure; open the failed stage in Details. */
export function fixActions() {
  const actions = [];
  const stage = failedStage();
  if (!state.jobId) return actions;
  const chain = (state.run && state.run.run && state.run.run.chain) || {};
  const face = chain.face || {};
  const text = ((state.job && state.job.status) || '').toLowerCase();
  if (stage === 'face' && face.tool === 'mediapipe_mesh' && face.params && face.params.strict && /lost face|tracking gap/.test(text)) {
    actions.push({ label: 'Re-run with lenient gaps · free', run: async () => {
      const r = await api.branch(state.jobId, { stage: 'face', tool: 'mediapipe_mesh', params: { strict: false } });
      navigate({ job: r.id, step: 'prep' });
    } });
  }
  if (stage) actions.push({ label: 'Open the failed stage', secondary: true, run: async () => { const { openDetails } = await import('./drawer.js'); openDetails({ id: state.jobId, tab: 'stages', stage }); } });
  return actions;
}

/** The banner shows a failure of the run in the URL and nothing else. */
export function renderBanner() {
  const banner = $('#job-banner');
  if (!banner) return;
  const job = state.jobId ? state.job : null;
  if (!job || job.state !== 'error') { banner.hidden = true; return; }
  const text = $('[data-text]', banner), fix = $('[data-fix]', banner), actions = $('[data-actions]', banner);
  banner.className = 'banner error';
  text.textContent = job.unreachable ? job.status : 'Preparation failed: ' + (job.status || 'no reason was saved');
  const fixText = job.fix || (job.unreachable ? '' : 'Make a new version from the stage that failed (Details · Stages); where the app can do it for you, a button is shown here.');
  fix.textContent = fixText; fix.hidden = !fixText;
  actions.replaceChildren();
  const list = !job.unreachable ? fixActions() : [];
  for (const a of list) actions.append(el('button', { type: 'button', class: 'sm ' + (a.secondary ? '' : 'primary'), text: a.label, onclick: async (ev) => { ev.target.disabled = true; try { await a.run(); } catch (e) { showError(e); ev.target.disabled = false; } } }));
  actions.hidden = !list.length;
  banner.hidden = false;
}

export { usd };
