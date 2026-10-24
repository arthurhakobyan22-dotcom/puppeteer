// New run (Quick start): preset cards (the free one preselected), Character 1 / 2, More options (subject to mask,
// depth model, clean dialogue, prep method), then the clip. Choosing the clip with a free preset starts the
// preparation at once ("Preparing with Talking head · free"); a paid preset shows "Prepare · about $x" and needs that
// click (the price on the button is the confirmation, docs/UI.md §7). Submits POST /jobs and opens the workspace.
import { api, plain } from './api.js';
import { $, $$, el, usd, showError, tpl, wireUploads, videoSeconds, modeLabel, remember, costActions, withCost } from './ui.js';
import { state, navigate } from './state.js';

export function renderStart(container) {
  const node = tpl('tpl-start'); container.append(node); remember(node);
  const form = $('[data-form=start]', node), go = $('[data-go]', node), goRow = $('[data-go-row]', node), costHint = $('[data-cost-hint]', node), autoHint = $('[data-auto-hint]', node), presetsBox = $('[data-presets]', node), clipTitle = $('[data-clip-title]', node);
  let seconds = null, pending = 0, estimate = null, hasClip = false, submitting = false;

  const presets = state.presets || [];
  presets.forEach((p, i) => {
    const input = el('input', { type: 'radio', name: 'preset', value: p.name }); input.checked = i === 0;
    presetsBox.append(el('label', { class: 'preset' }, input, el('span', {}, el('strong', { text: p.name + (p.builtin ? '' : ' · saved') }), el('small', { text: plainDescription(p) }), el('span', { class: 'cost', dataset: { presetCost: p.name }, text: '…' }))));
  });
  if (!presets.length) presetsBox.append(el('div', { class: 'empty sm', text: 'No presets could be loaded. Reload the page; if it happens again, check that the app is running.' }));

  function options() {
    return { prompt: form.prompt.value || 'person', provider: form.provider.value, clean_dialogue: form.clean_dialogue.checked ? 'true' : '' };
  }
  const chosen = () => form.mode.value ? { mode: form.mode.value } : { preset: form.preset && form.preset.value };
  async function estimateAll() {
    await Promise.all(presets.map(async p => {
      const span = $$('[data-preset-cost]', presetsBox).find(s => s.dataset.presetCost === p.name);
      try { const r = await api.estimatePrep({ preset: p.name, seconds: seconds || 10, ...options() }); span.textContent = r.free ? 'free, runs locally' : usd(r.estimated_cost_usd) + (seconds ? '' : ' for a 10 s clip'); span.classList.toggle('paid', !r.free); }
      catch { span.textContent = ''; }
    }));
  }
  async function estimateGo() {
    const pick = chosen();
    if (!pick.preset && !pick.mode) { estimate = null; paint(); return; }
    const mine = ++pending;
    try {
      const r = await api.estimatePrep({ ...pick, seconds: seconds || 10, ...options() });
      if (mine !== pending) return;
      estimate = r; paint();
    } catch (e) { if (mine !== pending) return; estimate = { error: plain(e) }; paint(); }
  }
  function label() { const pick = chosen(); return pick.mode ? modeLabel(pick.mode) : pick.preset || 'the preset'; }
  function paint() {
    const free = estimate && estimate.free, paid = estimate && !estimate.free && !estimate.error;
    if (submitting) { autoHint.textContent = 'Preparing with ' + label() + ' · ' + (free ? 'free' : usd(estimate && estimate.estimated_cost_usd)) + '…'; goRow.hidden = true; return; }
    clipTitle.textContent = hasClip ? 'Clip chosen' : 'Choose the clip';
    if (!estimate) { autoHint.textContent = ''; goRow.hidden = !hasClip; withCost(go, 'Prepare', ''); costHint.textContent = ''; return; }
    if (estimate.error) { autoHint.textContent = ''; goRow.hidden = !hasClip; withCost(go, 'Prepare', ''); costHint.textContent = 'The price could not be worked out: ' + estimate.error.message + ' ' + estimate.error.fix; return; }
    if (free) {
      autoHint.textContent = hasClip ? '' : 'Choosing the clip starts the free preparation with ' + label() + ' on this computer; nothing is sent anywhere. The draft step is paid and shows its own price.';
      goRow.hidden = !hasClip; withCost(go, 'Prepare', 'free, runs locally'); costHint.textContent = '';
    } else if (paid) {
      autoHint.textContent = hasClip ? '' : 'Choose the clip, then confirm the price: ' + label() + ' is ' + usd(estimate.estimated_cost_usd) + (seconds ? '' : ' for a 10 s clip') + '.';
      goRow.hidden = !hasClip; withCost(go, 'Prepare', usd(estimate.estimated_cost_usd));
      costHint.textContent = 'Paid steps: ' + estimate.paid.map(p => p.label + ' ' + usd(p.estimated_cost_usd)).join(', ') + (seconds ? ' for this ' + seconds.toFixed(1) + ' s clip.' : ' for a 10 s clip.') + ' The click on the button is the confirmation.';
    }
  }
  wireUploads(form, async (input, file) => {
    if (input.name !== 'video') return;
    hasClip = !!file; seconds = await videoSeconds(file);
    await estimateGo(); estimateAll();
    if (hasClip && estimate && estimate.free && !estimate.error) submit();   // the free path: the clip is the last click
  });
  form.addEventListener('change', e => { if (e.target.type !== 'file') { estimateGo(); if (['prompt', 'provider', 'clean_dialogue', 'mode'].includes(e.target.name)) estimateAll(); } });
  estimateGo(); estimateAll();

  async function submit(confirm = true) {
    if (submitting) return;
    submitting = true; go.disabled = true; paint();
    const data = new FormData(form);
    for (const name of ['char1', 'char2']) if (!form.elements[name].files.length) data.delete(name);
    if (form.mode.value) data.delete('preset'); else data.delete('mode');
    if (confirm) data.set('confirm_cost', 'true');   // the button (or the hint) showed the price, so this click is the confirmation
    const send = async () => { const r = await api.create(data); navigate({ job: r.id, step: 'prep' }); };
    try { await send(); }
    catch (e2) { submitting = false; go.disabled = false; paint(); showError(e2, { key: 'start', actions: costActions(e2, send) }); }
  }
  form.onsubmit = e => { e.preventDefault(); if (!form.video.files.length) { form.video.focus(); return; } submit(); };
}

/** Preset descriptions in plain words (the built-in ones name models). */
function plainDescription(p) {
  const by = { 'Talking head': 'The face mesh on your original frames. Free, runs on this computer.', 'Full body': 'Motion clip: a depth map plus a mask of the person. Review the mask.', 'Expressive': 'Motion clip + face mesh: the facial motion drawn over the motion clip; gaps only warn.', 'Profile-heavy': 'Motion clip with the face mesh off: best when the speaker turns away a lot.' };
  return by[p.name] || p.description || modeLabel(p.mode);
}
