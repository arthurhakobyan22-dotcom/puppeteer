// Compare: two to four versions side by side, one view, played in sync from one master clock; plain recipe
// differences and the numbers per tile; a pick per comparison stored by the app (survives reload). The tray lists
// the picked runs and their family first, then a search over every run. URL: /?view=compare&runs=a,b&stage=<file>
// (the old view=lab link lands here too).
import { api } from './api.js';
import { $, $$, el, spent, when, ranges, runName, runLabel, runStatus, setChip, showError, notice, tpl, shortId, stageName, methodName, ago } from './ui.js';
import { state, setLabRuns, hrefFor, runHref } from './state.js';
import { openDetails } from './drawer.js';

export const OUTPUTS = [
  ['Prepared clip', ['seedance-input.mp4']], ['Original', ['original.mp4']], ['Depth', ['depth.mp4']], ['Mask', ['mask.mp4']],
  ['Motion clip', ['composite.mp4', 'depth-composite-silent.mp4', 'composite-silent.mp4']], ['Draft', ['final-preview.mp4']], ['Final', ['hd/final-preview.mp4']],
];
const LETTERS = 'ABCD';

function flatten(nodes, depth = 0, out = []) {
  for (const n of nodes || []) { out.push({ node: n, depth }); flatten(n.children, depth + 1, out); }
  return out;
}

/** Plain lines describing how `chain` differs from `base` (the first tile). */
export function chainDiff(base, chain) {
  const lines = [];
  for (const stage of Object.keys(base || {})) {
    const a = base[stage] || {}, b = (chain || {})[stage] || {};
    if ((a.tool || 'off') !== (b.tool || 'off')) { lines.push(`${stageName(stage)}: ${methodName(a.tool || 'off')} → ${methodName(b.tool || 'off')}`); continue; }
    const keys = new Set([...Object.keys(a.params || {}), ...Object.keys(b.params || {})]);
    for (const k of keys) {
      const va = (a.params || {})[k], vb = (b.params || {})[k];
      if (JSON.stringify(va) !== JSON.stringify(vb)) {
        if (k === 'text') { lines.push(`${stageName(stage)}: the prompt text changed`); continue; }
        lines.push(`${stageName(stage)}: ${k} ${String(va)} → ${String(vb)}`);
      }
    }
  }
  return lines;
}

export function reportNumbers(info) {
  const reports = (info && info.reports) || {}, out = [];
  const face = reports.face, mask = reports.mask, probe = reports.input_doctor;
  if (probe && probe.frames && probe.frames.covered != null) out.push(`${probe.frames.covered} frames`);
  if (mask && mask.tool !== 'off' && mask.frames && mask.frames.covered != null) out.push(`mask on ${mask.frames.covered} frames`);
  if (face && face.tool !== 'off' && face.frames && face.frames.covered != null) out.push(`face found on ${face.frames.covered}` + (face.frames.filled ? `, filled ${face.frames.filled}` : '') + (face.frames.missing ? `, lost ${face.frames.missing}` : '') + ((face.gaps || []).length ? ` · lost ${ranges(face.gaps)}` : ''));
  out.push('spent ' + spent(info && info.run && info.run.cost_usd_total));
  return out;
}

