// Step 02: the review panel. Mounted once per view; `update()` refreshes it from state without resetting the video.
// The viewer is the timeline editor (static/editor.js: view switch, playhead, tracks, Save bar), mounted once into
// [data-editor]; it keeps its own state, so polls never reset its videos.
//
// Agent 3 (mask wand): call `registerReviewTool(fn)` from your module; `fn(box, ctx)` runs after every update with
// `box` = the [data-review-tools] element (empty it and draw your controls) and
// `ctx` = {jobId, files, review, video, selected, mode, refresh}. Approval clears by itself after a mask change
// (the fingerprint changes) and `refresh()` reloads the job data.
import { api, plain } from './api.js';
import { $, $$, el, ranges, showError, notice, tpl } from './ui.js';
import { state, navigate } from './state.js';
import { loadJob, fixActions } from './jobdata.js';
import { mountEditor } from './editor.js';
import { backgroundChip } from './slots.js';

export const TABS = [
  ['Prepared input', 'seedance-input.mp4', 'Prepared video with embedded audio'],
  ['Original', 'original.mp4', 'Original video'],
  ['Depth', 'depth.mp4', 'Exact depth colors from the model'],
  ['Mask', 'mask.mp4', 'Full subject mask'],
  ['Composite', 'composite.mp4', 'Depth subject over the original background'],
];

const tools = [];
export function registerReviewTool(fn) { tools.push(fn); }

/** The face-tracking line in plain words. Red only when the run is actually blocked (strict rule failed and the job is in error). */
export function trackingLine(t, jobState, depth) {
  const total = t.frames, tracked = t.tracked, filled = t.filled || 0, missing = t.missing || 0;
  const numbers = `Tracked ${tracked} of ${total} frames` + (filled ? `, ${filled} filled by interpolation (drawn dimmer)` : '') + (missing ? `, ${missing} missing` : '');
  const lost = (t.gaps || []).length ? `Face lost ${ranges(t.gaps)}` : '';
  const standIn = depth ? 'the depth composite stands in there' : 'those frames show the original video without a mesh';
  const lipNote = total && filled > total * 0.1 ? ' Many frames were interpolated; check lip motion closely.' : '';
  if (t.ok === false) {
    if (jobState === 'error') return { level: 'error', text: `${lost || 'Face tracking failed'}; the strict gap rule stopped this run. ${numbers}.` };
    return { level: 'warn', text: `${lost || 'Face tracking had gaps'}; ${standIn}. ${numbers}.${lipNote}` };
  }
  if (lost) return { level: 'warn', text: `${lost}; ${standIn}. ${numbers}.${lipNote}` };
  if (t.warning || lipNote) return { level: 'warn', text: `${numbers}.${lipNote || ' ' + t.warning}` };
  return { level: 'ok', text: `Face tracked throughout. ${numbers}.` };
}

