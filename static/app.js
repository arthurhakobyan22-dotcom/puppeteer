// Entry point: loads the shared data (stages, presets, providers, costs), wires navigation, the theme toggle and the
// Details drawer, and renders the screen named in the URL. Screens: Runs (default), New run, the Workspace of one
// run (`?job=<32 hex>&step=…`) and Compare. A step switch inside the same run does not remount the workspace (the
// editor's videos stay alive); only a different run or screen does.
import { api } from './api.js';
import { $, $$, showError, clearNotices } from './ui.js';
import { state, onRender, render, hrefFor, navigate, stopTimers, goStep } from './state.js';
import { resetJob, clearJobListeners, loadJob } from './jobdata.js';
import { renderRuns } from './runs.js';
import { renderStart } from './start.js';
import { mountWorkspace } from './workspace.js';
import { renderCompare } from './compare.js';
import { initDrawer, openDetails, closeDetails } from './drawer.js';
import { registerReviewTool } from './edit.js';

async function loadShared() {
  const [stages, presets, providers, costs] = await Promise.allSettled([api.stages(), api.presets(), api.providers(), api.costs()]);
  if (stages.status === 'fulfilled') state.registry = stages.value;
  if (presets.status === 'fulfilled') state.presets = presets.value.presets || [];
  if (providers.status === 'fulfilled') { state.providers = providers.value.providers || {}; state.providerDefault = providers.value.default || ''; }
  if (costs.status === 'fulfilled') state.costs = costs.value;
  const failed = [stages, presets, providers, costs].find(r => r.status === 'rejected');
  if (failed) showError(failed.reason, { key: 'boot', actions: [{ label: 'Try again', run: async () => { await loadShared(); render(); } }] });
}

let mounted = { key: '', handle: null };

function renderHeader() {
  for (const a of $$('nav.pages a')) {
    const v = a.dataset.view;
    a.classList.toggle('active', v === state.view);
    if (v === 'workspace') { a.hidden = !state.jobId; a.href = hrefFor({ job: state.jobId }); }
    else if (v === 'compare') a.href = hrefFor({ view: 'compare', runs: state.labRuns, stage: state.labStage });
    else a.href = hrefFor({ view: v });
  }
}

function renderView() {
  const key = state.view + '|' + (state.jobId || '');
  renderHeader();
  if (key === mounted.key && mounted.handle && mounted.handle.showStep && state.view === 'workspace') {   // same run: only the step (and the drawer) change
    mounted.handle.showStep(state.step);
    if (state.details) openDetails({ id: state.jobId, tab: state.details });
    return;
  }
  stopTimers(); clearNotices(); clearJobListeners(); resetJob(); closeDetails();
  const view = $('#view'); view.replaceChildren();
  mounted = { key, handle: null };
  document.title = 'Puppeteer · ' + ({ runs: 'Runs', new: 'New run', compare: 'Compare', workspace: 'Run' })[state.view];
  try {
    if (state.view === 'compare') renderCompare(view);
    else if (state.view === 'new') renderStart(view);
    else if (state.view === 'workspace') mounted.handle = mountWorkspace(view);
    else renderRuns(view);
  } catch (e) { showError(e); }
  if (!location.hash) window.scrollTo(0, 0);
}

function wireNavigation() {
  document.addEventListener('click', e => {
    const a = e.target.closest('a[data-nav]');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || a.target === '_blank') return;
    const href = a.getAttribute('href');
    if (!href || !href.startsWith('/')) return;
    e.preventDefault();
    history.pushState(null, '', href);
    render();
  });
  window.addEventListener('popstate', render);
}

function wireTheme() {
  const button = $('#theme'); if (!button) return;
  const paint = () => { const light = document.documentElement.getAttribute('data-theme') === 'light'; button.setAttribute('aria-label', light ? 'Switch to the dark theme' : 'Switch to the light theme'); };
  button.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('pp-theme', next); } catch { /* private mode */ }
    paint();
  });
  paint();
}

async function boot() {
  onRender(renderView);
  wireNavigation(); wireTheme(); initDrawer();
  await loadShared();
  render();
}

// For other modules (the mask tools) and for debugging in the console.
window.puppeteer = Object.assign(window.puppeteer || {}, { state, api, navigate, loadJob, registerReviewTool, goStep, openDetails });
boot();
