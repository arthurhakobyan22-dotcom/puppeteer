// Entry point: loads the shared data (stages, presets, providers, costs), wires navigation and renders the view
// named in the URL. Views: quick (default), studio, lab, runs. A job is `?job=<32 hex>`.
import { api } from './api.js';
import { $, $$, showError, clearNotices } from './ui.js';
import { state, onRender, render, hrefFor, navigate } from './state.js';
import { resetJob, clearJobListeners, loadJob } from './jobdata.js';
import { renderQuick } from './quick.js';
import { renderStudio } from './studio.js';
import { renderLab } from './lab.js';
import { renderRuns } from './runs.js';
import { registerReviewTool } from './review.js';
import './wand.js';   // the mask wand registers itself as a review tool

async function loadShared() {
  const [stages, presets, providers, costs] = await Promise.allSettled([api.stages(), api.presets(), api.providers(), api.costs()]);
  if (stages.status === 'fulfilled') state.registry = stages.value;
  if (presets.status === 'fulfilled') state.presets = presets.value.presets || [];
  if (providers.status === 'fulfilled') { state.providers = providers.value.providers || {}; state.providerDefault = providers.value.default || ''; }
  if (costs.status === 'fulfilled') state.costs = costs.value;
  const failed = [stages, presets, providers, costs].find(r => r.status === 'rejected');
  if (failed) showError(failed.reason, { key: 'boot', actions: [{ label: 'Try again', run: async () => { await loadShared(); render(); } }] });
}

function renderView() {
  clearNotices(); clearJobListeners(); resetJob();
  for (const a of $$('nav.views a')) {
    a.classList.toggle('active', a.dataset.view === state.view);
    a.href = hrefFor({ view: a.dataset.view, job: ['quick', 'studio'].includes(a.dataset.view) ? state.jobId : null, runs: a.dataset.view === 'lab' ? state.labRuns : null });
  }
  const view = $('#view'); view.replaceChildren();
  document.title = 'Puppeteer · ' + state.view[0].toUpperCase() + state.view.slice(1) + (state.jobId ? ' · ' + state.jobId.slice(0, 8) : '');
  try {
    if (state.view === 'studio') renderStudio(view);
    else if (state.view === 'lab') renderLab(view);
    else if (state.view === 'runs') renderRuns(view);
    else renderQuick(view);
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

async function boot() {
  onRender(renderView);
  wireNavigation();
  await loadShared();
  render();
}

// For other modules (the mask wand) and for debugging in the console.
window.puppeteer = { state, api, navigate, loadJob, registerReviewTool };
boot();
