// The workspace of one run: the run header (All runs, name with inline rename, status chip, spent, Compare, Details),
// the step rail (Prep · Edit · World & Look · Generate · Export, one line of status under each), the status line with
// the single "Next" button, and the five step bodies, one shown at a time. Each step is a history entry (state.goStep);
// `showStep()` switches without remounting, so the editor's videos survive Back / Forward.
import { api, plain } from './api.js';
import { $, $$, el, spent, usd, runName, runStatus, setChip, showError, notice, tpl, remember, runLabel, modeLabel, icon } from './ui.js';
import { state, navigate, setLabRuns, goStep, STEPS, hrefFor } from './state.js';
import { onJobData, loadJob } from './jobdata.js';
import { edits } from './editlayer.js';
import { mountPrep } from './prep.js';
import { mountEdit } from './edit.js';
import { mountWorld } from './world.js';
import { mountGenerate } from './generate.js';
import { mountExport } from './export.js';
import { openDetails, refreshDetails } from './drawer.js';

export const STEP_LABELS = { prep: 'Prep', edit: 'Edit', world: 'World & Look', generate: 'Generate', export: 'Export' };

/** The facts every step reads: prepared, approved, draft, final, running, failed, unsaved edits, estimates. */
export function facts() {
  const id = state.jobId, job = state.job || {}, files = state.files || new Set(), review = state.review || {};
  const run = (state.run && state.run.run) || {}, estimates = (state.run && state.run.estimates) || {};
  const provider = (state.generation && state.generation.provider) || state.providerDefault;
  const draftPrice = estimates.draft ? estimates.draft[provider] : null, finalPrice = estimates.complete ? estimates.complete[provider] : null;
  return {
    id, run, files, review, job,
    running: job.state === 'running', failed: job.state === 'error',
    prepared: files.has('seedance-input.mp4'), approved: !!review.approved,
    unsaved: edits.jobId === id ? (edits.pending.total || 0) : 0,
    draft: files.has('final-preview.mp4'), final: files.has('hd/final-preview.mp4'),
    hdRunning: !!(state.hd && state.hd.state === 'running'),
    draftPrice, finalPrice,
    summary: { id, name: run.name, preset: run.preset, mode: run.mode, created: run.created, parent: run.parent, changed: run.changed, state: job.state, reviewed: !!review.approved, draft: files.has('final-preview.mp4'), final: files.has('hd/final-preview.mp4'), request: files.has('seedance-response.json'), cost_usd_total: run.cost_usd_total },
  };
}

/** The most useful step to open when the URL names none. */
export function defaultStep(f) {
  if (f.running || f.failed || !f.prepared) return 'prep';
  if (!f.approved) return 'edit';
  return 'generate';
}

/** Per-step rail state and one-line status. */
export function stepStates(f, current) {
  const out = {};
  const lock = (key, reason) => { out[key] = { kind: 'locked', small: reason }; };
  if (f.failed) out.prep = { kind: 'failed', small: 'failed' };
  else if (f.running) out.prep = { kind: 'cur', small: 'preparing…' };
  else if (f.prepared) out.prep = { kind: 'done', small: f.run.preset || modeLabel(f.run.mode) };
  else out.prep = { kind: 'cur', small: 'not prepared yet' };
  if (!f.prepared) { lock('edit', 'after Prep'); lock('world', 'after Prep'); lock('generate', 'after approval'); lock('export', 'after Prep'); }
  else {
    out.edit = f.unsaved ? { kind: 'next', small: `${f.unsaved} unsaved edit${f.unsaved === 1 ? '' : 's'}`, badge: f.unsaved } : f.approved ? { kind: 'done', small: 'approved' } : { kind: 'next', small: 'needs review' };
    out.world = { kind: 'next', small: 'set · look · prompt' };
    out.generate = f.final ? { kind: 'done', small: 'final done' } : f.draft ? { kind: 'done', small: 'draft done' } : f.approved ? { kind: 'next', small: f.draftPrice != null ? usd(f.draftPrice) : 'ready' } : { kind: 'locked', small: 'after approval' };
    out.export = { kind: 'next', small: 'free' };
  }
  for (const key of STEPS) { if (key === current) out[key] = { ...out[key], kind: out[key].kind === 'failed' ? 'failed cur' : 'cur', small: out[key].small }; }
  return out;
}