export async function renderCompare(container) {
  const node = tpl('tpl-compare'); container.append(node);
  const q = s => $(s, node);
  const tray = q('[data-tray]'), search = q('[data-search]'), count = q('[data-count]'), stageSelect = q('[data-stage]'), tiles = q('[data-tiles]'), empty = q('[data-empty]'), controls = q('[data-controls]');
  const playButton = q('[data-play]'), scrub = q('[data-scrub]'), timeLabel = q('[data-time]'), note = q('[data-note]');
  for (const [label, files] of OUTPUTS) stageSelect.append(el('option', { value: files[0], text: label }));
  if (!OUTPUTS.some(o => o[1][0] === state.labStage)) state.labStage = OUTPUTS[0][1][0];
  stageSelect.value = state.labStage;
  let videos = [], rate = 1, token = 0, rows = [], query = '';

  try { rows = flatten((await api.tree()).runs); }
  catch (e) { showError(e, { key: 'compare' }); }
  const byId = new Map(rows.map(r => [r.node.id, r.node]));
  const rootOf = id => { let n = byId.get(id); while (n && n.parent && byId.has(n.parent)) n = byId.get(n.parent); return n; };
  const family = id => { const root = rootOf(id); return root ? flatten([root]).map(x => x.node.id) : [id]; };
  const text = r => [runName(r), r.preset, runLabel(r), r.changed, r.id.slice(0, 8)].filter(Boolean).join(' ').toLowerCase();

  function drawTray() {
    tray.replaceChildren();
    const picked = new Set(state.labRuns), fam = new Set([...state.labRuns, state.jobId].filter(Boolean).flatMap(family));
    const shown = query ? rows.filter(r => text(r.node).includes(query)) : rows.filter(r => fam.has(r.node.id) || picked.has(r.node.id));
    const list = shown.length ? shown : rows.slice(0, 12);
    for (const { node: r, depth } of list) {
      const input = el('input', { type: 'checkbox', value: r.id }); input.checked = picked.has(r.id);
      input.onchange = () => {
        const next = input.checked ? [...state.labRuns, r.id] : state.labRuns.filter(x => x !== r.id);
        if (next.length > 4) { input.checked = false; notice('Compare takes up to four runs at a time.', { kind: 'warn', key: 'compare', fix: 'Untick one run before picking another.' }); return; }
        setLabRuns(next); syncUrl(); drawTray(); loadTiles();
      };
      const st = runStatus(r);
      tray.append(el('label', { style: 'padding-left:' + (8 + (query ? 0 : depth) * 16) + 'px' }, input, el('span', {}, (depth && !query ? '└ ' : '') + runName(r), ' ', el('span', { class: 'chip ' + st.key, text: st.text }), el('span', { class: 'sub', text: (r.changed ? r.changed + ' · ' : '') + ago(r.created) }))));
    }
    if (!rows.length) tray.append(el('div', { class: 'empty sm', text: 'No runs yet. Start with New run.' }));
    else if (!shown.length && query) tray.append(el('div', { class: 'hint', text: 'No run matches “' + query + '”; the newest runs are listed instead.' }));
    else if (!query && !fam.size) tray.prepend(el('div', { class: 'hint', text: 'The newest runs. Search above to find another one.' }));
  }
  search.oninput = () => { query = search.value.trim().toLowerCase(); drawTray(); };
  drawTray();
  stageSelect.onchange = () => { state.labStage = stageSelect.value; syncUrl(); loadTiles(); };
  function syncUrl() { history.replaceState(null, '', hrefFor({ view: 'compare', runs: state.labRuns, stage: state.labStage })); }

  // ---- sync playback
  const master = () => videos[0];
  function fmt(t) { return (Number.isFinite(t) ? t : 0).toFixed(2); }
  function follow() {
    const m = master(); if (!m) return;
    for (const v of videos.slice(1)) if (Math.abs(v.currentTime - m.currentTime) > 0.08) v.currentTime = m.currentTime;
    if (Number.isFinite(m.duration) && m.duration > 0) scrub.value = Math.round(m.currentTime / m.duration * 1000);
    timeLabel.textContent = fmt(m.currentTime) + ' / ' + fmt(m.duration) + ' s';
  }
  function pauseAll() { for (const v of videos) v.pause(); playButton.textContent = 'Play'; }
  async function playAll() {
    const m = master(); if (!m) return;
    for (const v of videos.slice(1)) v.currentTime = m.currentTime;
    for (const v of videos) v.playbackRate = rate;
    await Promise.allSettled(videos.map(v => v.play()));
    playButton.textContent = 'Pause';
    tiles.scrollIntoView({ block: 'nearest' });   // browsers pause muted media that is off screen
  }
  playButton.onclick = () => { const m = master(); if (!m) return; if (m.paused) playAll(); else pauseAll(); };
  for (const b of $$('[data-speed]', node)) b.onclick = () => { rate = Number(b.dataset.speed); for (const x of $$('[data-speed]', node)) { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); } for (const v of videos) v.playbackRate = rate; };
  scrub.oninput = () => { const m = master(); if (!m || !Number.isFinite(m.duration)) return; const t = scrub.value / 1000 * m.duration; for (const v of videos) v.currentTime = t; timeLabel.textContent = fmt(t) + ' / ' + fmt(m.duration) + ' s'; };
  function wireMaster(m) {
    m.addEventListener('timeupdate', follow); m.addEventListener('seeked', follow); m.addEventListener('loadedmetadata', follow);
    m.addEventListener('pause', () => { for (const v of videos.slice(1)) v.pause(); playButton.textContent = 'Play'; });
    m.addEventListener('play', () => { playButton.textContent = 'Pause'; });
    m.addEventListener('ended', pauseAll);
  }

  // ---- tiles
  async function loadTiles() {
    const mine = ++token;
    pauseAll(); videos = []; tiles.replaceChildren();
    count.textContent = `(${state.labRuns.length} of 4)`;
    const ids = state.labRuns;
    empty.hidden = ids.length >= 2; controls.hidden = ids.length < 2;
    if (ids.length < 2) { empty.textContent = ids.length ? 'Pick one more run to compare.' : 'Pick at least two runs in the list.'; return; }
    let infos, picks = [];
    try {
      [infos, picks] = await Promise.all([Promise.all(ids.map(id => Promise.all([api.run(id), api.files(id)]).then(([run, files]) => ({ id, run, files: new Set(files.files || []) })))), api.picks().then(r => r.picks).catch(() => [])]);
    } catch (e) { if (mine === token) showError(e, { key: 'compare' }); return; }
    if (mine !== token) return;
    const comparison = [...ids].sort().join(',') + ':' + state.labStage;
    const pick = picks.find(p => p.comparison_id === comparison);
    const candidates = (OUTPUTS.find(o => o[1][0] === state.labStage) || OUTPUTS[0])[1];
    const stageLabel = (OUTPUTS.find(o => o[1][0] === state.labStage) || OUTPUTS[0])[0];
    infos.forEach((info, i) => {
      const tile = tpl('tpl-compare-tile'); tiles.append(tile);
      const run = info.run.run || {}, summary = { id: info.id, name: run.name, preset: run.preset, mode: run.mode, created: run.created, parent: run.parent, changed: run.changed };
      $('[data-letter]', tile).textContent = LETTERS[i]; $('[data-name]', tile).textContent = runName(summary);
      const st = runStatus({ state: (info.run.status && info.run.status.state) || run.state, draft: info.files.has('final-preview.mp4'), final: info.files.has('hd/final-preview.mp4') });
      setChip($('[data-state]', tile), st.key, st.text);
      const open = $('[data-open]', tile); open.href = runHref(info.id);
      $('[data-details]', tile).onclick = e => openDetails({ id: info.id, source: e.currentTarget });
      const video = $('[data-video]', tile), missing = $('[data-missing]', tile);
      const file = candidates.find(f => info.files.has(f));
      if (file) { video.src = '/runs/' + info.id + '/' + file; video.muted = i !== 0; if (i === 0) video.removeAttribute('muted'); videos.push(video); }
      else { video.hidden = true; missing.hidden = false; missing.textContent = 'This run has no ' + stageLabel.toLowerCase() + '.'; }
      const diff = $('[data-diff]', tile); diff.replaceChildren();
      if (i === 0) diff.append(el('li', { class: 'same', text: 'The reference recipe (A). The other tiles list how they differ from it.' }));
      else { const lines = chainDiff(infos[0].run.run && infos[0].run.run.chain, run.chain); if (!lines.length) diff.append(el('li', { class: 'same', text: 'The same recipe as A.' })); for (const l of lines) diff.append(el('li', { text: l })); }
      const numbers = $('[data-numbers]', tile); numbers.replaceChildren(); for (const n of reportNumbers(info.run)) numbers.append(el('span', { text: n }));
      const pickButton = $('[data-pick]', tile), picked = $('[data-picked]', tile);
      if (pick && pick.picked === info.id) { tile.classList.add('picked'); picked.hidden = false; picked.textContent = 'Your pick' + (pick.note ? ' · ' + pick.note : ''); pickButton.textContent = 'Picked'; open.classList.add('primary'); }
      pickButton.onclick = async () => {
        pickButton.disabled = true;
        try { await api.pick({ runs: ids, stage: state.labStage, picked: info.id, note: note.value }); notice(LETTERS[i] + ' picked for the ' + stageLabel.toLowerCase() + '. It stays picked after a reload.', { kind: 'ok', key: 'pick' }); loadTiles(); }
        catch (e) { showError(e, { key: 'pick' }); pickButton.disabled = false; }
      };
    });
    if (videos.length) wireMaster(videos[0]);
    for (const v of videos) v.playbackRate = rate;
    if (!videos.length) notice('None of the picked runs has this view; pick another view above.', { kind: 'warn', key: 'compare' });
    follow();
  }
  loadTiles();
}

export { when, shortId };
