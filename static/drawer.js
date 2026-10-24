// The Details drawer (level 3): ONE right-side drawer, the same on every step and on every Runs card. Tabs: Run (id,
// based on, prep method, frames, face found / filled / lost, generator, folder, approval) · Stages (the nine stage
// rows from stagecard.js: method, settings, health, numbers, warnings, previews, "Make a new version from here",
// "Use my own file…") · Reports & log (report.json per stage, run.json, log.txt, calls.jsonl) · Costs (spent, per
// stage, what the next steps cost). Esc closes and focus returns to the button that opened it. The last tab is
// remembered (localStorage pp-details-tab).
import { api, plain } from './api.js';
import { $, $$, el, spent, usd, when, ranges, shortId, runName, modeLabel, stageName, methodName, showError, notice, stored, runThumb } from './ui.js';
import { state, runHref } from './state.js';
import { mountStageCard } from './stagecard.js';

const TABS = ['run', 'stages', 'reports', 'costs'];
const d = { open: false, id: null, tab: 'run', source: null, data: null, cards: [], token: 0, stage: null };

function drawer() { return $('#details'); }

export function initDrawer() {
  const dr = drawer(); if (!dr) return;
  $('#details-close').onclick = closeDetails;
  $('#scrim').onclick = closeDetails;
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && d.open) { const t = e.target; if (t && (t.closest && t.closest('.toast'))) return; e.preventDefault(); closeDetails(); } });
  for (const b of $$('.tabs button', dr)) b.onclick = () => selectTab(b.dataset.tab);
  d.tab = TABS.includes(stored('details-tab')) ? stored('details-tab') : 'run';
}

function selectTab(tab) {
  d.tab = TABS.includes(tab) ? tab : 'run'; stored('details-tab', d.tab);
  for (const b of $$('.tabs button', drawer())) { b.classList.toggle('on', b.dataset.tab === d.tab); b.setAttribute('aria-selected', b.dataset.tab === d.tab ? 'true' : 'false'); }
  render();
}

/** Open the drawer for run `id` (defaults to the run in the URL); `tab` picks a tab, `stage` expands one stage row. */
export async function openDetails({ id = state.jobId, tab = null, stage = null, source = null } = {}) {
  const dr = drawer(); if (!dr || !id) return;
  d.source = source || (document.activeElement && document.activeElement !== document.body ? document.activeElement : null);
  const changed = d.id !== id; d.id = id; d.stage = stage || null;
  if (tab) d.tab = TABS.includes(tab) ? tab : d.tab;
  document.body.classList.add('details-open'); dr.setAttribute('aria-hidden', 'false'); d.open = true;
  for (const b of $$('.tabs button', dr)) { b.classList.toggle('on', b.dataset.tab === d.tab); b.setAttribute('aria-selected', b.dataset.tab === d.tab ? 'true' : 'false'); }
  if (changed || !d.data) { d.data = null; d.cards = []; render(); await load(); } else render();
  $('#details-close').focus();
}

export function closeDetails() {
  const dr = drawer(); if (!dr || !d.open) return;
  document.body.classList.remove('details-open'); dr.setAttribute('aria-hidden', 'true'); d.open = false;
  if (d.source && d.source.isConnected && d.source.focus) d.source.focus();
  d.source = null;
}

/** The workspace calls this after every job load: the drawer re-reads the live state when it shows the same run. */
export function refreshDetails(id) {
  if (!d.open || d.id !== id) return;
  if (id === state.jobId && state.run) { d.data = fromState(); render(); }
}

function fromState() {
  return { id: state.jobId, info: state.run, files: state.files || new Set(), job: state.job || {}, review: state.review || {}, tracking: state.tracking, generation: state.generation, live: true };
}

async function load() {
  const id = d.id, token = ++d.token;
  if (id === state.jobId && state.run) { d.data = fromState(); render(); return; }
  try {
    const [info, files, review] = await Promise.all([api.run(id), api.files(id), api.review(id).catch(() => ({}))]);
    if (token !== d.token) return;
    const set = new Set(files.files || []);
    const [tracking, generation, job] = await Promise.all([
      set.has('face-tracking.json') ? api.runFile(id, 'face-tracking.json').catch(() => null) : null,
      set.has('generation.json') ? api.runFile(id, 'generation.json').catch(() => null) : null,
      api.job(id).catch(() => info.status || {}),
    ]);
    if (token !== d.token) return;
    d.data = { id, info, files: set, job: job || {}, review, tracking, generation, live: false };
    render();
  } catch (e) { if (token === d.token) { showError(e, { key: 'details' }); d.data = { id, failed: true }; render(); } }
}

/** A `src` for stage cards: getters over the drawer's data (the live state for the open run). */
function src() {
  return { id: () => d.id, info: () => (d.data && d.data.info) || { run: {}, reports: {} }, files: () => (d.data && d.data.files) || new Set(), job: () => (d.data && d.data.job) || {} };
}