/** The status sentence and the Next button of the current step (docs/UX-PLAN.md §7). */
export function statusFor(f, step) {
  const next = (label, to) => ({ label, to });
  if (step === 'prep') {
    if (f.running) return { kind: 'running', text: ['Preparing', (f.job.status || '') + ' · the clip opens in Edit when it is done'] };
    if (f.failed) return { kind: 'error', text: ['Preparation failed', 'fix it from Details · Stages, or start a new run'] };
    if (f.prepared) return { text: ['Prepared', 'now watch the clip and approve it'], next: next('Watch and approve the clip', 'edit') };
    return { text: ['Not prepared', 'the prepared files are not in this run'] };
  }
  if (step === 'edit') {
    if (!f.prepared) return { text: ['Edit', 'the clip opens here when the preparation finishes'] };
    if (f.unsaved) return { text: [`${f.unsaved} unsaved edit${f.unsaved === 1 ? '' : 's'}`, 'save them as a new version, then approve it'] };
    if (f.approved) return { text: ['Approved', 'choose the world and the prompt, or create the draft'], next: next('Next: World & Look', 'world') };
    return { text: ['Watch the whole clip', 'fix what is wrong on the lanes, then approve it below'] };
  }
  if (step === 'world') return f.approved ? { text: ['Prompt ready', 'create the draft'], next: next('Next: Generate', 'generate') } : { text: ['World & Look', 'set, look and light are saved with this run; approve the clip in Edit before the draft'], next: next('Next: Generate', 'generate') };
  if (step === 'generate') {
    if (f.hdRunning) return { kind: 'running', text: ['Final in progress', (state.hd && state.hd.status) || ''] };
    if (f.final) return { text: ['Final ready', 'download it or export'], next: next('Next: Export', 'export') };
    if (f.draft) return { text: ['Draft ready', 'judge it, then make the final or export the clip for another tool'], next: next('Next: Export', 'export') };
    if (!f.approved) return { text: ['No draft yet', 'approve the clip in Edit first'], next: next('Go to Edit', 'edit') };
    return { text: ['No draft yet', 'create the draft to judge the result; the price is on the button'] };
  }
  return { text: ['Export', 'pick the tool you take the files to; the zip is made on this computer, free'] };
}

