// Quick: upload, pick a preset, add the character, go. With a job in the URL it shows the simple four-step flow
// (progress, review, draft, finalize) and polls until the preparation finishes.
import { api, plain } from './api.js';
import { $, $$, el, usd, showError, tpl, wireUploads, videoSeconds, modeLabel } from './ui.js';
import { state, navigate } from './state.js';
import { onJobData, loadJob } from './jobdata.js';
import { mountRunHead } from './runhead.js';
import { mountReview } from './review.js';
import { mountDraft, mountFinal } from './draft.js';

/** Steps 02–04 for a job (shared by Quick and Studio): review, draft, final. */
export function mountPanels(container) {
  const review = mountReview(container);
  const draft = mountDraft(container);
  const final = mountFinal(container);
  return { update() { review.update(); draft.update(); final.update(); } };
}

/** The four-step flow for a job: header plus the panels. */
export function mountFlow(container, view) {
  const head = mountRunHead(container, { view });
  const panels = mountPanels(container);
  return { update() { head.update(); panels.update(); } };
}

export function renderQuick(container) {
  if (state.jobId) {
    const flow = mountFlow(container, 'quick');
    onJobData(() => flow.update());
    loadJob();
    return;
  }
  const node = tpl('tpl-quick'); container.append(node);
  const form = $('[data-form=quick]', node), go = $('[data-go]', node), costHint = $('[data-cost-hint]', node), presetsBox = $('[data-presets]', node);
  let seconds = null, pending = 0;

  const presets = state.presets || [];
  presets.forEach((p, i) => {
    const input = el('input', { type: 'radio', name: 'preset', value: p.name }); input.checked = i === 0;
    presetsBox.append(el('label', { class: 'preset' }, input, el('span', {}, el('strong', { text: p.name + (p.builtin ? '' : ' · saved') }), el('small', { text: p.description || modeLabel(p.mode) }), el('span', { class: 'cost', dataset: { presetCost: p.name }, text: '…' }))));
  });
  if (!presets.length) presetsBox.append(el('div', { class: 'empty', text: 'No presets could be loaded. Reload the page; if it happens again, check that the app is running.' }));

  function options() {
    return { prompt: form.prompt.value || 'person', provider: form.provider.value, clean_dialogue: form.clean_dialogue.checked ? 'true' : '' };
  }
  async function estimateAll() {
    // one estimate per preset for the cost line under its name (10 s clip until a file is chosen)
    await Promise.all(presets.map(async p => {
      const span = $$('[data-preset-cost]', presetsBox).find(s => s.dataset.presetCost === p.name);
      try { const r = await api.estimatePrep({ preset: p.name, seconds: seconds || 10, ...options() }); span.textContent = r.free ? 'free, runs locally' : usd(r.estimated_cost_usd) + (seconds ? '' : ' for a 10 s clip'); span.classList.toggle('paid', !r.free); }
      catch { span.textContent = ''; }
    }));
  }
  async function estimateGo() {
    const preset = form.preset && form.preset.value;
    if (!preset) { go.textContent = 'Prepare →'; return; }
    const mine = ++pending;
    try {
      const r = await api.estimatePrep({ preset, seconds: seconds || 10, ...options() });
      if (mine !== pending) return;
      go.dataset.paid = r.free ? '' : 'true';
      go.textContent = r.free ? 'Prepare · free, runs locally' : 'Prepare · ' + usd(r.estimated_cost_usd);
      costHint.textContent = r.free ? 'Nothing is sent to a paid service for this preset. The draft step is paid and shows its own estimate.'
        : 'Paid steps: ' + r.paid.map(p => p.label + ' ' + usd(p.estimated_cost_usd)).join(', ') + (seconds ? ' for this ' + seconds.toFixed(1) + ' s clip.' : ' for a 10 s clip; the exact estimate appears once you choose a video.') + ' One click confirms the cost and starts.';
    } catch (e) { if (mine !== pending) return; const p = plain(e); go.textContent = 'Prepare →'; costHint.textContent = 'The cost could not be estimated: ' + p.message + ' ' + p.fix; }
  }
  wireUploads(form, async (input, file) => { if (input.name === 'video') { seconds = await videoSeconds(file); estimateGo(); estimateAll(); } });
  form.addEventListener('change', e => { if (e.target.type !== 'file') { estimateGo(); if (['prompt', 'provider', 'clean_dialogue'].includes(e.target.name)) estimateAll(); } });
  estimateGo(); estimateAll();

  form.onsubmit = async e => {
    e.preventDefault();
    go.disabled = true;
    const data = new FormData(form);
    for (const name of ['char1', 'char2']) if (!form.elements[name].files.length) data.delete(name);
    data.set('confirm_cost', 'true');   // the button showed the estimate, so this click is the confirmation
    const submit = async () => { const r = await api.create(data); navigate({ job: r.id, view: 'quick' }); };
    try { await submit(); }
    catch (e2) { const p = plain(e2); showError(e2, { key: 'quick', actions: p.status === 402 ? [{ label: 'Prepare anyway · ' + usd(p.body.estimated_cost_usd), run: submit }] : [] }); go.disabled = false; }
  };
}
