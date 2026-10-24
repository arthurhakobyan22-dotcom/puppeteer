// One stage row (Details · Stages): a compact header (number · name · method · state), expanded: the method select,
// on/off, settings from the schema, health, numbers, warnings, the input-check lists, a preview, "Use my own file…"
// and "Make a new version from here" (the price is on the button before anything runs; that click confirms it).
// `src` = {id(), info(), files(), job()} so the drawer can show any run (the live state for the open run).
import { api, plain, send } from './api.js';
import { $, el, usd, spent, duration, ranges, shortId, setChip, showError, notice, tpl, stageName, methodName, withCost, costActions } from './ui.js';
import { state, navigate } from './state.js';
import { backgroundControls, BACKGROUND_PARAMS } from './slots.js';   // the Background setting of the Motion clip stage (also under World & Look → Set)

const PREVIEW = {
  input_doctor: ['original.mp4'], audio: ['vocals.wav', 'music.wav'], depth: ['depth.mp4', 'depth-raw.mp4'], mask: ['mask.mp4'],
  composite: ['composite.mp4', 'depth-composite-silent.mp4'], face: ['composite-silent.mp4', 'seedance-input.mp4', 'preview.jpg'],
  prompt: [], generate: ['final-preview.mp4', 'seedance-result.mp4'], finish: ['hd/final-preview.mp4', 'final-preview.mp4'],
};

// Use my own file: stages that accept a file made elsewhere, with the formats (POST /jobs/{id}/import).
const IMPORT = {
  depth: ['.mp4,.mov,.webm,.mkv,.m4v,.avi,video/*', 'A depth video, grayscale or coloured (.mp4, .mov, .webm). The earlier mask is kept.'],
  mask: ['.mp4,.mov,.webm,.mkv,.m4v,.avi,.zip,video/*,application/zip', 'A black-and-white mask video, a .zip of PNG frames, or a video with transparency (ProRes 4444 / PNG in .mov, VP9 .webm with alpha).'],
  face: ['.mp4,.mov,.webm,.mkv,.m4v,.avi,.json,video/*,application/json', 'An overlay video (black = keep the clip, anything else is drawn over it), or face landmarks .json in the face-landmarks.json schema.'],
  composite: ['.mp4,.mov,.webm,.mkv,.m4v,.avi,video/*', 'A finished motion clip; the face mesh is switched off for it and it goes straight to Edit.'],
};
const ZIPPABLE = name => !name.includes('/');

/** Download links: one per output file in the report, folders as a zip (GET /jobs/{id}/download/<folder>.zip). */
export function downloadLinks(jobId, files, names) {
  const out = [];
  for (const name of names) {
    if (files.has(name)) out.push(el('a', { href: '/runs/' + jobId + '/' + name, download: name.split('/').pop(), text: name + ' ↓' }));
    else if (ZIPPABLE(name) && [...files].some(f => f.startsWith(name + '/'))) out.push(el('a', { href: '/jobs/' + jobId + '/download/' + name + '.zip', download: '', text: name + '/ (.zip) ↓' }));
  }
  return out;
}

const defaultSrc = () => ({ id: () => state.jobId, info: () => state.run || { run: {}, reports: {} }, files: () => state.files || new Set(), job: () => state.job || {} });

