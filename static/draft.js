// Steps 03 and 04: create a draft, approve and complete it at full resolution. Both paid buttons show the estimate
// before anything runs and send confirm_cost=true from that click only.
import { api, plain, getJSON, send } from './api.js';
import { $, el, usd, showError, notice, tpl, wireUploads } from './ui.js';
import { state } from './state.js';
import { loadJob, isBusy, pollHD } from './jobdata.js';
import { edits } from './editlayer.js';
import { mountSlots } from './slots.js';   // Set / Look / Light slots (World stage, Agent 1), mounted above the prompt
import { mountExport } from './export.js';   // export kit (World stage, Agent 4), mounted under step 04

export const DEFAULT_PROMPT = "@Image1 defines the character's identity only (face, hair, outfit, proportions); do not copy its pose, expression, props, background or lighting. Pose, motion, timing and lip-sync come from @Video1.";
const REF_EXT = ['png', 'jpg', 'jpeg', 'webp', 'mp4', 'mov', 'webm'];

export function savedReference(files, name) {
  for (const ext of REF_EXT) { const file = name + '-reference.' + ext; if (files.has(file)) return file; }
  return null;
}
const isVideoName = file => /\.(mp4|mov|webm)$/i.test(file || '');

export const providerLabel = name => (state.providers[name] && state.providers[name].label) || name || 'Provider';
export function usableProvider(preferred) {
  const p = state.providers;
  if (preferred && p[preferred]) return preferred;
  if (p[state.providerDefault] && p[state.providerDefault].configured) return state.providerDefault;
  return Object.keys(p).find(n => p[n].configured) || state.providerDefault || Object.keys(p)[0] || '';
}

/** Retry helper for a 402: offer a button that re-sends the same request with the confirmation. */
function costActions(error, resend) {
  const p = plain(error);
  if (p.status !== 402) return [];
  return [{ label: 'Run anyway · ' + usd(p.body.estimated_cost_usd), run: resend }];
}

// ---------------------------------------------------------------- step 03

