// The Edit step: the timeline editor (static/editor.js: views, viewer, transport, lanes, the active lane's tools, the
// Save bar) plus the approval, which is this step's completion: "I watched the whole clip" + "Approve the prepared
// clip" replaces the Save bar once nothing is unsaved; "Approve again" / "Take the approval back" stay reachable.
// Downloads (this view, the audio stems, every file) are a level-2 panel. `registerReviewTool(fn)` is kept for
// extra tools: fn(box, ctx) runs after every update with ctx = {jobId, files, review, video, selected, mode, refresh, editor}.
import { api, plain } from './api.js';
import { $, el, showError, tpl, when, withCost } from './ui.js';
import { state } from './state.js';
import { loadJob } from './jobdata.js';
import { edits } from './editlayer.js';
import { mountEditor } from './editor.js';
import { downloadLinks } from './stagecard.js';
import { trackingLine } from './prep.js';

export const TABS = [
  ['Prepared clip', 'seedance-input.mp4', 'The clip the generator follows: the picture with the whole original sound'],
  ['Original', 'original.mp4', 'Your original video'],
  ['Depth', 'depth.mp4', 'The depth map, exact colours from the model'],
  ['Mask', 'mask.mp4', 'White where the person is, black elsewhere'],
  ['Motion clip', 'composite.mp4', 'The depth person over the background you chose'],
];

const tools = [];
export function registerReviewTool(fn) { tools.push(fn); }

