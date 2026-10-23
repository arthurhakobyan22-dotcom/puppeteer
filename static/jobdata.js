// Loading and polling the job named in the URL. The job banner is written only from here, only after checking
// that the answer still belongs to the job in the URL (token + id), so another run's status can never leak in.
import { api, plain } from './api.js';
import { $, $$, el, usd } from './ui.js';
import { state, later, current, navigate } from './state.js';

const POLL_MS = 2500;
let listeners = [];
/** Views register one callback that re-renders their job panels after a (re)load. */
export function onJobData(fn) { listeners = [fn]; }
export function clearJobListeners() { listeners = []; }

export function resetJob() {
  Object.assign(state, { job: null, run: null, files: new Set(), review: null, tracking: null, generation: null, hd: null });
  renderBanner();
}

/** The status dict of the job: the live job, else the saved status, else what run.json says. */
async function fetchStatus(id) {
  try { return await api.job(id); }
  catch (e) {
    const p = plain(e);
    if (p.status === 404) {
      if (state.run && state.run.status) return state.run.status;
      return { state: 'unknown', status: 'No status was saved for this run (it was interrupted before preparation finished).', fix: 'Open it in Studio and re-run the stage that did not finish.' };
    }
    throw e;
  }
}

/** Load everything the panels need for the job in the URL. Safe to call again; results are dropped when the page moved on. */
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
}

/** While the job runs: refresh its status (and the stage reports) every few seconds; on completion reload everything. */
async function poll() {
  const id = state.jobId; const token = state.token;
  if (!id) return;
  let status;
  try { status = await fetchStatus(id); }
  catch (e) { if (!current(token, id)) return; later(() => poll(), POLL_MS * 2); return; }   // a glitch: keep polling, never show another job's words
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

/** Fix actions for a failed job: open the failed stage in Studio; for a strict face-tracking failure, re-run leniently (free). */
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
      navigate({ job: r.id, view: state.view === 'studio' ? 'studio' : 'quick' });
    } });
  }
  if (stage && state.view !== 'studio') actions.push({ label: 'Open the failed stage in Studio', secondary: true, run: async () => navigate({ job: state.jobId, view: 'studio' }, { hash: 'stage-' + stage }) });
  return actions;
}

/** The banner shows the status of the job in the URL and nothing else. */
export function renderBanner() {
  const banner = $('#job-banner');
  if (!banner) return;
  const job = state.jobId ? state.job : null;
  if (!job) { banner.hidden = true; return; }
  const text = $('[data-text]', banner), fix = $('[data-fix]', banner), actions = $('[data-actions]', banner);
  const kind = job.state === 'error' ? 'error' : job.state === 'running' ? 'running' : job.state === 'done' ? 'done' : '';
  banner.className = 'status ' + kind;
  text.textContent = job.status || (job.state === 'running' ? 'Working…' : job.state || '');
  const fixText = job.state === 'error' ? (job.fix || (job.unreachable ? '' : 'Re-run the stage that failed from Studio; where the app can do it for you, a button is shown below.')) : '';
  fix.textContent = fixText; fix.hidden = !fixText;
  actions.replaceChildren();
  const list = job.state === 'error' && !job.unreachable ? fixActions() : [];
  for (const a of list) actions.append(el('button', { type: 'button', class: 'small ' + (a.secondary ? 'secondary' : ''), text: a.label, onclick: async (ev) => { ev.target.disabled = true; try { await a.run(); } catch (e) { const { showError } = await import('./ui.js'); showError(e); ev.target.disabled = false; } } }));
  actions.hidden = !list.length;
  banner.hidden = false;
}

export { usd };
