// One Studio card per stage: tool dropdown, on/off, params from the schema, output preview, health line, numbers,
// and "Re-run from here" (estimate first; a paid re-run needs a second click on the button that shows the cost).
import { api, plain } from './api.js';
import { $, el, usd, spent, duration, ranges, shortId, setChip, showError, tpl } from './ui.js';
import { state, navigate } from './state.js';

const PREVIEW = {
  input_doctor: ['original.mp4'], audio: ['vocals.wav', 'music.wav'], depth: ['depth.mp4', 'depth-raw.mp4'], mask: ['mask.mp4'],
  composite: ['composite.mp4', 'depth-composite-silent.mp4'], face: ['composite-silent.mp4', 'seedance-input.mp4', 'preview.jpg'],
  prompt: [], generate: ['final-preview.mp4', 'seedance-result.mp4'], finish: ['hd/final-preview.mp4', 'final-preview.mp4'],
};

export function mountStageCard(parent, stageDef, index) {
  const node = tpl('tpl-stage-card'); node.id = 'stage-' + stageDef.name; parent.append(node);
  const q = s => $(s, node);
  const toolSelect = q('[data-tool]'), paramsBox = q('[data-params]'), toggle = q('[data-toggle]'), onBox = q('[data-on]'), rerun = q('[data-rerun]');
  const costEl = q('[data-cost]'), fixes = q('[data-fixes]'), preview = q('[data-preview]'), description = q('[data-description]');
  const local = { tool: null, params: {}, touched: false, estimate: null, lastOn: null, initialised: false, chainTool: null, chainParams: {} };
  q('[data-index]').textContent = String(index + 1).padStart(2, '0'); q('[data-label]').textContent = stageDef.label;
  for (const t of stageDef.tools) toolSelect.append(el('option', { value: t.name, text: t.label + (t.paid ? ' · paid' : '') + (t.experimental ? ' · experimental' : '') }));
  const hasOff = stageDef.tools.some(t => t.name === 'off'); toggle.hidden = !hasOff;
  const toolOf = name => stageDef.tools.find(t => t.name === name);
  const firstOn = () => (stageDef.tools.find(t => t.name !== 'off') || stageDef.tools[0]).name;

  function renderParams() {
    paramsBox.replaceChildren();
    const tool = toolOf(local.tool);
    description.textContent = tool ? tool.description : '';
    if (!tool) return;
    for (const [name, spec] of Object.entries(tool.params || {})) {
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

  function settings() { return { stage: stageDef.name, tool: local.tool, params: local.params }; }
  function refreshRerun() {
    const est = local.estimate;
    if (!est) { rerun.textContent = local.touched ? 'Re-run from here with these settings' : 'Re-run from here'; rerun.classList.add('secondary'); return; }
    rerun.classList.remove('secondary');
    rerun.textContent = est.free ? 'Run now · free' : 'Run now · ' + usd(est.estimated_cost_usd) + ' · click to confirm';
  }
  async function branchNow(confirm) {
    const body = { ...settings() }; if (confirm) body.confirm_cost = 'true';
    const r = await api.branch(state.jobId, body);
    navigate({ job: r.id, view: 'studio' });
  }
  rerun.onclick = async () => {
    rerun.disabled = true;
    try {
      if (!local.estimate) {
        const est = await api.estimateBranch(state.jobId, settings());
        local.estimate = est; refreshRerun();
        if (est.free) { costEl.textContent = 'Re-runs ' + est.stages_to_run.join(' → ') + ' · free'; await branchNow(false); }
        else costEl.textContent = 'Re-running ' + est.stages_to_run.join(' → ') + ' costs ' + usd(est.estimated_cost_usd) + ' (' + est.paid.map(p => p.label).join(', ') + '). Click the button again to confirm; nothing has run yet.';
      } else await branchNow(!local.estimate.free);
    } catch (e) {
      const p = plain(e);
      showError(e, { key: 'branch-' + stageDef.name, actions: p.status === 402 ? [{ label: 'Run anyway · ' + usd(p.body.estimated_cost_usd), run: () => branchNow(true) }] : [] });
    } finally { rerun.disabled = false; }
  };

  /** Input doctor (and any tool that reports them): data.checks, data.fixes (with before/after notes) and data.advice as plain lists. */
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
    const base = '/runs/' + state.jobId + '/';
    const candidates = [...(PREVIEW[stageDef.name] || []), ...Object.keys((report && report.outputs) || {})];
    const file = candidates.find(n => /\.(mp4|webm|mov|jpg|jpeg|png|wav|mp3)$/i.test(n) && files.has(n));
    if (stageDef.name === 'prompt') {
      const text = (report && report.data && (report.data.full_prompt || report.data.text)) || (local.chainParams && local.chainParams.text) || '';
      if (preview.dataset.file !== 'prompt:' + text) { preview.dataset.file = 'prompt:' + text; preview.replaceChildren(text ? el('pre', { text }) : el('div', { class: 'empty', text: 'No prompt recorded yet.' })); }
      return;
    }
    if (!file) { if (preview.dataset.file !== '') { preview.dataset.file = ''; preview.replaceChildren(el('div', { class: 'empty', text: 'No output to preview for this stage.' })); } return; }
    if (preview.dataset.file === file) return;
    preview.dataset.file = file;
    const url = base + file;
    const media = /\.(jpg|jpeg|png)$/i.test(file) ? el('img', { src: url, alt: file }) : /\.(wav|mp3)$/i.test(file) ? el('audio', { src: url, controls: true }) : el('video', { src: url, controls: true, playsinline: true, preload: 'metadata' });
    preview.replaceChildren(media, el('a', { class: 'hint', href: url, download: file.split('/').pop(), text: file + ' ↓' }));
  }

  function update({ active = false } = {}) {
    const run = (state.run && state.run.run) || {}, reports = (state.run && state.run.reports) || {}, files = state.files || new Set();
    const entry = (run.chain && run.chain[stageDef.name]) || { tool: stageDef.tools[0].name, params: {} };
    const report = reports[stageDef.name] || null;
    if (!local.initialised || !local.touched) {
      local.chainTool = entry.tool; local.chainParams = { ...(entry.params || {}) };
      local.tool = entry.tool; local.params = { ...(entry.params || {}) }; local.lastOn = entry.tool !== 'off' ? entry.tool : (local.lastOn || firstOn());
      if (!toolOf(local.tool)) local.tool = stageDef.tools[0].name;
      toolSelect.value = local.tool; onBox.checked = local.tool !== 'off'; renderParams(); local.initialised = true; refreshRerun();
    }
    const jobState = (state.job && state.job.state) || '';
    const cardState = report ? report.state : (jobState === 'running' ? (active ? 'running' : 'pending') : 'missing');
    setChip(q('[data-state]'), cardState, cardState === 'pending' ? 'waiting' : cardState === 'missing' ? 'not run' : cardState);
    node.className = 'card' + (cardState === 'error' ? ' error' : cardState === 'running' ? ' running' : '');
    // health + numbers
    const health = (report && report.health) || (cardState === 'running' ? 'Running now…' : cardState === 'pending' ? 'Waiting for the earlier stages.' : 'Nothing recorded for this stage.');
    q('[data-health]').textContent = health;
    const numbers = q('[data-numbers]'); numbers.replaceChildren();
    if (report) {
      const f = report.frames || {};
      if (f.covered != null) numbers.append(el('span', { text: 'covered ' + f.covered }));
      if (f.filled) numbers.append(el('span', { text: 'filled ' + f.filled }));
      if (f.missing) numbers.append(el('span', { text: 'missing ' + f.missing }));
      if ((report.gaps || []).length) numbers.append(el('span', { text: 'lost ' + ranges(report.gaps) }));
      if (report.seconds != null) numbers.append(el('span', { text: duration(report.seconds) }));
      numbers.append(el('span', { text: Number(report.cost_usd || 0) > 0 ? 'cost ' + spent(report.cost_usd) : 'free' }));
      if (report.cached_from) numbers.append(el('span', { text: 'reused from ' + shortId(report.cached_from) + ', nothing re-billed' }));
    }
    const warnings = q('[data-warnings]'); warnings.replaceChildren();
    const list = (report && report.warnings) || []; warnings.hidden = !list.length;
    for (const w of list) warnings.append(el('li', { text: w }));
    renderChecklists(report);
    const errorBox = q('[data-error]');
    if (report && report.error) { errorBox.hidden = false; errorBox.textContent = report.error.message + (report.error.fix ? ' ' + report.error.fix : ''); }
    else errorBox.hidden = true;
    // fix buttons
    fixes.replaceChildren();
    if (report && report.error && stageDef.name === 'face' && entry.tool === 'mediapipe_mesh' && entry.params && entry.params.strict) {
      fixes.append(el('button', { type: 'button', class: 'small', text: 'Re-run with lenient gaps · free', onclick: async () => { chooseTool('mediapipe_mesh'); local.params = { ...local.chainParams, strict: false }; renderParams(); local.estimate = null; rerun.click(); } }));
    }
    if (!local.estimate) costEl.textContent = toolOf(local.tool) && toolOf(local.tool).paid ? 'This tool is paid; the estimate shows on the button before anything runs.' : '';
    renderPreview(files, report);
    rerun.disabled = jobState === 'running';
  }
  return { node, update, stage: stageDef.name };
}
