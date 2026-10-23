// The run header shown above the panels (Quick with a job, Studio): name, state, spent so far, parent, what changed,
// and the actions (switch view, add to Lab, save the chain as a preset).
import { api } from './api.js';
import { $, el, spent, when, modeLabel, runLabel, setChip, showError, notice, tpl, shortId } from './ui.js';
import { state, navigate, setLabRuns, hrefFor } from './state.js';

/** Stages of a chain whose tool is an "Import my own" tool (the registry marks them imported: true). */
export function importedStages(chain) {
  const reg = (state.registry && state.registry.stages) || [];
  return Object.entries(chain || {}).filter(([stage, entry]) => { const s = reg.find(x => x.name === stage); const t = s && s.tools.find(x => x.name === (entry && entry.tool)); return !!(t && t.imported); }).map(([stage]) => stage);
}

export function mountRunHead(parent, { view }) {
  const node = tpl('tpl-run-head'); parent.append(node);
  const q = s => $(s, node);
  const form = q('[data-form=preset]'), actions = q('[data-actions]');
  q('[data-cancel]').onclick = () => { form.hidden = true; };
  form.onsubmit = async e => {
    e.preventDefault();
    const button = form.querySelector('button[type=submit]'); button.disabled = true;
    try {
      const r = await api.savePreset({ name: form.name.value, description: form.description.value, job: state.jobId });
      state.presets = (await api.presets()).presets;
      form.hidden = true; form.reset();
      notice('Preset "' + r.preset.name + '" saved. It is now in the Quick preset list.', { kind: 'ok', key: 'preset' });
    } catch (e2) { showError(e2, { key: 'preset' }); }
    finally { button.disabled = false; }
  };

  function update() {
    const run = (state.run && state.run.run) || {}, job = state.job || {}, id = state.jobId;
    q('[data-title]').textContent = runLabel({ preset: run.preset, mode: run.mode });
    setChip(q('[data-state]'), job.state || run.state || 'unknown');
    q('[data-spent]').textContent = 'Spent so far: ' + spent(run.cost_usd_total);
    q('[data-created]').textContent = when(run.created || (state.run && state.run.status && state.run.status.created));
    q('[data-mode]').textContent = modeLabel(run.mode) + (state.run && state.run.migrated ? ' · made before the stage rack' : '');
    const parent = q('[data-parent]'), changed = q('[data-changed]');
    if (run.parent) { parent.hidden = false; parent.replaceChildren('Branched from ', el('a', { href: hrefFor({ job: run.parent, view }), 'data-nav': true, text: shortId(run.parent) + '…' })); }
    else parent.hidden = true;
    const imported = importedStages(run.chain);
    if (run.changed) { changed.hidden = false; changed.replaceChildren(el('b', { text: 'What changed: ' }), run.changed, ...imported.map(stage => el('span', { class: 'chip imported', style: 'margin-left:6px', text: 'imported · ' + stage }))); }
    else if (imported.length) { changed.hidden = false; changed.replaceChildren(...imported.map(stage => el('span', { class: 'chip imported', text: 'imported · ' + stage }))); }
    else changed.hidden = true;
    q('[data-id]').textContent = id;
    actions.replaceChildren();
    if (view === 'quick') actions.append(el('a', { class: 'button small secondary', href: hrefFor({ job: id, view: 'studio' }), 'data-nav': true, text: 'Open in Studio' }));
    else actions.append(el('a', { class: 'button small secondary', href: hrefFor({ job: id, view: 'quick' }), 'data-nav': true, text: 'Quick view' }));
    if (view === 'studio') actions.append(el('a', { class: 'button small secondary', href: '#export', text: 'Export…', title: 'Export kit under step 04: zip for Seedance web, Kling, ComfyUI, After Effects (free, local)', onclick: e => { const t = document.getElementById('export'); if (t) { e.preventDefault(); t.scrollIntoView({ behavior: 'smooth', block: 'start' }); } } }));
    const inLab = state.labRuns.includes(id);
    actions.append(el('button', { type: 'button', class: 'small secondary', text: inLab ? 'In Lab ✓ · open' : 'Add to Lab', onclick: () => { if (!inLab) setLabRuns([...state.labRuns, id]); navigate({ view: 'lab', runs: state.labRuns, stage: state.labStage }); } }));
    actions.append(el('button', { type: 'button', class: 'small secondary', text: 'Save as preset', onclick: () => { form.hidden = !form.hidden; if (!form.hidden) form.name.focus(); } }));
    actions.append(el('a', { class: 'button small secondary', href: hrefFor({ view: 'runs' }), 'data-nav': true, text: 'All runs' }));
  }
  return { node, update };
}