export function mountDraft(parent) {
  const node = tpl('tpl-draft'); parent.append(node);
  const q = s => $(s, node);
  const form = q('[data-form=seedance]'), select = q('select[name=provider]'), hint = q('[data-provider-hint]'), button = q('[data-draft-button]'), textarea = q('textarea[name=prompt]');
  const thumbs = { char1: q('input[name=char1]').closest('.upload'), char2: q('input[name=char2]').closest('.upload') };
  let filled = false;
  const slots = mountSlots(textarea.closest('label'));

  // dialogue beats from the Words track: timed lines inserted into the prompt, editable before submit (what is in the textarea is sent)
  const beatsButton = el('button', { type: 'button', class: 'small secondary', text: 'Insert dialogue beats', onclick: () => insertBeats() });
  const beatsHint = el('span', { class: 'hint' });
  textarea.closest('label').after(el('div', { class: 'row', style: 'margin-top:8px;align-items:center' }, beatsButton, beatsHint));
  const hasWords = () => (state.files && state.files.has('words.json')) || (edits.jobId === state.jobId && edits.layer.words && Array.isArray(edits.layer.words.words) && edits.layer.words.words.length > 0);
  async function insertBeats() {
    beatsButton.disabled = true;
    try {
      const r = await getJSON('/jobs/' + state.jobId + '/words/beats');
      const lines = textarea.value.split('\n'), start = lines.findIndex(l => l.startsWith('Dialogue beats'));
      if (start >= 0) { let end = start + 1; while (end < lines.length && /^\d+(\.\d+)?–\d+(\.\d+)? s says: /.test(lines[end])) end++; lines.splice(start, end - start, ...r.text.split('\n')); textarea.value = lines.join('\n'); }
      else textarea.value = textarea.value.replace(/\s+$/, '') + '\n\n' + r.text;
      textarea.focus(); textarea.scrollTop = textarea.scrollHeight;
      notice(`Inserted ${r.lines.length} dialogue beat${r.lines.length === 1 ? '' : 's'} from ${r.source === 'edits' ? 'your pending word edits' : 'words.json'}. Edit them as you like; the text in the box is what is sent.`, { kind: 'ok', key: 'beats' });
    } catch (e) { showError(e, { key: 'beats' }); }
    finally { beatsButton.disabled = !hasWords(); }
  }

  wireUploads(form, (input, file) => { if (input.name === 'char1' && file) q('[data-mode-label]').textContent = file.type.startsWith('video/') ? 'Seedance · Omni reference' : 'Seedance · Edit'; });
  select.onchange = () => applyProvider(select.value);

  function fillProviders() {
    if (filled || !Object.keys(state.providers).length) return;
    filled = true; select.replaceChildren();
    for (const [name, c] of Object.entries(state.providers)) select.append(el('option', { value: name, disabled: !c.configured, text: c.label + ' · ' + c.draft_resolution + ' → ' + c.final_resolution + (c.configured ? '' : ' · not configured') }));
    select.value = usableProvider();
  }

  function applyProvider(name) {
    const c = state.providers[name] || state.providers[state.providerDefault];
    if (!c) { hint.textContent = 'No Seedance provider is available. Add FAL_KEY or ENHANCOR_API_KEY to .env and restart the app.'; return; }
    q('[data-provider-label]').textContent = 'Provider · ' + c.label; q('[data-draft-quality]').textContent = 'Draft · ' + c.draft_resolution; q('[data-final-quality]').textContent = 'Final · ' + c.final_resolution;
    hint.textContent = (c.configured ? '' : 'Not configured: add its key to .env and restart the app. ') + (c.needs_webhook ? 'Needs the cloudflared callback tunnel (or ENHANCOR_WEBHOOK_URL). ' : 'No webhook or tunnel needed. ') + 'Hosting: ' + (c.hosting === 'fal_storage' ? 'fal storage' : c.hosting) + '.';
    const estimates = (state.run && state.run.estimates && state.run.estimates.draft) || {};
    button.textContent = 'Create draft · ' + usd(estimates[name]);
  }

  function update() {
    const files = state.files || new Set(), review = state.review || {}, run = (state.run && state.run.run) || {}, generation = state.generation;
    fillProviders();
    if (generation && generation.provider && state.providers[generation.provider]) select.value = generation.provider;
    applyProvider(select.value);
    if (generation && generation.mode) q('[data-mode-label]').textContent = generation.mode === 'multi_reference' ? 'Seedance · Omni reference' : 'Seedance · Edit';
    if (!textarea.dataset.loaded) {
      textarea.value = (generation && generation.prompt) || (run.chain && run.chain.prompt && run.chain.prompt.params && run.chain.prompt.params.text) || DEFAULT_PROMPT;
      textarea.dataset.loaded = 'true';
    }
    for (const name of ['char1', 'char2']) {
      const saved = savedReference(files, name); const label = thumbs[name]; const img = label.querySelector('img'); const input = label.querySelector('input');
      if (saved && !(input.files && input.files.length)) {
        if (!isVideoName(saved)) { img.src = '/runs/' + state.jobId + '/' + saved; img.hidden = false; }
        label.querySelector('[data-filename]').textContent = 'Saved reference · click to replace';
      }
    }
    button.disabled = !files.has('seedance-input.mp4') || isBusy() || !review.approved;
    slots.update();
    beatsButton.disabled = !hasWords();
    beatsHint.textContent = hasWords() ? 'Adds timed lines like  0.0–1.8 s says: "…"  from the transcript (your pending word edits first); edit them before you create the draft.' : 'Transcribe on the Words track in step 02 (free) to insert timed dialogue beats here.';
  }

  form.onsubmit = async e => {
    e.preventDefault();
    const review = state.review || {};
    if (!review.approved) { notice('Review and approve the prepared input first.', { kind: 'warn', fix: 'Tick the review box in step 02 and click Approve input.', key: 'draft' }); return; }
    button.disabled = true;
    let data;
    try {
      data = new FormData(form);
      for (const name of ['char1', 'char2']) {
        if (form.elements[name].files.length) continue;
        const saved = savedReference(state.files, name);
        if (!saved) { data.delete(name); if (name === 'char1') throw new Error("Choose Character 1's reference first."); continue; }
        data.set(name, new File([await (await fetch('/runs/' + state.jobId + '/' + saved)).blob()], saved));
      }
      data.set('confirm_cost', 'true');
    } catch (e2) { showError(e2, { key: 'draft' }); button.disabled = false; return; }
    const submit = async () => { await api.seedance(state.jobId, data); await loadJob(); };
    try { await submit(); }
    catch (e2) { showError(e2, { key: 'draft', actions: costActions(e2, submit) }); button.disabled = false; }
  };
  return { node, update };
}