export function mountReview(parent) {
  const node = tpl('tpl-review'); parent.append(node);
  const q = s => $(s, node);
  const progress = q('[data-progress]'), empty = q('[data-empty]'), ready = q('[data-ready]');
  const status = q('[data-review-status]'), tracking = q('[data-tracking]');
  const editor = mountEditor(q('[data-editor]'), { tabs: TABS, onViewChosen: file => { state.previewChosen = true; state.selectedPreview = file; } });
  const check = q('[data-check]'), approve = q('[data-approve]'), reject = q('[data-reject]'), audio = q('[data-audio]'), toolsBox = q('[data-review-tools]');
  const chips = el('div', { class: 'meta slot-chips', hidden: true }); toolsBox.before(chips);   // "Background · …" (World stage)

  check.onchange = () => { approve.disabled = !check.checked; };
  approve.onclick = () => saveReview(true);
  reject.onclick = () => saveReview(false);

  async function saveReview(approved) {
    const review = state.review || {};
    if (!review.fingerprint) return;
    approve.disabled = reject.disabled = true;
    try {
      const data = new FormData();
      data.set('approved', approved ? 'true' : 'false'); data.set('fingerprint', review.fingerprint);
      data.set('note', approved ? 'Prepared input approved after full-clip visual review.' : 'Mask needs correction. Seedance submission is blocked.');
      await api.saveReview(state.jobId, data);
      await loadJob();
    } catch (e) {
      const p = plain(e);
      showError(e, { actions: p.status === 409 ? [{ label: 'Reload the latest preview', run: () => loadJob() }] : [] });
      reject.disabled = false;
    }
  }

  function update() {
    const id = state.jobId, job = state.job || {}, files = state.files || new Set(), review = state.review || {};
    const base = '/runs/' + id + '/';
    const running = job.state === 'running', failed = job.state === 'error';
    const mode = (state.run && state.run.run && state.run.run.mode) || '';
    // progress: while preparing, or after a failure, say so in plain words (the review state is not the problem then)
    progress.hidden = !(running || failed);
    const ptext = $('[data-text]', progress), pfix = $('[data-fix]', progress), pactions = $('[data-actions]', progress);
    if (running) { progress.className = 'status running'; ptext.textContent = 'Preparing… ' + (job.status || ''); pfix.hidden = true; pactions.hidden = true; }
    else if (failed) {
      progress.className = 'status error'; ptext.textContent = 'Preparation failed: ' + (job.status || 'no reason was saved');
      pfix.textContent = job.fix || ''; pfix.hidden = !job.fix;
      const actions = fixActions(); pactions.replaceChildren(); pactions.hidden = !actions.length;
      for (const a of actions) pactions.append(el('button', { type: 'button', class: 'small ' + (a.secondary ? 'secondary' : ''), text: a.label, onclick: async ev => { ev.target.disabled = true; try { await a.run(); } catch (e) { showError(e); ev.target.disabled = false; } } }));
    }
    // previews: the editor (view switch = TABS present in the run, plus views added by tracks)
    const present = TABS.filter(t => files.has(t[1]));
    ready.hidden = !present.length; empty.hidden = !!present.length || running || failed;
    if (present.length) {
      const preferred = state.previewChosen && present.some(t => t[1] === state.selectedPreview) ? state.selectedPreview : present[0][1];
      editor.update({ jobId: id, files, run: state.run, mode, preferred: state.previewChosen ? state.selectedPreview || preferred : preferred });
      state.selectedPreview = editor.view;
    }
    const video = editor.video;
    // review state line
    const lines = {
      preparing: ['info', 'Preparing the clip; the review opens here as soon as it finishes.'],
      failed: ['error', (review.note || 'Preparation failed.') + (review.fix ? ' ' + review.fix : '')],
      unavailable: ['warn', 'The prepared files are not here yet. ' + (review.fix || '')],
      pending: ['info', review.note || 'Review the entire prepared input before approving.'],
      approved: ['ok', 'Approved. ' + (review.note || '')],
      rejected: ['warn', 'Marked as needing fixes. ' + (review.note || '')],
    };
    const [level, text] = lines[review.status] || ['info', review.note || 'Review state unknown.'];
    status.className = 'line ' + level; status.textContent = text;
    // face tracking
    if (state.tracking && typeof state.tracking === 'object') {
      const line = trackingLine(state.tracking, job.state, mode !== 'face_mesh' && files.has('depth.mp4'));
      tracking.className = 'line ' + line.level; tracking.textContent = line.text; tracking.hidden = false;
    } else tracking.hidden = true;
    // background chip
    const chip = backgroundChip(state.run && state.run.run && state.run.run.chain, id);
    chips.hidden = !chip; chips.replaceChildren(...(chip ? [chip] : []));
    // controls
    const canReview = !!review.fingerprint && !running;
    check.disabled = !canReview; check.checked = !!review.approved; approve.disabled = true; reject.disabled = !canReview;
    // audio downloads
    audio.replaceChildren();
    for (const [file, title] of [['vocals.wav', 'Isolated vocals'], ['music.wav', 'Music stem'], ['original-audio.wav', 'Original audio']]) if (files.has(file)) audio.append(el('a', { href: base + file, download: file, text: title + ' ↓' }));
    if (!audio.children.length) audio.append(el('span', { class: 'hint', text: 'The prepared clip carries the original audio; no separate stems were made.' }));
    // extension point
    // ctx.video = the editor's base video of the current view (the old wand lays its overlay over it)
    for (const fn of tools) { try { fn(toolsBox, { jobId: id, files, review, video, selected: state.selectedPreview, mode, refresh: () => loadJob(), editor }); } catch (e) { showError(e, { key: 'review-tool' }); } }
  }
  return { node, update };
}
