// Export kit (step 04, World stage Agent 4): tick the items, pick a target preset, export · free, local. The server saves
// pending timeline edits first (one free branch) and exports the new run; the panel says so before you click and shows
// the README and the zip link after. GET /jobs/{id}/export (items + reasons, presets, pending note, earlier exports),
// POST /jobs/{id}/export {preset, items, mesh_format, alpha_format} → poll GET /jobs/{id}/export/{name}.
import { getJSON, send } from './api.js';
import { $, el, showError, notice, tpl, when, shortId } from './ui.js';
import { state, later, current, hrefFor } from './state.js';
import { edits } from './editlayer.js';

const FORMAT_LABEL = { prores: 'ProRes 4444 (.mov, real alpha)', png: 'PNG sequence (RGBA frames)' };
const bytes = n => n == null ? '' : n > 1e9 ? (n / 1e9).toFixed(2) + ' GB' : n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.round(n / 1e3) + ' kB';

export function mountExport(parent) {
  const node = tpl('tpl-export'); parent.append(node);
  const q = s => $(s, node);
  const presetSel = q('[data-preset]'), itemsBox = q('[data-items]'), what = q('[data-what]'), formats = q('[data-formats]'), pendingLine = q('[data-pending]');
  const button = q('[data-export]'), hint = q('[data-hint]'), progress = q('[data-progress]'), result = q('[data-result]'), earlierBox = q('[data-earlier-box]'), earlier = q('[data-earlier]');
  const local = { info: null, key: '', jobId: null, preset: 'seedance_web', ticked: new Set(), touched: false, mesh: 'prores', alpha: 'prores', busy: false, polling: null, last: null };

  presetSel.onchange = () => { local.preset = presetSel.value; local.touched = false; applyPreset(); render(); };

  function applyPreset() {
    const p = local.info && local.info.presets.find(x => x.name === local.preset);
    if (!p) return;
    local.ticked = new Set(p.items.filter(k => available(k)));
    if (p.formats.mesh_alpha) local.mesh = p.formats.mesh_alpha;
    if (p.formats.alpha) local.alpha = p.formats.alpha;
  }
  const available = key => { const it = local.info && local.info.items.find(i => i.key === key); return !!(it && it.available); };

  async function load(force = false) {
    const id = state.jobId; if (!id) return;
    const files = state.files || new Set();
    const key = id + '|' + ['seedance-input.mp4', 'composite-silent.mp4', 'depth.mp4', 'mask.mp4', 'face-landmarks.json', 'words.json', 'vocals.wav', 'char1-reference.png', 'slots.json', 'run.json'].map(f => (files.has(f) ? 1 : 0)).join('') + '|' + (edits.jobId === id ? edits.rev : '') + '|' + ((state.job && state.job.state) || '');
    if (!force && key === local.key) return;
    local.key = key; const token = state.token;
    try {
      const info = await getJSON('/jobs/' + id + '/export');
      if (!current(token, id)) return;
      if (local.jobId !== id) { local.jobId = id; local.touched = false; local.last = null; local.preset = 'seedance_web'; }
      local.info = info;
      if (!local.touched) applyPreset(); else local.ticked = new Set([...local.ticked].filter(available));
      render();
    } catch (e) { if (current(token, id)) showError(e, { key: 'export' }); }
  }

  function render() {
    const info = local.info; if (!info) return;
    if (presetSel.options.length !== info.presets.length) { presetSel.replaceChildren(...info.presets.map(p => el('option', { value: p.name, text: p.label }))); }
    presetSel.value = local.preset;
    const p = info.presets.find(x => x.name === local.preset) || info.presets[0];
    const names = [...local.ticked].map(k => (info.items.find(i => i.key === k) || {}).label).filter(Boolean);
    what.textContent = "What's in it: " + (local.preset === 'custom' ? (names.length ? names.join(', ') + '.' : 'nothing yet; tick the items below.') : p.what);
    // items: one tick box each; unavailable ones disabled with the reason
    itemsBox.replaceChildren(...info.items.map(it => {
      const box = el('input', { type: 'checkbox', 'aria-label': it.label }); box.checked = it.available && local.ticked.has(it.key); box.disabled = !it.available || local.busy;
      box.onchange = () => { local.touched = true; if (box.checked) local.ticked.add(it.key); else local.ticked.delete(it.key); render(); };
      return el('label', { class: 'check export-item' + (it.available ? '' : ' off') }, box,
        el('span', {}, el('strong', { text: it.label }), el('span', { class: 'hint', text: ' · ' + (it.available ? it.what : it.reason) })));
    }));
    // formats for the two alpha items
    const needsMesh = local.ticked.has('mesh_alpha'), needsAlpha = local.ticked.has('alpha');
    formats.replaceChildren();
    if (needsMesh || needsAlpha) {
      const sel = el('select', { 'aria-label': 'Alpha format' }, ...Object.entries(FORMAT_LABEL).map(([v, t]) => el('option', { value: v, text: t })));
      sel.value = needsMesh ? local.mesh : local.alpha; sel.disabled = local.busy;
      sel.onchange = () => { local.mesh = local.alpha = sel.value; local.touched = true; render(); };
      formats.append(el('label', { class: 'field', style: 'flex:1 1 240px' }, (needsMesh && needsAlpha ? 'Face mesh and person alpha as' : needsMesh ? 'Face mesh alone as' : 'Person alpha as'), sel,
        el('span', { class: 'hint', text: sel.value === 'prores' ? 'One .mov per item; imports with its alpha into After Effects, Premiere, Resolve, Nuke.' : 'A folder of numbered RGBA PNGs per item (frame_00000.png …); for ComfyUI and image loaders.' })));
    }
    // pending edits
    const pend = info.pending || {};
    if (pend.problem) { pendingLine.hidden = false; pendingLine.className = 'line warn'; pendingLine.textContent = pend.problem.message + ' ' + (pend.problem.fix || ''); }
    else if (pend.note) { pendingLine.hidden = false; pendingLine.className = 'line info'; pendingLine.textContent = pend.note + (pend.summary && pend.summary.length ? ' (' + pend.summary.join(' · ') + ')' : ''); }
    else pendingLine.hidden = true;
    const blocked = !info.ffmpeg ? (info.ffmpeg_problem.message + ' ' + info.ffmpeg_problem.fix) : info.running ? 'This run is still preparing; export when it finishes.' : !local.ticked.size ? 'Tick at least one item.' : pend.problem ? 'Save the pending edits from the editor first.' : '';
    hint.textContent = blocked || (pend.note ? 'Free, runs locally. The edits are saved first, then the zip is made from the new run.' : 'Free, runs locally. The zip lands in the run folder under export/.');
    button.disabled = local.busy || !!blocked;
    button.textContent = local.busy ? 'Exporting…' : 'Export · free, local';
    // earlier exports
    const list = (info.exports || []).filter(x => !local.last || x.name !== local.last.name);
    earlierBox.hidden = !list.length;
    earlier.replaceChildren(...list.map(x => el('div', { class: 'export-row' },
      el('span', { class: 'chip ' + (x.state === 'running' ? 'running' : x.state === 'error' ? 'error' : 'done'), text: x.state === 'running' ? 'running' : x.state === 'error' ? 'failed' : x.preset || 'export' }),
      el('span', { class: 'wrap' }, el('strong', { text: x.preset_label || x.preset || x.name }), ' · ', when(x.created || x.started), x.exported_run && x.exported_run !== state.jobId ? el('span', { class: 'hint', text: ' · from the new version ' + shortId(x.exported_run) + '…' }) : null,
        el('span', { class: 'hint', text: x.files ? ' · ' + x.files.length + ' file' + (x.files.length === 1 ? '' : 's') + (x.zip_bytes ? ' · ' + bytes(x.zip_bytes) : '') : '' })),
      x.state === 'done' && x.zip_exists !== false ? el('a', { class: 'button small secondary', href: x.zip_url, download: '', text: 'Download zip ↓' }) : x.state === 'running' ? el('button', { type: 'button', class: 'small secondary', text: 'Follow', onclick: () => poll(x.name) }) : el('span', { class: 'hint', text: x.status || '' }))));
  }

  function showResult(s) {
    local.last = s;
    if (!s || s.state !== 'done') { result.hidden = true; result.replaceChildren(); return; }
    result.hidden = false;
    const other = s.exported_run && s.exported_run !== state.jobId;
    result.replaceChildren(
      el('p', { class: 'line ok', text: 'Export ready: ' + s.files.length + ' file' + (s.files.length === 1 ? '' : 's') + ', ' + s.frames + ' frames at ' + s.fps + ' fps, ' + bytes(s.zip_bytes) + ' zipped.' + (other ? ' Your pending edits were saved first as the new version ' + shortId(s.exported_run) + '…, and this export is of that version.' : '') }),
      el('div', { class: 'row' },
        el('a', { class: 'button', href: s.zip_url, download: '', text: 'Download ' + s.name + '.zip ↓' }),
        other ? el('a', { class: 'button small secondary', href: hrefFor({ job: s.exported_run, view: state.view }), 'data-nav': true, text: 'Open the new version →' }) : null,
        el('span', { class: 'hint', text: 'Unzipped copy: runs/' + shortId(s.exported_run || state.jobId) + '…/export/' + s.name + '/' })),
      el('details', { open: true }, el('summary', { text: 'README.txt' }), el('pre', { class: 'export-readme', text: s.readme || '' })));
  }

  async function start() {
    const id = state.jobId; if (!id || local.busy) return;
    local.busy = true; render(); result.hidden = true; progress.hidden = false; progress.className = 'line info'; progress.textContent = 'Starting the export…';
    try {
      const s = await send('/jobs/' + id + '/export', { preset: local.preset, items: [...local.ticked], mesh_format: local.mesh, alpha_format: local.alpha });
      poll(s.name);
    } catch (e) { local.busy = false; progress.hidden = true; render(); showError(e, { key: 'export' }); }
  }

  async function poll(name) {
    const id = state.jobId, token = state.token; local.busy = true; local.polling = name; render();
    try {
      const s = await getJSON('/jobs/' + id + '/export/' + name);
      if (!current(token, id) || local.polling !== name) return;
      if (s.state === 'running') { progress.hidden = false; progress.className = 'line info'; progress.textContent = s.status || 'Exporting…'; later(() => poll(name), 700); return; }
      local.busy = false; local.polling = null; progress.hidden = true;
      if (s.state === 'done') { showResult(s); notice('Export ready: ' + name + '.zip', { kind: 'ok', key: 'export' }); }
      else { progress.hidden = false; progress.className = 'line error'; progress.textContent = (s.status || 'The export could not be finished.') + ' ' + (s.fix || ''); }
      local.key = ''; load(true);
    } catch (e) { if (!current(token, id)) return; local.busy = false; local.polling = null; progress.hidden = true; render(); showError(e, { key: 'export' }); }
  }

  button.onclick = start;
  edits.on('change', () => { if (edits.jobId === state.jobId) load(); });
  function update() { if (!state.jobId) return; if (local.jobId && local.jobId !== state.jobId) { local.polling = null; local.busy = false; progress.hidden = true; result.hidden = true; } load(); }
  return { node, update };
}