export function mountWorkspace(container) {
  const head = tpl('tpl-ws-head'); container.append(head);
  const q = s => $(s, head);
  const rail = q('[data-rail]'), statusline = q('[data-statusline]'), statusText = q('[data-status-text]'), nextBox = q('[data-next]');
  const nameEl = q('[data-name]'), renameButton = q('[data-rename]'), renameForm = q('[data-rename-form]');
  for (const key of STEPS) rail.append(el('button', { type: 'button', class: 'rs', dataset: { go: key }, onclick: () => goStep(key) }, el('span', { class: 'dot', text: String(STEPS.indexOf(key) + 1) }), el('span', {}, STEP_LABELS[key], el('small'))));
  const bodies = {};
  const steps = { prep: mountPrep, edit: mountEdit, world: mountWorld, generate: mountGenerate, export: mountExport };
  const handles = {};
  for (const key of STEPS) {
    const body = el('div', { class: 'step-body', dataset: { body: key } }); container.append(body); bodies[key] = body;
    try { handles[key] = steps[key](body); } catch (e) { showError(e, { key: 'step-' + key }); handles[key] = { update() {} }; }
    remember(body);
  }
  let current = null, chosen = !!state.step;

  // rename
  renameButton.onclick = () => { renameForm.hidden = false; nameEl.hidden = true; renameButton.hidden = true; renameForm.name.value = (state.run && state.run.run && state.run.run.name) || ''; renameForm.name.placeholder = runName(facts().summary); renameForm.name.focus(); renameForm.name.select(); };
  const stopRename = () => { renameForm.hidden = true; nameEl.hidden = false; renameButton.hidden = false; renameButton.focus(); };
  q('[data-cancel]').onclick = stopRename;
  renameForm.name.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); stopRename(); } });
  renameForm.onsubmit = async e => {
    e.preventDefault();
    const button = renameForm.querySelector('button[type=submit]'); button.disabled = true;
    try { const r = await api.rename(state.jobId, renameForm.name.value); if (state.run && state.run.run) state.run.run.name = r.name; stopRename(); paintHead(); }
    catch (e2) { showError(e2, { key: 'rename' }); }
    finally { button.disabled = false; }
  };
  q('[data-compare]').onclick = () => { if (!state.labRuns.includes(state.jobId)) setLabRuns([...state.labRuns, state.jobId]); navigate({ view: 'compare', runs: state.labRuns, stage: state.labStage }); };
  q('[data-details]').onclick = e => openDetails({ id: state.jobId, source: e.currentTarget });

  function paintHead() {
    const f = facts();
    const name = runName(f.summary); nameEl.textContent = name; document.title = 'Puppeteer · ' + (current ? STEP_LABELS[current] + ' · ' : '') + name;
    const st = runStatus(f.summary); setChip(q('[data-state]'), st.key, st.text);
    q('[data-spent]').textContent = spent(f.run.cost_usd_total);
  }

  function paintRail() {
    const f = facts(), states = stepStates(f, current);
    for (const b of $$('.rs', rail)) {
      const key = b.dataset.go, s = states[key];
      b.className = 'rs ' + s.kind; b.querySelector('small').textContent = key === current ? ('you are here' + (s.small && !/here/.test(s.small) ? ' · ' + s.small : '')) : s.small;
      if (key === current) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
      b.querySelector('.dot').textContent = s.kind.startsWith('done') ? '✓' : String(STEPS.indexOf(key) + 1);
      const old = b.querySelector('.badge'); if (old) old.remove();
      if (s.badge) b.append(el('span', { class: 'badge', text: String(s.badge) }));
      b.title = s.kind === 'locked' ? STEP_LABELS[key] + ' · ' + s.small : STEP_LABELS[key];
    }
    const s = statusFor(f, current);
    statusline.className = 'statusline' + (s.kind ? ' ' + s.kind : '');
    statusText.replaceChildren(el('b', { text: s.text[0] }), s.text[1] ? ' · ' + s.text[1] : '');
    nextBox.replaceChildren();
    if (s.next) nextBox.append(el('button', { type: 'button', class: 'sm', onclick: () => goStep(s.next.to) }, s.next.label + ' ', icon('arrow')));
  }

  function showStep(step) {
    const f = facts();
    if (!step) { step = defaultStep(f); if (state.run) history.replaceState(null, '', hrefFor({ job: state.jobId, step })); }
    if (!STEPS.includes(step)) step = 'prep';
    current = step;
    for (const [key, body] of Object.entries(bodies)) body.classList.toggle('on', key === step);
    paintHead(); paintRail();
    const h = handles[step]; if (h && h.shown) { try { h.shown(); } catch (e) { showError(e); } }
  }

  function update() {
    const f = facts();
    if (!current || (!chosen && !state.step)) showStep(state.step || defaultStep(f)); else { paintHead(); paintRail(); }
    chosen = chosen || !!state.step;
    for (const key of STEPS) { try { handles[key].update(); } catch (e) { showError(e, { key: 'step-' + key }); } }
    paintRail();
    refreshDetails(state.jobId);
  }
  edits.on('change', () => { if (edits.jobId === state.jobId && state.run) paintRail(); });
  onJobData(update);
  loadJob();
  if (state.details) openDetails({ id: state.jobId, tab: state.details });
  return { showStep(step) { chosen = true; showStep(step); }, update };
}

export { runLabel, plain, notice };