export function mountEdit(host) {
  const node = tpl('tpl-edit'); host.append(node);
  const q = s => $(s, node);
  const empty = q('[data-empty]'), ready = q('[data-ready]'), toolsBox = q('[data-review-tools]');
  const editor = mountEditor(q('[data-editor]'), { tabs: TABS, onViewChosen: file => { state.previewChosen = true; state.selectedPreview = file; } });
  const approveBar = editor.node.querySelector('[data-approvebar]'), downloadsBox = editor.node.querySelector('[data-downloads-body]'), downloadsDetails = editor.node.querySelector('[data-downloads]');
  let busy = false, reviewed = false;

  async function saveReview(approved) {
    const review = state.review || {};
    if (!review.fingerprint) return;
    busy = true; renderApprove();
    try {
      const data = new FormData();
      data.set('approved', approved ? 'true' : 'false'); data.set('fingerprint', review.fingerprint);
      data.set('note', approved ? 'Approved after watching the whole prepared clip.' : 'Approval taken back; the clip needs another look.');
      await api.saveReview(state.jobId, data);
      await loadJob();
    } catch (e) {
      const p = plain(e);
      showError(e, { actions: p.status === 409 ? [{ label: 'Reload the latest clip', run: () => loadJob() }] : [] });
    } finally { busy = false; renderApprove(); }
  }

  function renderApprove() {
    const review = state.review || {}, job = state.job || {}, running = job.state === 'running';
    const n = edits.jobId === state.jobId ? (edits.pending.total || 0) : 0;
    const canReview = !!review.fingerprint && !running;
    approveBar.hidden = n > 0 || !canReview;
    approveBar.classList.toggle('approved', !!review.approved);
    if (approveBar.hidden) return;
    const kids = [];
    const face = state.tracking && state.tracking.frames ? trackingLine(state.tracking, job.state, ((state.run && state.run.run && state.run.run.mode) || '') !== 'face_mesh' && (state.files || new Set()).has('depth.mp4')) : null;
    if (review.approved) {
      kids.push(el('div', { class: 'sb-summary' }, el('strong', { text: 'Approved ✓' }), el('span', { class: 'hint', text: 'This exact clip is approved' + (review.time ? ' · ' + when(review.time) : '') + '. If you change it, approve it again.' + (face ? ' ' + face.text : '') })));
      kids.push(el('div', { class: 'sb-actions' }, el('button', { type: 'button', class: 'ghost sm', text: 'Take the approval back', disabled: busy, onclick: () => saveReview(false) })));
    } else {
      const check = el('input', { type: 'checkbox', 'aria-label': 'I watched the whole clip' }); check.checked = reviewed;
      const approve = el('button', { type: 'button', class: 'primary', disabled: !reviewed || busy, onclick: () => saveReview(true) }); withCost(approve, busy ? 'Approving…' : 'Approve the prepared clip', '');
      check.onchange = () => { reviewed = check.checked; approve.disabled = !reviewed || busy; };
      kids.push(el('div', { class: 'sb-summary' }, el('strong', { text: review.status === 'rejected' ? 'Not approved yet' : 'Watched the whole clip?' }), el('span', { class: 'hint', text: 'Check the mask (hands, hair, spill), the face mesh (eyes, mouth, alignment) and the sound on every frame; fix what is wrong on the lanes first. Nothing paid runs before this approval.' + (face ? ' ' + face.text : '') })));
      kids.push(el('div', { class: 'sb-actions' }, el('label', { class: 'check' }, check, el('span', { text: 'I watched the whole clip' })), approve));
    }
    approveBar.replaceChildren(...kids);
  }

  function renderDownloads() {
    const id = state.jobId, files = state.files || new Set(), reports = (state.run && state.run.reports) || {};
    const key = id + '|' + files.size + '|' + (editor.view || '');
    if (downloadsBox.dataset.key === key) return; downloadsBox.dataset.key = key;
    const base = '/runs/' + id + '/';
    const links = [];
    const view = editor.view; if (view && files.has(view)) links.push(el('a', { href: base + view, download: view, text: 'This view (' + view + ') ↓' }));
    if ([...files].some(f => f.startsWith('clean-masks/'))) links.push(el('a', { href: '/jobs/' + id + '/download/mask.zip', download: '', text: 'Masks as PNGs (mask.zip) ↓' }));
    for (const [file, title] of [['vocals.wav', 'Isolated vocals'], ['music.wav', 'Music without the voice'], ['original-audio.wav', 'Original audio']]) if (files.has(file)) links.push(el('a', { href: base + file, download: file, text: title + ' (' + file + ') ↓' }));
    const names = [...new Set(Object.values(reports).flatMap(r => Object.keys((r && r.outputs) || {})))];
    links.push(...downloadLinks(id, files, names.filter(n => n !== view)));
    if (files.has('face-landmarks.json') && !names.includes('face-landmarks.json')) links.push(el('a', { href: base + 'face-landmarks.json', download: 'face-landmarks.json', text: 'face-landmarks.json ↓' }));
    downloadsBox.replaceChildren(...(links.length ? links : [el('span', { class: 'hint', text: 'Nothing to download yet.' })]));
    downloadsDetails.hidden = !links.length;
  }

  function update() {
    const id = state.jobId, job = state.job || {}, files = state.files || new Set(), review = state.review || {};
    const running = job.state === 'running', failed = job.state === 'error';
    const mode = (state.run && state.run.run && state.run.run.mode) || '';
    const present = TABS.filter(t => files.has(t[1]));
    ready.hidden = !present.length; empty.hidden = !!present.length;
    empty.querySelector('p').textContent = running ? 'The clip opens here when the preparation finishes.' : failed ? 'The preparation failed, so there is no clip to edit yet. The fix buttons are under Prep.' : 'The prepared files are not in this run yet.';
    if (present.length) {
      const preferred = state.previewChosen && present.some(t => t[1] === state.selectedPreview) ? state.selectedPreview : present[0][1];
      editor.update({ jobId: id, files, run: state.run, mode, preferred: state.previewChosen ? state.selectedPreview || preferred : preferred });
      state.selectedPreview = editor.view;
    }
    if (review.jobId !== id) reviewed = !!review.approved;
    renderApprove(); renderDownloads();
    for (const fn of tools) { try { fn(toolsBox, { jobId: id, files, review, video: editor.video, selected: state.selectedPreview, mode, refresh: () => loadJob(), editor }); } catch (e) { showError(e, { key: 'review-tool' }); } }
  }
  edits.on('change', () => { if (edits.jobId === state.jobId && node.isConnected) renderApprove(); });
  editor.on('view', () => renderDownloads());
  return { node, update, editor };
}