const kv = pairs => el('dl', { class: 'kv' }, pairs.filter(Boolean).flatMap(([k, v, ui]) => [el('dt', { text: k }), el('dd', { class: ui ? 'ui' : '' }, v)]));
const frameFacts = data => {
  const reports = (data.info && data.info.reports) || {}, norm = reports.input_doctor && reports.input_doctor.data && reports.input_doctor.data.normalized;
  const t = data.tracking, seconds = data.info && data.info.seconds;
  const frames = (norm && norm.frames) || (t && t.frames) || null, fps = (norm && norm.fps) || (t && t.fps) || 24;
  if (!frames) return seconds ? `${Number(seconds).toFixed(2)} s` : '—';
  return `${frames} · ${fps} fps · ${(frames / fps).toFixed(2)} s` + (norm && norm.width ? ` · ${norm.width} × ${norm.height}` : '');
};

function render() {
  const dr = drawer(); if (!dr) return;
  const body = $('[data-body]', dr), data = d.data;
  const title = $('#details-title');
  if (!data) { title.textContent = 'Details'; body.replaceChildren(el('div', { class: 'skel' }, el('i', { style: 'width:60%' }), el('i', { style: 'width:90%' }), el('i', { style: 'width:40%' }))); return; }
  if (data.failed) { title.textContent = 'Details'; body.replaceChildren(el('p', { class: 'line error', text: 'The run could not be read.' })); return; }
  const run = (data.info && data.info.run) || {}, reports = (data.info && data.info.reports) || {}, files = data.files, id = data.id;
  const summary = { id, name: run.name, preset: run.preset, mode: run.mode, created: run.created, parent: run.parent, changed: run.changed };
  title.textContent = runName(summary);
  body.replaceChildren();
  if (d.tab === 'run') {
    const copy = el('button', { type: 'button', class: 'ghost sm', text: 'copy', onclick: async e => { try { await navigator.clipboard.writeText(id); e.target.textContent = 'copied'; setTimeout(() => { e.target.textContent = 'copy'; }, 1500); } catch { notice('Copy failed; select the id and copy it by hand.', { kind: 'warn', key: 'copy' }); } } });
    const t = data.tracking, face = t && t.frames ? `${t.tracked} found · ${t.filled || 0} filled · ${t.missing || 0} lost` + ((t.gaps || []).length ? ` · lost ${ranges(t.gaps)}` : '') : null;
    const gen = data.generation ? ((state.providers[data.generation.provider] || {}).label || data.generation.provider) + (data.generation.mode ? ' · ' + (data.generation.mode === 'multi_reference' ? 'reference mode (character video)' : 'edit mode') : '') : null;
    const review = data.review || {};
    body.append(el('section', {}, el('h4', { text: 'Run' }), kv([
      ['Run id', el('span', {}, id, ' ', copy)],
      ['Name', run.name || '— (default name shown)', true],
      ['Based on', run.parent ? el('a', { href: runHref(run.parent), 'data-nav': true, text: shortId(run.parent) + '…', onclick: closeDetails }) : '— (an original run)', !run.parent],
      run.changed ? ['What changed', run.changed, true] : null,
      ['Prep method', modeLabel(run.mode) + (run.preset ? ' · preset ' + run.preset : ''), true],
      ['Frames', frameFacts(data)],
      face ? ['Face', face] : null,
      gen ? ['Generator', gen, true] : null,
      ['Made', when(run.created || (data.info && data.info.status && data.info.status.created)), true],
      ['Folder', 'runs/' + id],
      ['Approval', review.approved ? 'approved' + (review.fingerprint ? ' · for clip ' + String(review.fingerprint).slice(0, 8) + '…' : '') : (review.status || 'not approved'), true],
      data.info && data.info.migrated ? ['Record', 'reconstructed: this run was made before run records existed', true] : null,
    ])));
    body.append(el('section', {}, el('h4', { text: 'Open' }), el('div', { class: 'row' }, el('a', { class: 'btn sm', href: runHref(id), 'data-nav': true, text: 'Open the workspace', onclick: closeDetails }), el('a', { class: 'btn ghost sm', href: '/runs/' + id + '/run.json', target: '_blank', rel: 'noopener', text: 'run.json' }))));
  } else if (d.tab === 'stages') {
    const registry = state.registry || { stages: [] };
    body.append(el('p', { class: 'hint', text: 'One row per stage, in the order they run. Change a method or a setting and make a new version from that stage: this run stays as it is, and finished paid stages are reused, never billed twice.' }));
    const list = el('div', { class: 'stages-list' }); body.append(list);
    d.cards = registry.stages.map((s, i) => mountStageCard(list, s, i, src(), { onBranch: closeDetails }));
    if (!registry.stages.length) list.append(el('div', { class: 'empty sm', text: 'The stage list could not be loaded. Reload the page.' }));
    const job = data.job || {}, running = job.state === 'running';
    const active = running ? registry.stages.map(s => s.name).find(name => !reports[name]) : null;
    d.cards.forEach(c => c.update({ active: c.stage === active }));
    if (d.stage) { const card = d.cards.find(c => c.stage === d.stage); if (card) { card.node.open = true; setTimeout(() => card.node.scrollIntoView({ block: 'start' }), 50); } d.stage = null; }
  } else if (d.tab === 'reports') {
    const calls = (data.info && data.info.calls) || [];
    const links = el('div', { class: 'downloads' },
      el('a', { href: '/runs/' + id + '/run.json', target: '_blank', rel: 'noopener', text: 'run.json' }),
      files.has('status.json') ? el('a', { href: '/runs/' + id + '/status.json', target: '_blank', rel: 'noopener', text: 'status.json' }) : null,
      files.has('log.txt') ? el('a', { href: '/runs/' + id + '/log.txt', target: '_blank', rel: 'noopener', text: 'log.txt' }) : null,
      files.has('calls.jsonl') ? el('a', { href: '/runs/' + id + '/calls.jsonl', target: '_blank', rel: 'noopener', text: `calls.jsonl (${calls.length} external call${calls.length === 1 ? '' : 's'})` }) : el('span', { class: 'hint', text: 'no external calls recorded' }),
      files.has('face-tracking.json') ? el('a', { href: '/runs/' + id + '/face-tracking.json', target: '_blank', rel: 'noopener', text: 'face-tracking.json' }) : null,
      files.has('mask-cleanup-report.json') ? el('a', { href: '/runs/' + id + '/mask-cleanup-report.json', target: '_blank', rel: 'noopener', text: 'mask-cleanup-report.json' }) : null,
      files.has('sam-report.json') ? el('a', { href: '/runs/' + id + '/sam-report.json', target: '_blank', rel: 'noopener', text: 'sam-report.json' }) : null,
      files.has('generation.json') ? el('a', { href: '/runs/' + id + '/generation.json', target: '_blank', rel: 'noopener', text: 'generation.json' }) : null,
      files.has('seedance-request.json') ? el('a', { href: '/runs/' + id + '/seedance-request.json', target: '_blank', rel: 'noopener', text: 'seedance-request.json' }) : null,
      files.has('seedance-response.json') ? el('a', { href: '/runs/' + id + '/seedance-response.json', target: '_blank', rel: 'noopener', text: 'seedance-response.json' }) : null);
    body.append(el('section', {}, el('h4', { text: 'Files' }), links));
    const perStage = Object.keys(reports).map(name => el('li', {}, el('a', { href: '/runs/' + id + '/stages/' + name + '/report.json', target: '_blank', rel: 'noopener', text: stageName(name) + ' · report.json' }), ' ', el('span', { class: 'hint', text: (reports[name] && reports[name].health) || '' })));
    if (perStage.length) body.append(el('section', {}, el('h4', { text: 'Stage reports' }), el('ul', { class: 'checklist' }, perStage)));
    if (files.has('log.txt')) {
      const pre = el('pre', { class: 'log', text: 'Loading log.txt…' }); body.append(el('section', {}, el('h4', { text: 'Log · last lines' }), pre));
      fetch('/runs/' + id + '/log.txt', { cache: 'no-store' }).then(r => r.ok ? r.text() : '').then(t => { const lines = t.trim().split('\n'); pre.textContent = lines.slice(-60).join('\n') || 'The log is empty.'; pre.scrollTop = pre.scrollHeight; }).catch(() => { pre.textContent = 'The log could not be read.'; });
    }
  } else {
    const rows = Object.entries(reports).map(([name, r]) => el('li', {}, el('span', { class: 'n', text: stageName(name) }), el('span', { text: ' · ' + methodName(r.tool, r.tool) }), el('span', { class: 'c' + (Number(r.cost_usd || 0) > 0 ? ' paid' : ''), text: ' · ' + (Number(r.cost_usd || 0) > 0 ? spent(r.cost_usd) : 'free') + (r.cached_from ? ' · reused from ' + shortId(r.cached_from) + '…, nothing re-billed' : '') })));
    const est = (data.info && data.info.estimates) || {}, provider = (data.generation && data.generation.provider) || state.providerDefault;
    body.append(el('section', {}, el('h4', { text: 'Costs' }), kv([
      ['Spent', spent(run.cost_usd_total)],
      est.draft && est.draft[provider] != null ? ['Draft', usd(est.draft[provider]) + ' · ' + ((state.providers[provider] || {}).label || provider), true] : null,
      est.complete && est.complete[provider] != null ? ['Final', usd(est.complete[provider]) + ' · 1080p', true] : null,
    ]), rows.length ? el('ul', { class: 'checklist', style: 'list-style:none;padding:0;display:grid;gap:4px' }, rows) : el('p', { class: 'hint', text: 'No stage reports yet.' })));
    if (est.note) body.append(el('p', { class: 'hint', text: est.note }));
  }
}

export { plain, runThumb };
