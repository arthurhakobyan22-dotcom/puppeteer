// Lab: 2–4 runs side by side, one stage output, played in sync from one master clock; chain differences and
// report numbers per tile; an "A or B?" pick per comparison stored by the app (survives reload).
import { api } from './api.js';
import { $, $$, el, spent, when, ranges, runLabel, setChip, showError, notice, tpl, shortId } from './ui.js';
import { state, setLabRuns, hrefFor } from './state.js';

export const OUTPUTS = [
  ['Prepared input', ['seedance-input.mp4']], ['Original', ['original.mp4']], ['Depth', ['depth.mp4']], ['Mask', ['mask.mp4']],
  ['Composite', ['composite.mp4', 'depth-composite-silent.mp4', 'composite-silent.mp4']], ['Draft', ['final-preview.mp4']], ['Final', ['hd/final-preview.mp4']],
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
    if ((a.tool || 'off') !== (b.tool || 'off')) { lines.push(`${stage}: ${a.tool || 'off'} → ${b.tool || 'off'}`); continue; }
    const keys = new Set([...Object.keys(a.params || {}), ...Object.keys(b.params || {})]);
    for (const k of keys) {
      const va = (a.params || {})[k], vb = (b.params || {})[k];
      if (JSON.stringify(va) !== JSON.stringify(vb)) lines.push(`${stage}: ${k} ${String(va)} → ${String(vb)}`.replace(/@Image1 defines[^]*?@Video1\./g, 'built-in prompt'));
    }
  }
  return lines;
}

export function reportNumbers(info) {
  const reports = (info && info.reports) || {}, out = [];
  const face = reports.face, mask = reports.mask, probe = reports.input_doctor;
  if (probe && probe.frames && probe.frames.covered != null) out.push(`${probe.frames.covered} frames`);
  if (mask && mask.tool !== 'off' && mask.frames && mask.frames.covered != null) out.push(`mask on ${mask.frames.covered} frames`);
  if (face && face.tool !== 'off' && face.frames && face.frames.covered != null) out.push(`face tracked ${face.frames.covered}` + (face.frames.filled ? `, filled ${face.frames.filled}` : '') + (face.frames.missing ? `, missing ${face.frames.missing}` : '') + ((face.gaps || []).length ? ` · lost ${ranges(face.gaps)}` : ''));
  out.push('spent ' + spent(info && info.run && info.run.cost_usd_total));
  return out;
}

