// The Prep step of an existing run: a summary card (picture, prep method, the input check in one line, face found /
// lost, the background behind the person, the saved characters), the progress while it prepares (stage rail +
// status), the plain reason and fix buttons when it failed, and a "More" panel (save the recipe as a preset, a link
// to Details · Stages for a new version from one stage).
import { api } from './api.js';
import { $, el, ranges, modeLabel, setChip, showError, notice, tpl, runStatus, stageName, runThumb } from './ui.js';
import { state } from './state.js';
import { fixActions } from './jobdata.js';
import { openDetails } from './drawer.js';
import { BACKGROUND_LABEL } from './slots.js';
import { savedReference } from './generate.js';

const PREP = ['input_doctor', 'audio', 'depth', 'mask', 'composite', 'face'];

/** The face-tracking line in plain words. Red only when the run is actually blocked (strict rule failed and the job is in error). */
export function trackingLine(t, jobState, depth) {
  const total = t.frames, tracked = t.tracked, filled = t.filled || 0, missing = t.missing || 0;
  const numbers = `Face found on ${tracked} of ${total} frames` + (filled ? `, ${filled} filled in (drawn dimmer)` : '') + (missing ? `, ${missing} lost` : '');
  const lost = (t.gaps || []).length ? `Face lost ${ranges(t.gaps)}` : '';
  const standIn = depth ? 'the motion clip stands in there' : 'those frames show the original video without a mesh';
  const lipNote = total && filled > total * 0.1 ? ' Many frames were filled in; check the lip motion closely.' : '';
  if (t.ok === false) {
    if (jobState === 'error') return { level: 'error', text: `${lost || 'The face could not be followed'}; the strict gap rule stopped this run. ${numbers}.` };
    return { level: 'warn', text: `${lost || 'The face was lost for a while'}; ${standIn}. ${numbers}.${lipNote}` };
  }
  if (lost) return { level: 'warn', text: `${lost}; ${standIn}. ${numbers}.${lipNote}` };
  if (t.warning || lipNote) return { level: 'warn', text: `${numbers}.${lipNote || ' ' + t.warning}` };
  return { level: 'ok', text: `Face found throughout. ${numbers}.` };
}

export function mountPrep(host) {
  const node = tpl('tpl-prep'); host.append(node);
  const q = s => $(s, node);
  const form = q('[data-form=preset]');
  let thumbFor = null;
  form.onsubmit = async e => {
    e.preventDefault();
    const button = form.querySelector('button[type=submit]'); button.disabled = true;
    try {
      const r = await api.savePreset({ name: form.name.value, description: form.description.value, job: state.jobId });
      state.presets = (await api.presets()).presets; form.reset();
      notice('Preset "' + r.preset.name + '" saved. It is in the preset list of New run.', { kind: 'ok', key: 'preset' });
    } catch (e2) { showError(e2, { key: 'preset' }); }
    finally { button.disabled = false; }
  };
  q('[data-open-stages]').onclick = e => openDetails({ id: state.jobId, tab: 'stages', source: e.currentTarget });

  function update() {
    const id = state.jobId, job = state.job || {}, files = state.files || new Set(), run = (state.run && state.run.run) || {}, reports = (state.run && state.run.reports) || {};
    const running = job.state === 'running', failed = job.state === 'error';
    if (thumbFor !== id && (files.has('preview.jpg') || files.has('original.mp4'))) { thumbFor = id; const t = runThumb(id, { files }); t.classList.add('thumb'); q('[data-thumb]').replaceWith(t); t.setAttribute('data-thumb', ''); }
    q('[data-title]').textContent = running ? 'Preparing the clip' : failed ? 'Preparation failed' : files.has('seedance-input.mp4') ? 'Prepared clip' : 'Not prepared yet';
    const st = runStatus({ state: job.state, reviewed: !!(state.review && state.review.approved), draft: files.has('final-preview.mp4'), final: files.has('hd/final-preview.mp4') });
    setChip(q('[data-chip]'), st.key, st.text);
    q('[data-method]').textContent = (run.preset ? 'Preset ' + run.preset + ' · ' : '') + modeLabel(run.mode) + (run.parent ? ' · a version' + (run.changed ? ': ' + run.changed : '') : '');
    // progress
    const progress = q('[data-progress]'); progress.hidden = !running;
    if (running) {
      const rail = q('[data-stage-rail]'); rail.replaceChildren();
      const names = ((state.registry && state.registry.stages) || []).map(s => s.name).filter(n => PREP.includes(n));
      const active = names.find(n => !reports[n]);
      for (const n of names) rail.append(el('i', { class: reports[n] ? (reports[n].state === 'error' ? 'e' : 'd') : n === active ? 'c' : '', title: stageName(n) }));
      q('[data-progress-text]').textContent = (active ? stageName(active) + ' · ' : '') + (job.status || 'Working…') + ' · this can take a minute';
    }
    // input check: one line
    const check = q('[data-check]'), doctor = reports.input_doctor, data = (doctor && doctor.data) || {};
    const advice = Array.isArray(data.advice) ? data.advice : [], fixes = Array.isArray(data.fixes) ? data.fixes : [];
    if (doctor && (advice.length || fixes.length || doctor.health)) {
      check.hidden = false; check.className = 'line ' + (advice.length ? 'warn' : 'ok');
      check.textContent = 'Input check: ' + (doctor.health || 'ok') + (fixes.length ? ' · ' + fixes.length + ' safe fix' + (fixes.length === 1 ? '' : 'es') + ' applied' : '') + (advice.length ? ' · ' + advice[0] + (advice.length > 1 ? ' (+' + (advice.length - 1) + ' more in Details)' : '') : '');
    } else check.hidden = true;
    // face
    const face = q('[data-face]');
    if (state.tracking && typeof state.tracking === 'object' && state.tracking.frames) { const line = trackingLine(state.tracking, job.state, run.mode !== 'face_mesh' && files.has('depth.mp4')); face.hidden = false; face.className = 'line ' + line.level; face.textContent = line.text; }
    else face.hidden = true;
    // background
    const comp = (run.chain && run.chain.composite) || {};
    q('[data-background]').textContent = comp.tool === 'depth_cutout' ? 'Background behind the person: ' + (BACKGROUND_LABEL[(comp.params || {}).background || 'original'] || 'original frames').toLowerCase() + ' · change it under World & Look → Set' : comp.tool === 'original' ? 'The original frames are the background (no motion clip in this run).' : '';
    // characters
    const chars = q('[data-chars]'); chars.replaceChildren();
    for (const name of ['char1', 'char2']) {
      const saved = savedReference(files, name);
      chars.append(el('div', { class: 'ref' }, saved && !/\.(mp4|mov|webm)$/i.test(saved) ? el('img', { src: '/runs/' + id + '/' + saved, alt: '' }) : el('i', { text: saved ? '▶' : (name === 'char1' ? '1' : '2') }), el('b', { text: name === 'char1' ? 'Character 1' : 'Character 2' }), el('span', { text: saved ? saved : (name === 'char1' ? 'not chosen yet · add it in Generate' : 'optional') })));
    }
    // failed: fix buttons (the sentence is in the banner)
    const fix = q('[data-fix]'); fix.replaceChildren();
    const actions = failed ? fixActions() : [];
    fix.hidden = !actions.length;
    for (const a of actions) fix.append(el('button', { type: 'button', class: 'sm ' + (a.secondary ? '' : 'primary'), text: a.label, onclick: async ev => { ev.target.disabled = true; try { await a.run(); } catch (e) { showError(e); ev.target.disabled = false; } } }));
  }
  return { node, update };
}
