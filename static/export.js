// Export: target cards (Seedance web · Kling · ComfyUI · After Effects / Nuke · Custom) with a "What's in it" line,
// the alpha format when it matters, the unsaved-edits note, ONE primary "Export · free" (the server saves unsaved
// timeline edits first as one new version and exports that), "Choose files" (level 2: the tick boxes), earlier
// exports, the README and zip of the last one, the Subtitles block (burn them into a copy of the final · free) and
// "Downloads" (level 2: every single file of the run). GET /jobs/{id}/export, POST /jobs/{id}/export, GET …/export/{name}.
import { getJSON, send } from './api.js';
import { $, el, showError, notice, tpl, when, shortId, bytes, remember, withCost } from './ui.js';
import { state, later, current, runHref } from './state.js';
import { edits } from './editlayer.js';
import { downloadLinks } from './stagecard.js';

const FORMAT_LABEL = { prores: 'ProRes 4444 (.mov, real alpha)', png: 'PNG sequence (RGBA frames)' };
const TARGET_NAME = { seedance_web: 'Seedance web', kling: 'Kling', comfyui: 'ComfyUI', after_effects: 'After Effects / Nuke', custom: 'Custom' };

export function mountExport(parent) {
  const node = tpl('tpl-export'); parent.append(node); remember(node);
  const q = s => $(s, node);
  const targets = q('[data-targets]'), itemsBox = q('[data-items]'), itemsCount = q('[data-items-count]'), what = q('[data-what]'), formats = q('[data-formats]'), pendingLine = q('[data-pending]');
  const button = q('[data-export]'), hint = q('[data-hint]'), progress = q('[data-progress]'), result = q('[data-result]'), earlierBox = q('[data-earlier-box]'), earlier = q('[data-earlier]'), earlierCount = q('[data-earlier-count]');
  const subsPanel = q('[data-subs]'), subsBody = q('[data-subs-body]'), filesBox = q('[data-files]');
  const local = { info: null, key: '', jobId: null, preset: 'seedance_web', ticked: new Set(), touched: false, mesh: 'prores', alpha: 'prores', busy: false, polling: null, last: null };

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
    targets.replaceChildren(...info.presets.map(p => el('button', { type: 'button', class: 'target' + (p.name === local.preset ? ' on' : ''), role: 'radio', 'aria-checked': p.name === local.preset ? 'true' : 'false', disabled: local.busy, onclick: () => { local.preset = p.name; local.touched = false; applyPreset(); render(); } },
      el('b', { text: TARGET_NAME[p.name] || p.label }), el('small', { text: p.name === 'custom' ? 'Exactly the files you tick.' : p.what }))));
    const p = info.presets.find(x => x.name === local.preset) || info.presets[0];
    const names = [...local.ticked].map(k => (info.items.find(i => i.key === k) || {}).label).filter(Boolean);
    what.textContent = "What's in it: " + (local.preset === 'custom' ? (names.length ? names.join(', ') + '.' : 'nothing yet; tick the files under "Choose files".') : p.what);
    itemsCount.textContent = local.ticked.size + ' of ' + info.items.filter(i => i.available).length + ' files';
    itemsBox.replaceChildren(...info.items.map(it => {
      const box = el('input', { type: 'checkbox', 'aria-label': it.label }); box.checked = it.available && local.ticked.has(it.key); box.disabled = !it.available || local.busy;
      box.onchange = () => { local.touched = true; if (box.checked) local.ticked.add(it.key); else local.ticked.delete(it.key); render(); };
      return el('label', { class: 'check export-item' + (it.available ? '' : ' off') }, box, el('span', {}, el('strong', { text: it.label }), el('span', { class: 'hint', text: ' · ' + (it.available ? it.what : it.reason) })));
    }));
    const needsMesh = local.ticked.has('mesh_alpha'), needsAlpha = local.ticked.has('alpha');
    formats.replaceChildren();
    if (needsMesh || needsAlpha) {
      const sel = el('select', { 'aria-label': 'Alpha format' }, ...Object.entries(FORMAT_LABEL).map(([v, t]) => el('option', { value: v, text: t })));
      sel.value = needsMesh ? local.mesh : local.alpha; sel.disabled = local.busy;
      sel.onchange = () => { local.mesh = local.alpha = sel.value; local.touched = true; render(); };
      formats.append(el('label', { class: 'field', style: 'flex:1 1 240px' }, (needsMesh && needsAlpha ? 'Face mesh and person alpha as' : needsMesh ? 'Face mesh alone as' : 'Person alpha as'), sel,
        el('span', { class: 'hint', text: sel.value === 'prores' ? 'One .mov per item; imports with its alpha into After Effects, Premiere, Resolve, Nuke.' : 'A folder of numbered RGBA PNGs per item (frame_00000.png …); for ComfyUI and image loaders.' })));
    }
    const pend = info.pending || {};
    if (pend.problem) { pendingLine.hidden = false; pendingLine.className = 'line warn'; pendingLine.textContent = pend.problem.message + ' ' + (pend.problem.fix || ''); }
    else if (pend.note) { pendingLine.hidden = false; pendingLine.className = 'line info'; pendingLine.textContent = pend.note.replace(/pending/gi, 'unsaved') + (pend.summary && pend.summary.length ? ' (' + pend.summary.join(' · ') + ')' : ''); }
    else pendingLine.hidden = true;
    const blocked = !info.ffmpeg ? (info.ffmpeg_problem.message + ' ' + info.ffmpeg_problem.fix) : info.running ? 'This run is still preparing; export when it finishes.' : !local.ticked.size ? 'Tick at least one file under "Choose files".' : pend.problem ? 'Save the unsaved edits in Edit first.' : '';
    hint.textContent = blocked || (pend.note ? 'The edits are saved first as a new version, then the zip is made from it.' : 'The zip lands in the run folder under export/.');
    button.disabled = local.busy || !!blocked;
    withCost(button, local.busy ? 'Exporting…' : 'Export for ' + (TARGET_NAME[local.preset] || 'this target'), local.busy ? '' : 'free');
    const list = (info.exports || []).filter(x => !local.last || x.name !== local.last.name);
    earlierBox.hidden = !list.length; earlierCount.textContent = list.length ? String(list.length) : '';
    earlier.replaceChildren(...list.map(x => el('div', { class: 'export-row' },
      el('span', { class: 'chip ' + (x.state === 'running' ? 'running' : x.state === 'error' ? 'error' : 'done'), text: x.state === 'running' ? 'running' : x.state === 'error' ? 'failed' : (TARGET_NAME[x.preset] || x.preset || 'export') }),
      el('span', { class: 'wrap' }, el('strong', { text: x.preset_label || x.preset || x.name }), ' · ', when(x.created || x.started), x.exported_run && x.exported_run !== state.jobId ? el('span', { class: 'hint', text: ' · from the version ' + shortId(x.exported_run) + '…' }) : null,
        el('span', { class: 'hint', text: x.files ? ' · ' + x.files.length + ' file' + (x.files.length === 1 ? '' : 's') + (x.zip_bytes ? ' · ' + bytes(x.zip_bytes) : '') : '' })),
      x.state === 'done' && x.zip_exists !== false ? el('a', { class: 'btn sm', href: x.zip_url, download: '', text: 'Download zip' }) : x.state === 'running' ? el('button', { type: 'button', class: 'sm', text: 'Follow', onclick: () => poll(x.name) }) : el('span', { class: 'hint', text: x.status || '' }))));
  }

  function showResult(s) {
    local.last = s;
    if (!s || s.state !== 'done') { result.hidden = true; result.replaceChildren(); return; }
    result.hidden = false;
    const other = s.exported_run && s.exported_run !== state.jobId;
    result.replaceChildren(
      el('p', { class: 'line ok', text: 'Export ready: ' + s.files.length + ' file' + (s.files.length === 1 ? '' : 's') + ', ' + s.frames + ' frames at ' + s.fps + ' fps, ' + bytes(s.zip_bytes) + ' zipped.' + (other ? ' Your unsaved edits were saved first as the new version ' + shortId(s.exported_run) + '…, and this export is of that version.' : '') }),
      el('div', { class: 'row' },
        el('a', { class: 'btn', href: s.zip_url, download: '', text: 'Download ' + s.name + '.zip' }),
        other ? el('a', { class: 'btn sm', href: runHref(s.exported_run, 'export'), 'data-nav': true, text: 'Open the new version' }) : null,
        el('span', { class: 'hint', text: 'Unzipped copy: runs/' + shortId(s.exported_run || state.jobId) + '…/export/' + s.name + '/' })),
      el('details', { class: 'more flat' }, el('summary', { text: 'README.txt' }), el('div', { class: 'body' }, el('pre', { class: 'export-readme', text: s.readme || '' }))));
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
      if (s.state === 'done') { showResult(s); notice('Export ready: ' + name + '.zip', { kind: 'ok', key: 'export' }); if (s.exported_run && s.exported_run !== id && edits.jobId === id) edits.load(id); }   // the unsaved edits were saved into the new version: the Save bar must stop showing them here
      else { progress.hidden = false; progress.className = 'line error'; progress.textContent = (s.status || 'The export could not be finished.') + ' ' + (s.fix || ''); }
      local.key = ''; load(true);
    } catch (e) { if (!current(token, id)) return; local.busy = false; local.polling = null; progress.hidden = true; render(); showError(e, { key: 'export' }); }
  }
  button.onclick = start;

  // ---- subtitles: burn them into a copy of the final (off by default; free, local)
  const sub = { state: null, key: '', busy: false, status: '' };
  async function loadSubs(force = false) {
    const files = state.files || new Set();
    const key = state.jobId + '|' + ['final-preview.mp4', 'hd/final-preview.mp4', 'words.json', 'final-preview-subtitled.mp4', 'hd/final-preview-subtitled.mp4'].map(f => (files.has(f) ? 1 : 0)).join('') + '|' + (edits.jobId === state.jobId ? edits.rev : '');
    if (!force && key === sub.key) return;
    sub.key = key;
    try { sub.state = await getJSON('/jobs/' + state.jobId + '/subtitles'); renderSubs(); } catch (e) { showError(e, { key: 'subtitles' }); }
  }
  async function toggleSubs(on) {
    sub.busy = true; sub.status = on ? 'Burning the subtitles in on this computer (free)… about 10 s for a short clip.' : ''; renderSubs();
    try { sub.state = await send('/jobs/' + state.jobId + '/subtitles', { burn: on ? 'true' : 'false' }); sub.status = ''; }
    catch (e) { sub.status = ''; showError(e, { key: 'subtitles' }); }
    sub.busy = false; renderSubs();
  }
  function renderSubs() {
    const s = sub.state; if (!s) { subsBody.replaceChildren(); return; }
    const box = el('input', { type: 'checkbox', 'aria-label': 'Burn subtitles into the final' }); box.checked = !!s.burn; box.disabled = sub.busy || (!s.words && !s.burn);
    box.onchange = () => toggleSubs(box.checked);
    const made = s.finals.filter(f => f.has_final);
    const line = sub.status ? ['info', sub.status] : !s.words ? ['info', 'No words yet: transcribe on the Words lane in Edit (free) to add subtitles.'] : !s.burn ? ['info', `Off: the final has no subtitles (${s.cues} subtitle line${s.cues === 1 ? '' : 's'} ready from ${s.source === 'edits' ? 'your unsaved word edits' : 'the words'}).`]
      : s.up_to_date ? ['ok', `On: ${s.cues} subtitle line${s.cues === 1 ? '' : 's'} burned into a copy of the final; the untouched final stays as it is.`] : ['warn', 'On, but the words changed since the subtitles were burned (or this final has no subtitled copy yet).'];
    const shown = [...made].reverse().find(f => f.exists);
    subsBody.replaceChildren(...[
      el('label', { class: 'check' }, box, el('span', {}, 'Burn subtitles into the final', el('span', { class: 'hint', text: ' · free, runs on this computer; off by default' }))),
      el('p', { class: 'line ' + line[0], 'aria-live': 'polite', text: line[1] }),
      s.burn && !s.up_to_date && s.words && !sub.busy ? el('div', { class: 'row' }, el('button', { type: 'button', class: 'sm', text: 'Burn again · free', onclick: () => toggleSubs(true) })) : null,
      s.burn && shown ? el('video', { src: shown.url + '?v=' + encodeURIComponent(s.updated || ''), controls: true, playsinline: true, preload: 'metadata' }) : null,
      s.burn ? el('div', { class: 'downloads' }, ...made.filter(f => f.exists).map(f => el('a', { href: f.url, download: f.subtitled.replace('/', '-'), text: (f.final.startsWith('hd/') ? 'Final with subtitles' : 'Draft with subtitles') + ' ↓' }))) : null,
    ].filter(Boolean));
  }

  // ---- downloads: every file of the run, plain name first
  function renderFiles() {
    const id = state.jobId, files = state.files || new Set(), reports = (state.run && state.run.reports) || {};
    const key = id + '|' + files.size; if (filesBox.dataset.key === key) return; filesBox.dataset.key = key;
    const base = '/runs/' + id + '/', links = [];
    const named = [['seedance-input.mp4', 'Prepared clip'], ['original.mp4', 'Original'], ['composite.mp4', 'Motion clip'], ['composite-silent.mp4', 'Prepared clip, silent'], ['depth.mp4', 'Depth'], ['mask.mp4', 'Mask'], ['final-preview.mp4', 'Draft'], ['hd/final-preview.mp4', 'Final'], ['vocals.wav', 'Isolated vocals'], ['music.wav', 'Music without the voice'], ['original-audio.wav', 'Original audio'], ['words.json', 'Words'], ['mouth-guidance.json', 'Mouth guidance'], ['face-landmarks.json', 'Face mesh points']];
    for (const [file, title] of named) if (files.has(file)) links.push(el('a', { href: base + file, download: file.split('/').pop(), text: title + ' (' + file + ') ↓' }));
    if (files.has('words.json')) links.push(el('a', { href: '/jobs/' + id + '/subtitles.srt', download: '', text: 'Subtitles (.srt) ↓' }));
    if ([...files].some(f => f.startsWith('clean-masks/'))) links.push(el('a', { href: '/jobs/' + id + '/download/mask.zip', download: '', text: 'Masks as PNGs (mask.zip) ↓' }));
    const seen = new Set(named.map(n => n[0]));
    const names = [...new Set(Object.values(reports).flatMap(r => Object.keys((r && r.outputs) || {})))].filter(n => !seen.has(n));
    links.push(...downloadLinks(id, files, names));
    filesBox.replaceChildren(...(links.length ? links : [el('span', { class: 'hint', text: 'Nothing to download yet.' })]));
  }

  edits.on('change', () => { if (edits.jobId === state.jobId) load(); });
  function update() {
    if (!state.jobId) return;
    if (local.jobId && local.jobId !== state.jobId) { local.polling = null; local.busy = false; progress.hidden = true; result.hidden = true; sub.key = ''; sub.state = null; }
    load();
    const files = state.files || new Set();
    const hasFinal = files.has('final-preview.mp4') || files.has('hd/final-preview.mp4');
    subsPanel.hidden = !hasFinal; if (hasFinal) loadSubs();
    renderFiles();
  }
  return { node, update };
}