export async function renderLab(container) {
  const node = tpl('tpl-lab'); container.append(node);
  const q = s => $(s, node);
  const picker = q('[data-picker]'), count = q('[data-count]'), stageSelect = q('[data-stage]'), tiles = q('[data-tiles]'), empty = q('[data-empty]'), controls = q('[data-controls]');
  const playButton = q('[data-play]'), scrub = q('[data-scrub]'), timeLabel = q('[data-time]'), note = q('[data-note]');
  for (const [label, files] of OUTPUTS) stageSelect.append(el('option', { value: files[0], text: label }));
  if (!OUTPUTS.some(o => o[1][0] === state.labStage)) state.labStage = OUTPUTS[0][1][0];
  stageSelect.value = state.labStage;
  let videos = [], rate = 1, token = 0;

  // ---- picker
  let rows = [];
  try { rows = flatten((await api.tree()).runs); }
  catch (e) { showError(e, { key: 'lab' }); }
  function drawPicker() {
    picker.replaceChildren();
    for (const { node: r, depth } of rows) {
      const input = el('input', { type: 'checkbox', value: r.id }); input.checked = state.labRuns.includes(r.id);
      input.onchange = () => {
        const next = input.checked ? [...state.labRuns, r.id] : state.labRuns.filter(x => x !== r.id);
        if (next.length > 4) { input.checked = false; notice('The Lab compares up to four runs at a time.', { kind: 'warn', key: 'lab', fix: 'Untick one run before adding another.' }); return; }
        setLabRuns(next); syncUrl(); loadTiles();
      };
      picker.append(el('label', { style: 'padding-left:' + (8 + depth * 16) + 'px' }, input, el('span', {}, (depth ? '└ ' : '') + runLabel(r) + ' · ' + shortId(r.id) + '…', el('span', { class: 'sub', text: (r.changed ? r.changed + ' · ' : '') + when(r.created) + ' · ' + r.state }))));
    }
    if (!rows.length) picker.append(el('div', { class: 'empty', text: 'No runs yet. Prepare a video in Quick first.' }));
  }
  drawPicker();
  stageSelect.onchange = () => { state.labStage = stageSelect.value; syncUrl(); loadTiles(); };
  function syncUrl() { history.replaceState(null, '', hrefFor({ view: 'lab', runs: state.labRuns, stage: state.labStage })); }

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
    // Browsers pause muted media that is off screen; keep the tiles in view while they play.
    tiles.scrollIntoView({ block: 'nearest' });
  }
  playButton.onclick = () => { const m = master(); if (!m) return; if (m.paused) playAll(); else pauseAll(); };
  for (const b of $$('[data-speed]', node)) b.onclick = () => { rate = Number(b.dataset.speed); for (const x of $$('[data-speed]', node)) x.classList.toggle('active', x === b); for (const v of videos) v.playbackRate = rate; };
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
    if (ids.length < 2) { empty.textContent = ids.length ? 'Choose one more run to compare.' : 'Choose at least two runs above.'; return; }
    let infos, picks = [];
    try {
      [infos, picks] = await Promise.all([Promise.all(ids.map(id => Promise.all([api.run(id), api.files(id)]).then(([run, files]) => ({ id, run, files: new Set(files.files || []) })))), api.picks().then(r => r.picks).catch(() => [])]);
    } catch (e) { if (mine === token) showError(e, { key: 'lab' }); return; }
    if (mine !== token) return;
    const comparison = [...ids].sort().join(',') + ':' + state.labStage;
    const pick = picks.find(p => p.comparison_id === comparison);
    const candidates = (OUTPUTS.find(o => o[1][0] === state.labStage) || OUTPUTS[0])[1];
    const stageLabel = (OUTPUTS.find(o => o[1][0] === state.labStage) || OUTPUTS[0])[0];
    infos.forEach((info, i) => {
      const tile = tpl('tpl-lab-tile'); tiles.append(tile);
      const run = info.run.run || {}, summary = { preset: run.preset, mode: run.mode };
      $('[data-letter]', tile).textContent = LETTERS[i]; $('[data-name]', tile).textContent = runLabel(summary) + (run.changed ? ' · ' + run.changed : '');
      setChip($('[data-state]', tile), (info.run.status && info.run.status.state) || run.state || 'unknown'); $('[data-id]', tile).textContent = info.id;
      $('[data-open]', tile).href = hrefFor({ job: info.id, view: 'studio' }); $('[data-open]', tile).setAttribute('data-nav', '');
      const video = $('[data-video]', tile), missing = $('[data-missing]', tile);
      const file = candidates.find(f => info.files.has(f));
      if (file) { video.src = '/runs/' + info.id + '/' + file; video.muted = i !== 0; if (i === 0) video.removeAttribute('muted'); videos.push(video); }
      else { video.hidden = true; missing.hidden = false; missing.textContent = 'This run has no ' + stageLabel.toLowerCase() + ' output.'; }
      const diff = $('[data-diff]', tile); diff.replaceChildren();
      if (i === 0) diff.append(el('li', { class: 'same', text: 'Reference chain (A). The other tiles list how they differ from it.' }));
      else { const lines = chainDiff(infos[0].run.run && infos[0].run.run.chain, run.chain); if (!lines.length) diff.append(el('li', { class: 'same', text: 'Same chain as A.' })); for (const l of lines) diff.append(el('li', { text: l })); }
      const numbers = $('[data-numbers]', tile); numbers.replaceChildren(); for (const n of reportNumbers(info.run)) numbers.append(el('span', { text: n }));
      const pickButton = $('[data-pick]', tile), picked = $('[data-picked]', tile);
      if (pick && pick.picked === info.id) { tile.classList.add('picked'); picked.hidden = false; picked.textContent = 'Your pick' + (pick.note ? ' · ' + pick.note : ''); pickButton.textContent = 'Picked'; }
      pickButton.onclick = async () => {
        pickButton.disabled = true;
        try { await api.pick({ runs: ids, stage: state.labStage, picked: info.id, note: note.value }); notice(LETTERS[i] + ' picked for ' + stageLabel.toLowerCase() + '. Saved; it will still be here after a reload.', { kind: 'ok', key: 'pick' }); loadTiles(); }
        catch (e) { showError(e, { key: 'pick' }); pickButton.disabled = false; }
      };
    });
    if (videos.length) wireMaster(videos[0]);
    for (const v of videos) v.playbackRate = rate;
    if (!videos.length) notice('None of the chosen runs has this output; pick another output above.', { kind: 'warn', key: 'lab' });
    follow();
  }
  loadTiles();
}
