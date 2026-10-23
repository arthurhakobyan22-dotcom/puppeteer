// Steps 03 and 04: create a draft, approve and complete it at full resolution. Both paid buttons show the estimate
// before anything runs and send confirm_cost=true from that click only.
import { api, plain } from './api.js';
import { $, el, usd, showError, notice, tpl, wireUploads } from './ui.js';
import { state } from './state.js';
import { loadJob, isBusy, pollHD } from './jobdata.js';

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
    const s = state.hd;
    if (s && s.state && s.state !== 'idle') {
      upgradeStatus.hidden = false; upgradeStatus.className = 'line ' + (s.state === 'error' ? 'error' : s.state === 'done' ? 'ok' : 'info');
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