// ---------------------------------------------------------------- step 04

export function mountFinal(parent) {
  const node = tpl('tpl-final'); parent.append(node);
  const q = s => $(s, node);
  const empty = q('[data-empty]'), ready = q('[data-ready]'), video = q('[data-video]'), quality = q('[data-quality]'), download = q('[data-download]');
  const upgrade = q('[data-upgrade]'), upgradeStatus = q('[data-upgrade-status]'), sent = q('[data-sent]'), finishForm = q('[data-form=finish]');
  wireUploads(finishForm);

  // subtitles: "Burn subtitles into final" (off by default; free, local) + .srt export, from the run's words
  const subs = el('div', { class: 'subs' }); ready.append(subs);
  const exportKit = mountExport(node);   // works with no generation at all: prep → edit → export
  const sub = { state: null, key: '', busy: false, status: '' };
  async function loadSubs(force = false) {
    const files = state.files || new Set();
    const key = state.jobId + '|' + ['final-preview.mp4', 'hd/final-preview.mp4', 'words.json', 'final-preview-subtitled.mp4', 'hd/final-preview-subtitled.mp4'].map(f => (files.has(f) ? 1 : 0)).join('') + '|' + (edits.jobId === state.jobId ? edits.rev : '');
    if (!force && key === sub.key) return;
    sub.key = key;
    try { sub.state = await getJSON('/jobs/' + state.jobId + '/subtitles'); renderSubs(); } catch (e) { showError(e, { key: 'subtitles' }); }
  }
  async function toggleSubs(on) {
    sub.busy = true; sub.status = on ? 'Burning the subtitles in locally (free)… about 10 s for a short clip.' : ''; renderSubs();
    try { sub.state = await send('/jobs/' + state.jobId + '/subtitles', { burn: on ? 'true' : 'false' }); sub.status = ''; }
    catch (e) { sub.status = ''; showError(e, { key: 'subtitles' }); }
    sub.busy = false; renderSubs();
  }
  function renderSubs() {
    const s = sub.state; if (!s) { subs.replaceChildren(); return; }
    const box = el('input', { type: 'checkbox', 'aria-label': 'Burn subtitles into final' }); box.checked = !!s.burn; box.disabled = sub.busy || (!s.words && !s.burn);
    box.onchange = () => toggleSubs(box.checked);
    const made = s.finals.filter(f => f.has_final);
    const line = sub.status ? ['info', sub.status] : !s.words ? ['info', 'No transcript yet: transcribe on the Words track in step 02 (free) to add subtitles.'] : !s.burn ? ['info', `Off: the final has no subtitles (${s.cues} subtitle line${s.cues === 1 ? '' : 's'} ready from ${s.source === 'edits' ? 'your pending word edits' : 'words.json'}).`]
      : s.up_to_date ? ['ok', `On: ${s.cues} subtitle line${s.cues === 1 ? '' : 's'} burned locally into a copy of the final; the untouched final stays as it is.`] : ['warn', 'On, but the words changed since the subtitles were burned (or this final has no subtitled copy yet).'];
    const shown = [...made].reverse().find(f => f.exists);
    const kids = [
      el('label', { class: 'check' }, box, el('span', {}, 'Burn subtitles into final', el('span', { class: 'hint', text: ' · free, runs locally; off by default' }))),
      el('p', { class: 'line ' + line[0], 'aria-live': 'polite', text: line[1] }),
      s.burn && !s.up_to_date && s.words && !sub.busy ? el('div', { class: 'row' }, el('button', { type: 'button', class: 'small', text: 'Burn again · free', onclick: () => toggleSubs(true) })) : null,
      s.burn && shown ? el('video', { src: shown.url + '?v=' + encodeURIComponent(s.updated || ''), controls: true, playsinline: true, preload: 'metadata' }) : null,
      el('div', { class: 'downloads' },
        s.words ? el('a', { href: '/jobs/' + state.jobId + '/subtitles.srt', download: '', text: 'Export subtitles (.srt) ↓' }) : null,
        ...(s.burn ? made.filter(f => f.exists).map(f => el('a', { href: f.url, download: f.subtitled.replace('/', '-'), text: (f.final.startsWith('hd/') ? 'Download HD with subtitles' : 'Download draft with subtitles') + ' ↓' })) : [])),
    ];
    subs.replaceChildren(...kids.filter(Boolean));
  }

  function providerName() {
    const g = state.generation;
    return (g && g.provider && state.providers[g.provider]) ? g.provider : usableProvider();
  }

  function update() {
    const files = state.files || new Set(), base = '/runs/' + state.jobId + '/';
    const hd = files.has('hd/final-preview.mp4'), draft = files.has('final-preview.mp4');
    const caps = state.providers[providerName()] || {};
    const finalRes = caps.final_resolution || 'full resolution';
    empty.hidden = draft || hd; ready.hidden = !(draft || hd);
    if (draft || hd) {
      const url = base + (hd ? 'hd/' : '') + 'final-preview.mp4';
      if (video.dataset.src !== url) { video.dataset.src = url; video.src = url; }
      download.href = url;
      quality.textContent = hd ? finalRes.toUpperCase() + ' · ORIGINAL AUDIO' : 'DRAFT · ORIGINAL AUDIO';
      download.textContent = hd ? 'Download ' + finalRes + ' ↓' : 'Download draft ↓';
      const estimates = (state.run && state.run.estimates && state.run.estimates.complete) || {};
      upgrade.textContent = (caps.finalize_label || 'Approve & generate full resolution →') + ' · ' + usd(estimates[providerName()]);
      q('[data-finalize-hint]').textContent = caps.finalize_hint || ('Approve it to generate the ' + finalRes + ' version through ' + (caps.label || 'the provider') + '.');
      q('[data-finalize-warning]').hidden = caps.finalize_identical !== false;
      const hdRunning = state.hd && state.hd.state === 'running';
      upgrade.disabled = isBusy() || hd || hdRunning;
    }
    if (draft || hd) loadSubs();
    const s = state.hd;
    if (s && s.state && s.state !== 'idle') {
      upgradeStatus.hidden = false; upgradeStatus.className = 'line ' + (s.state === 'error' ? 'error' : s.state === 'done' ? 'ok' : 'info');
    exportKit.update();
      upgradeStatus.textContent = (s.status || '') + (s.state === 'error' && s.fix ? ' ' + s.fix : '');
    } else upgradeStatus.hidden = true;
    const g = state.generation;
    if (g) {
      sent.hidden = false; q('[data-generation-id]').textContent = providerLabel(g.provider) + ' · ' + (g.request_id || ''); q('[data-sent-prompt]').textContent = g.prompt || '';
      q('[data-raw-link]').href = base + 'seedance-result.mp4';
    } else sent.hidden = true;
  }

  upgrade.onclick = async () => {
    upgrade.disabled = true;
    const data = new FormData(); data.set('confirm_cost', 'true');
    const start = async () => { state.hd = await api.hdStart(state.jobId, data); update(); pollHD(); };
    try { await start(); }
    catch (e) { showError(e, { key: 'hd', actions: costActions(e, start) }); upgrade.disabled = false; }
  };

  finishForm.onsubmit = async e => {
    e.preventDefault();
    const b = finishForm.querySelector('button'); b.disabled = true;
    try { await api.finish(state.jobId, new FormData(finishForm)); await loadJob(); notice('Preview ready with the original audio restored.', { kind: 'ok', key: 'finish' }); }
    catch (e2) { showError(e2, { key: 'finish' }); }
    finally { b.disabled = false; }
  };
  return { node, update };
}
