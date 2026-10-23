// Studio: the run as a vertical rack of stage cards, then the review / draft / final panels, then the legacy
// "Preparation method" form for a new run.
import { api, plain } from './api.js';
import { $, el, usd, showError, tpl, wireUploads, videoSeconds } from './ui.js';
import { state, navigate } from './state.js';
import { onJobData, loadJob } from './jobdata.js';
import { mountStageCard } from './stagecard.js';
import { mountPanels } from './quick.js';
import { mountRunHead } from './runhead.js';

/** The legacy form: Preparation method (mode) + subject + provider + clean dialogue; the button shows the estimate. */
export function mountLegacyForm(container) {
  const node = tpl('tpl-studio-new'); container.append(node);
  const form = $('[data-form=legacy]', node), go = $('[data-go]', node), costHint = $('[data-cost-hint]', node);
  let seconds = null, pending = 0;
  async function estimate() {
    const mine = ++pending;
    try {
      const r = await api.estimatePrep({ mode: form.mode.value, seconds: seconds || 10, prompt: form.prompt.value || 'person', provider: form.provider.value, clean_dialogue: form.clean_dialogue.checked ? 'true' : '' });
      if (mine !== pending) return;
      go.textContent = r.free ? 'Prepare video · free, runs locally' : 'Prepare video · ' + usd(r.estimated_cost_usd);
      costHint.textContent = r.free ? 'Nothing is sent to a paid service for this method.' : 'Paid steps: ' + r.paid.map(p => p.label + ' ' + usd(p.estimated_cost_usd)).join(', ') + (seconds ? ' for this ' + seconds.toFixed(1) + ' s clip.' : ' for a 10 s clip.') + ' One click confirms the cost and starts.';
    } catch (e) { if (mine !== pending) return; const p = plain(e); go.textContent = 'Prepare video →'; costHint.textContent = 'The cost could not be estimated: ' + p.message + ' ' + p.fix; }
  }
  wireUploads(form, async (input, file) => { if (input.name === 'video') { seconds = await videoSeconds(file); estimate(); } });
  form.addEventListener('change', e => { if (e.target.type !== 'file') estimate(); });
  estimate();
  form.onsubmit = async e => {
    e.preventDefault(); go.disabled = true;
    const data = new FormData(form); data.set('confirm_cost', 'true');
    const submit = async () => { const r = await api.create(data); navigate({ job: r.id, view: 'studio' }); };
    try { await submit(); }
    catch (e2) { const p = plain(e2); showError(e2, { key: 'legacy', actions: p.status === 402 ? [{ label: 'Prepare anyway · ' + usd(p.body.estimated_cost_usd), run: submit }] : [] }); go.disabled = false; }
  };
  return node;
}

export function renderStudio(container) {
  if (!state.jobId) {
    container.append(el('div', { class: 'hero' }, el('div', {}, el('span', { class: 'eyebrow', text: 'Studio · every stage, one card each' }), el('h1', { text: 'Open a run to see its stage rack.' }),
      el('p', {}, 'Choose a run on the ', el('a', { href: '/?view=runs', 'data-nav': true, text: 'Runs page' }), ', or prepare a new video below with the preparation method of your choice.'))));
    mountLegacyForm(container);
    return;
  }
  const registry = state.registry || { stages: [] };
  const rackPanel = el('section', { class: 'panel', id: 'rack' }, el('div', { class: 'heading' }, el('span', { class: 'number', text: '⋮' }), el('h2', { text: 'Stage rack' })),
    el('p', { class: 'hint', text: 'One card per stage, in the order they run. Change a tool or a setting and click "Re-run from here": that makes a new branch run from this one; this run stays as it is, and finished paid steps are reused, never billed again.' }));
  const rack = el('div', { class: 'rack' }); rackPanel.append(rack);
  const head = mountRunHead(container, { view: 'studio' });
  container.append(rackPanel);
  const cards = registry.stages.map((s, i) => mountStageCard(rack, s, i));
  const panels = mountPanels(container);
  if (!registry.stages.length) rack.append(el('div', { class: 'empty', text: 'The stage list could not be loaded. Reload the page; if it happens again, check that the app is running.' }));
  const more = el('details', {}, el('summary', { text: 'Prepare another video (preparation method)' }));
  container.append(el('section', { class: 'panel' }, more));
  mountLegacyForm(more).classList.remove('panel');
  let scrolled = false;
  onJobData(() => {
    const reports = (state.run && state.run.reports) || {};
    const running = state.job && state.job.state === 'running';
    const active = running ? registry.stages.map(s => s.name).find(name => !reports[name]) : null;
    cards.forEach(c => c.update({ active: c.stage === active }));
    head.update(); panels.update();
    if (!scrolled && location.hash) { scrolled = true; const target = document.getElementById(location.hash.slice(1)); if (target) { target.scrollIntoView({ block: 'start' }); setTimeout(() => target.scrollIntoView({ block: 'start' }), 400); } }
  });
  loadJob();
}