export function mountStageCard(parent, stageDef, index, src = defaultSrc(), { onBranch = null } = {}) {
  const node = tpl('tpl-stage-card'); node.id = 'stage-' + stageDef.name; parent.append(node);
  const q = s => $(s, node);
  const toolSelect = q('[data-tool]'), paramsBox = q('[data-params]'), toggle = q('[data-toggle]'), onBox = q('[data-on]'), rerun = q('[data-rerun]');
  const costEl = q('[data-cost]'), fixes = q('[data-fixes]'), preview = q('[data-preview]'), description = q('[data-description]'), summaryLine = q('[data-summary]');
  const local = { tool: null, params: {}, touched: false, estimate: null, lastOn: null, initialised: false, chainTool: null, chainParams: {} };
  const importedChip = el('span', { class: 'chip imported', text: 'own file', hidden: true, title: 'This stage uses a file you brought in' }); q('[data-state]').after(importedChip);
  const chain = () => ((src.info() || {}).run || {}).chain || {};
  let importBox = null, importBusy = false;
  if (IMPORT[stageDef.name]) {
    const [accept, hint] = IMPORT[stageDef.name];
    const input = el('input', { type: 'file', accept, 'aria-label': 'File to use for ' + stageName(stageDef.name, stageDef.label) });
    const go = el('button', { type: 'button', class: 'sm', disabled: true }); withCost(go, 'Use this file', 'free');
    input.onchange = () => { go.disabled = importBusy || !input.files.length; };
    const doImport = async confirm => {
      const data = new FormData(); data.set('stage', stageDef.name); data.set('file', input.files[0]); if (confirm) data.set('confirm_cost', 'true');
      const r = await send('/jobs/' + src.id() + '/import', data);
      if (onBranch) onBranch();
      navigate({ job: r.id, step: 'prep' });
      notice('"' + input.files[0].name + '" is the ' + stageName(stageDef.name, stageDef.label).toLowerCase() + ' of this new version. It was fitted to the clip; any change is listed as a warning on the stage. The run you took it from stays as it was.', { kind: 'ok', key: 'import' });
    };
    go.onclick = async () => {
      if (!input.files.length) return;
      importBusy = true; go.disabled = true; go.textContent = 'Fitting the file…';
      try { await doImport(false); }
      catch (e) { showError(e, { key: 'import-' + stageDef.name, actions: costActions(e, () => doImport(true)) }); }
      finally { importBusy = false; withCost(go, 'Use this file', 'free'); go.disabled = !input.files.length; }
    };
    importBox = el('details', { class: 'more flat import-own' }, el('summary', { text: 'Use my own file…' }), el('div', { class: 'body' }, el('span', { class: 'hint', text: hint + ' It is fitted to the clip (frame rate, length, size) and becomes a new version; nothing is overwritten.' }), el('div', { class: 'row' }, input, go)));
    q('.controls').append(importBox);
  }
  q('[data-index]').textContent = String(index + 1).padStart(2, '0'); q('[data-label]').textContent = stageName(stageDef.name, stageDef.label);
  const optionText = t => methodName(t.name, t.label) + (t.paid ? ' · paid' : '') + (t.experimental ? ' · experimental' : '');
  for (const t of stageDef.tools) toolSelect.append(el('option', { value: t.name, dataset: { needs: t.needs || '' }, text: optionText(t) }));
  // Methods a plain re-run cannot feed (POST /branch refuses them with a plain 400): 'edits' = saved timeline edits, 'import' = a file chosen with "Use my own file…".
  const NEEDS = { edits: ' · from "Save as new version" only', import: ' · use "Use my own file…"' };
  function canRun(t, files, entry) {
    if (!t || !t.needs) return true;
    if (t.needs === 'import') return entry.tool === t.name && /^[0-9a-f]{64}$/.test(String((entry.params || {}).file || ''));
    return (t.inputs || []).filter(n => n.startsWith('edit-layer/')).every(n => files.has(n) || [...files].some(f => f.startsWith(n + '/')));
  }
  function gateOptions(files, entry) {
    for (const option of toolSelect.options) {
      const t = toolOf(option.value); const ok = canRun(t, files, entry);
      option.disabled = !ok && option.value !== toolSelect.value;
      option.textContent = optionText(t) + (ok ? '' : NEEDS[t.needs] || '');
    }
  }
  const hasOff = stageDef.tools.some(t => t.name === 'off'); toggle.hidden = !hasOff;
  const toolOf = name => stageDef.tools.find(t => t.name === name);
  const firstOn = () => (stageDef.tools.find(t => t.name !== 'off') || stageDef.tools[0]).name;

  function renderParams() {
    paramsBox.replaceChildren();
    const tool = toolOf(local.tool);
    description.textContent = tool ? tool.description : '';
    if (!tool) return;
    const entry = chain()[stageDef.name] || {};
    if (tool.needs === 'edits' && !canRun(tool, src.files(), entry)) {
      paramsBox.append(el('p', { class: 'hint', text: 'This method runs from "Save as new version" in Edit: make the change on the timeline and save it. A plain new version has nothing to give it.' }));
      return;
    }
    if (tool.imported) {   // the file is chosen with "Use my own file…"; its sha256 is never shown as a setting
      paramsBox.append(el('p', { class: 'hint', text: local.params.name ? 'Your file: ' + local.params.name : 'Choose the file with "Use my own file…" below; this method needs a file you bring in.' }));
      return;
    }
    const custom = stageDef.name === 'composite' && tool.name === 'depth_cutout' ? BACKGROUND_PARAMS : [];   // drawn by backgroundControls below
    if (stageDef.name === 'composite' && tool.name === 'original') paramsBox.append(el('p', { class: 'hint', text: 'Original frames have no depth person, so there is no background to choose here. Pick "Depth person over a background" to set one.' }));
    for (const [name, spec] of Object.entries(tool.params || {})) {
      if (custom.includes(name)) continue;
      const value = local.params[name] !== undefined ? local.params[name] : spec.default;
      if (spec.type === 'bool') {
        const input = el('input', { type: 'checkbox' }); input.checked = !!value; input.onchange = () => set(name, input.checked);
        paramsBox.append(el('label', { class: 'check' }, input, el('span', {}, spec.label || name, spec.hint ? el('span', { class: 'hint', text: ' ' + spec.hint }) : null)));
        continue;
      }
      let input;
      if (spec.type === 'choice') { input = el('select'); for (const c of spec.choices || []) input.append(el('option', { value: String(c), text: String(c) })); input.value = value == null ? '' : String(value); input.onchange = () => set(name, input.value); }
      else if (spec.type === 'number') { input = el('input', { type: 'number', step: 'any' }); input.value = value == null ? '' : value; input.onchange = () => set(name, input.value === '' ? null : Number(input.value)); }
      else { const long = name === 'text' || String(value || '').length > 60; input = el(long ? 'textarea' : 'input', long ? { rows: 4 } : { type: 'text' }); input.value = value == null ? '' : String(value); input.onchange = () => set(name, input.value); }
      paramsBox.append(el('label', { class: 'field' }, spec.label || name, input, spec.hint ? el('span', { class: 'hint', text: spec.hint }) : null));
    }
    if (custom.length) backgroundControls(paramsBox, { tool, params: local.params, set, jobId: src.id() });
  }
  function set(name, value) { local.params[name] = value; local.touched = true; local.estimate = null; refreshRerun(); }
  function chooseTool(name) {
    if (name !== 'off') local.lastOn = name;
    local.tool = name; local.params = name === local.chainTool ? { ...local.chainParams } : {};
    local.touched = true; local.estimate = null; onBox.checked = name !== 'off'; toolSelect.value = name;
    renderParams(); refreshRerun();
  }
  toolSelect.onchange = () => chooseTool(toolSelect.value);
  onBox.onchange = () => chooseTool(onBox.checked ? (local.lastOn || firstOn()) : 'off');

  function blocked() {   // the picked method needs saved edits / a file this run does not have
    const picked = toolOf(local.tool); if (!picked || !picked.needs) return false;
    if (picked.imported) return !local.params.file;
    return !canRun(picked, src.files(), chain()[stageDef.name] || {});
  }
  function settings() { return { stage: stageDef.name, tool: local.tool, params: local.params }; }
  function refreshRerun() {
    const busy = src.job().state === 'running'; rerun.disabled = busy || blocked();
    const est = local.estimate;
    if (!est) { withCost(rerun, 'Make a new version from here', local.touched ? 'with these settings' : ''); rerun.classList.remove('primary'); return; }
    rerun.classList.add('primary');
    withCost(rerun, 'Make a new version from here', est.free ? 'free' : usd(est.estimated_cost_usd));
  }
  async function branchNow(confirm) {
    const body = { ...settings() }; if (confirm) body.confirm_cost = 'true';
    const r = await api.branch(src.id(), body);
    if (onBranch) onBranch();
    navigate({ job: r.id, step: 'prep' });
  }
  rerun.onclick = async () => {
    rerun.disabled = true;
    try {
      if (!local.estimate) {
        const est = await api.estimateBranch(src.id(), settings());
        local.estimate = est; refreshRerun();
        if (est.free) { costEl.textContent = 'Runs ' + est.stages_to_run.map(s => stageName(s)).join(' → ') + ' again · free'; await branchNow(false); }
        else costEl.textContent = 'Running ' + est.stages_to_run.map(s => stageName(s)).join(' → ') + ' again costs ' + usd(est.estimated_cost_usd) + ' (' + est.paid.map(p => p.label).join(', ') + '). Click the button again to confirm; nothing has run yet.';
      } else await branchNow(!local.estimate.free);
    } catch (e) { showError(e, { key: 'branch-' + stageDef.name, actions: costActions(e, () => branchNow(true)) }); }
    finally { rerun.disabled = false; }
  };

  /** Input check (and any method that reports them): data.checks, data.fixes (with before/after notes) and data.advice as plain lists. */
  function renderChecklists(report) {
    const data = (report && report.data) || {};
    const lists = [['Checks', data.checks, 'checks'], ['Fixes applied', (data.fixes || []).map(f => (f && f.note) || f), 'fixes'], ['Advice', data.advice, 'advice']].filter(([, items]) => Array.isArray(items) && items.length);
    let box = q('[data-checklists]');
    if (!lists.length) { if (box) box.remove(); return; }
    if (!box) { box = el('div', { 'data-checklists': true }); q('[data-warnings]').before(box); }
    box.replaceChildren();
    for (const [title, items, kind] of lists) box.append(el('p', { class: 'checklist-title', text: title }), el('ul', { class: 'checklist ' + kind }, items.map(t => el('li', { text: String(t) }))));
  }

  function renderPreview(files, report) {
    const base = '/runs/' + src.id() + '/';
    const candidates = [...(PREVIEW[stageDef.name] || []), ...Object.keys((report && report.outputs) || {})];
    const file = candidates.find(n => /\.(mp4|webm|mov|jpg|jpeg|png|wav|mp3)$/i.test(n) && files.has(n));
    if (stageDef.name === 'prompt') {
      const text = (report && report.data && (report.data.full_prompt || report.data.text)) || (local.chainParams && local.chainParams.text) || '';
      if (preview.dataset.file !== 'prompt:' + text) { preview.dataset.file = 'prompt:' + text; preview.replaceChildren(text ? el('pre', { class: 'prompt', text }) : el('div', { class: 'empty sm', text: 'No prompt recorded yet.' })); }
      return;
    }
    if (!file) { if (preview.dataset.file !== '') { preview.dataset.file = ''; preview.replaceChildren(el('div', { class: 'empty sm', text: 'No output to preview for this stage.' })); } return; }
    if (preview.dataset.file === file) return;
    preview.dataset.file = file;
    const url = base + file;
    const media = /\.(jpg|jpeg|png)$/i.test(file) ? el('img', { src: url, alt: file }) : /\.(wav|mp3)$/i.test(file) ? el('audio', { src: url, controls: true }) : el('video', { src: url, controls: true, playsinline: true, preload: 'metadata' });
    preview.replaceChildren(media, el('a', { class: 'hint', href: url, download: file.split('/').pop(), text: file + ' ↓' }));
  }

  function update({ active = false } = {}) {
    const info = src.info() || {}, run = info.run || {}, reports = info.reports || {}, files = src.files();
    const entry = (run.chain && run.chain[stageDef.name]) || { tool: stageDef.tools[0].name, params: {} };
    const report = reports[stageDef.name] || null;
    if (!local.initialised || !local.touched) {
      local.chainTool = entry.tool; local.chainParams = { ...(entry.params || {}) };
      local.tool = entry.tool; local.params = { ...(entry.params || {}) }; local.lastOn = entry.tool !== 'off' ? entry.tool : (local.lastOn || firstOn());
      if (!toolOf(local.tool)) local.tool = stageDef.tools[0].name;
      toolSelect.value = local.tool; onBox.checked = local.tool !== 'off'; renderParams(); local.initialised = true; refreshRerun();
    }
    const jobState = src.job().state || '';
    const cardState = report ? report.state : (jobState === 'running' ? (active ? 'running' : 'pending') : 'missing');
    setChip(q('[data-state]'), cardState, cardState === 'pending' ? 'waiting' : cardState === 'missing' ? 'not run' : cardState === 'cached' ? 'reused' : cardState);
    node.className = 'stage' + (cardState === 'error' ? ' error' : cardState === 'running' ? ' running' : '');
    const tool = toolOf(entry.tool);
    summaryLine.textContent = (tool ? methodName(tool.name, tool.label) : entry.tool) + (report && report.health ? ' · ' + report.health : '');
    const health = (report && report.health) || (cardState === 'running' ? 'Running now…' : cardState === 'pending' ? 'Waiting for the earlier stages.' : 'Nothing recorded for this stage.');
    q('[data-health]').textContent = health;
    const numbers = q('[data-numbers]'); numbers.replaceChildren();
    if (report) {
      const f = report.frames || {};
      if (f.covered != null) numbers.append(el('span', { text: 'covered ' + f.covered }));
      if (f.filled) numbers.append(el('span', { text: 'filled ' + f.filled }));
      if (f.missing) numbers.append(el('span', { text: 'lost ' + f.missing }));
      if ((report.gaps || []).length) numbers.append(el('span', { text: 'lost ' + ranges(report.gaps) }));
      if (report.seconds != null) numbers.append(el('span', { text: duration(report.seconds) }));
      numbers.append(el('span', { text: Number(report.cost_usd || 0) > 0 ? 'spent ' + spent(report.cost_usd) : 'free' }));
      if (report.cached_from) numbers.append(el('span', { text: 'reused from ' + shortId(report.cached_from) + '…, nothing re-billed' }));
    }
    const warnings = q('[data-warnings]'); warnings.replaceChildren();
    const list = (report && report.warnings) || []; warnings.hidden = !list.length;
    for (const w of list) warnings.append(el('li', { text: w }));
    renderChecklists(report);
    importedChip.hidden = !(tool && tool.imported);
    if (importBox) importBox.querySelector('button').disabled = importBusy || jobState === 'running' || !importBox.querySelector('input').files.length;
    const errorBox = q('[data-error]');
    if (report && report.error) { errorBox.hidden = false; errorBox.textContent = report.error.message + (report.error.fix ? ' ' + report.error.fix : ''); }
    else errorBox.hidden = true;
    fixes.replaceChildren();
    if (report && report.error && stageDef.name === 'face' && entry.tool === 'mediapipe_mesh' && entry.params && entry.params.strict) {
      fixes.append(el('button', { type: 'button', class: 'sm', text: 'Re-run with lenient gaps · free', onclick: async () => { chooseTool('mediapipe_mesh'); local.params = { ...local.chainParams, strict: false }; renderParams(); local.estimate = null; rerun.click(); } }));
    }
    if (!local.estimate) costEl.textContent = toolOf(local.tool) && toolOf(local.tool).paid ? 'This method is paid; the price shows on the button before anything runs.' : '';
    renderPreview(files, report);
    gateOptions(files, entry);
    rerun.disabled = jobState === 'running' || blocked();
  }
  return { node, update, stage: stageDef.name };
}

export { plain };
