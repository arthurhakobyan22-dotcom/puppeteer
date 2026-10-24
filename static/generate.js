// Generate: the generator (cards from GET /jobs/{id}/generators), the cost line (draft · final · spent), the
// references (Character 1 / 2 as upload tiles, the prepared clip), the read-only prompt mirrored from World & Look
// and ONE primary "Create draft · about $x" (POST /jobs/{id}/seedance; the price on the button is the confirmation,
// a 402 comes back as "Yes, spend about $x"). After a draft: the video, "Make the final · 1080p · about $y"
// (POST /jobs/{id}/hd), "Export instead · free", the "not identical" note only when the generator says so. Level 2
// ("More"): a render made elsewhere (POST /jobs/{id}/finish), the generator details, the submitted prompt and the
// request / response files.
import { api, plain } from './api.js';
import { $, el, usd, spent, showError, notice, tpl, wireUploads, remember, withCost, costActions } from './ui.js';
import { state, goStep } from './state.js';
import { loadJob, isBusy, pollHD } from './jobdata.js';
import { mountGenerator } from './generator.js';
import { worldPrompt } from './world.js';

const REF_EXT = ['png', 'jpg', 'jpeg', 'webp', 'mp4', 'mov', 'webm'];
export function savedReference(files, name) {
  for (const ext of REF_EXT) { const file = name + '-reference.' + ext; if (files.has(file)) return file; }
  return null;
}
const isVideoName = file => /\.(mp4|mov|webm)$/i.test(file || '');
export const providerLabel = name => (state.providers[name] && state.providers[name].label) || name || 'Generator';
export function usableProvider(preferred) {
  const p = state.providers;
  if (preferred && p[preferred]) return preferred;
  if (p[state.providerDefault] && p[state.providerDefault].configured) return state.providerDefault;
  return Object.keys(p).find(n => p[n].configured) || state.providerDefault || Object.keys(p)[0] || '';
}

export function mountGenerate(host) {
  const node = tpl('tpl-generate'); host.append(node); remember(node);
  const q = s => $(s, node);
  const form = q('[data-form=seedance]'), select = q('select[name=provider]'), button = q('[data-draft-button]'), reason = q('[data-reason]'), costline = q('[data-costline]'), promptPre = q('[data-prompt]'), hiddenPrompt = q('textarea[name=prompt]');
  const tiles = { char1: q('[data-ref=char1]'), char2: q('[data-ref=char2]') };
  const draftBox = q('[data-draft]'), video = q('[data-video]'), quality = q('[data-quality]'), download = q('[data-download]'), upgrade = q('[data-upgrade]'), upgradeStatus = q('[data-upgrade-status]'), finalizeHint = q('[data-finalize-hint]'), finalizeWarning = q('[data-finalize-warning]');
  const sent = q('[data-sent]'), finishForm = q('[data-form=finish]'), providerHint = q('[data-provider-hint]');
  q('[data-go="world"]').onclick = () => goStep('world');
  q('[data-export-instead]').onclick = () => goStep('export');
  wireUploads(finishForm);
  let filled = false, generatorChoice = null;

  const refFacts = () => ({ char1_video: !!(form.elements.char1.files[0] && form.elements.char1.files[0].type.startsWith('video/')) || isVideoName(savedReference(state.files || new Set(), 'char1')), char2: !!(form.elements.char2.files[0]) || !!savedReference(state.files || new Set(), 'char2') });
  const generator = mountGenerator(q('[data-generator]'), { select, facts: refFacts, onChange: g => {
    generatorChoice = g; applyProvider(g.name);
    const char2 = tiles.char2, char2Input = char2.querySelector('input'), limit = slot => (g.caps.limits || []).find(l => l.slot === slot);
    char2Input.disabled = !g.caps.slots.char2; char2.classList.toggle('disabled', !g.caps.slots.char2);
    if (!g.caps.slots.char2) char2.querySelector('[data-filename]').textContent = limit('char2') ? limit('char2').message : g.caps.label + ' takes one reference picture: Character 2 is not sent.';
    tiles.char1.querySelector('input').accept = g.caps.slots.identity_video ? 'image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm' : 'image/png,image/jpeg,image/webp';
    worldPrompt.setProvider(g.name);
  } });
  wireUploads(form, (input, file) => { if (file && worldPrompt.refresh) setTimeout(() => worldPrompt.refresh(true), 300); generator.refresh(); update(); });
  select.onchange = () => applyProvider(select.value);
  worldPrompt.onChange(r => { promptPre.textContent = (r && (r.full_prompt || r.text)) || worldPrompt.text() || ''; });

  function fillProviders() {
    if (filled || !Object.keys(state.providers).length) return;
    filled = true; select.replaceChildren();
    for (const [name, c] of Object.entries(state.providers)) select.append(el('option', { value: name, disabled: !c.configured, text: c.label }));
    select.value = usableProvider();
  }
  function applyProvider(name) {
    const c = state.providers[name] || state.providers[state.providerDefault];
    const estimates = (state.run && state.run.estimates) || {};
    const draft = generatorChoice && generatorChoice.name === name && generatorChoice.estimate_usd != null ? generatorChoice.estimate_usd : (estimates.draft || {})[name];
    const fin = (estimates.complete || {})[name];
    const run = (state.run && state.run.run) || {};
    costline.replaceChildren(
      el('span', {}, 'Draft · ' + ((c && c.draft_resolution) || '') + ' · ', el('b', { text: usd(draft) })),
      c && c.finalize !== false && fin != null ? el('span', {}, 'Final · ' + ((c && c.final_resolution) || '1080p') + ' · ', el('b', { text: usd(fin) })) : null,
      el('span', {}, 'Spent so far · ', el('b', { text: spent(run.cost_usd_total) })));
    const hasDraft = (state.files || new Set()).has('final-preview.mp4') || (state.files || new Set()).has('hd/final-preview.mp4');
    withCost(button, hasDraft ? 'Create another draft' : 'Create draft', usd(draft));
    button.classList.toggle('primary', !hasDraft);   // one accent button per screen: after a draft, "Make the final" is it
    providerHint.textContent = c ? c.label + ' · ' + (c.configured ? 'set up' : 'not set up: add its key to .env and restart the app') + ' · ' + (c.needs_webhook ? 'needs the callback tunnel (or ENHANCOR_WEBHOOK_URL)' : 'no tunnel needed') + ' · files are hosted on ' + (c.hosting === 'fal_storage' ? 'fal storage' : c.hosting) + '.' : 'No generator is set up yet. Add FAL_KEY or ENHANCOR_API_KEY to .env and restart the app.';
  }
  function providerName() { const g = state.generation; return (g && g.provider && state.providers[g.provider]) ? g.provider : (select.value || usableProvider()); }

  function update() {
    const files = state.files || new Set(), review = state.review || {}, base = '/runs/' + state.jobId + '/';
    fillProviders();
    if (state.generation && state.generation.provider && state.providers[state.generation.provider]) select.value = state.generation.provider;
    applyProvider(select.value);
    for (const name of ['char1', 'char2']) {
      const saved = savedReference(files, name); const tile = tiles[name]; const img = tile.querySelector('img'); const input = tile.querySelector('input'); const ico = tile.querySelector('[data-ico]');
      if (saved && !(input.files && input.files.length)) {
        if (!isVideoName(saved)) { img.src = base + saved; img.hidden = false; ico.hidden = true; } else { img.hidden = true; ico.hidden = false; ico.textContent = '▶'; }
        tile.querySelector('[data-filename]').textContent = saved + ' · click to replace'; tile.classList.add('has');
      } else if (input.files && input.files.length) { ico.hidden = !img.hidden ? true : false; }
    }
    generator.update();
    promptPre.textContent = (worldPrompt.last && (worldPrompt.last.full_prompt || worldPrompt.last.text)) || worldPrompt.text() || 'Building the prompt…';
    const hasChar1 = !!(savedReference(files, 'char1') || form.elements.char1.files.length);
    const why = !files.has('seedance-input.mp4') ? 'The prepared clip is not ready yet.' : isBusy() ? 'The run is still preparing.' : !review.approved ? 'Approve the clip in Edit first.' : !hasChar1 ? 'Add Character 1 first.' : '';
    button.disabled = !!why;
    reason.replaceChildren(); if (why) reason.append(why, ' ', !review.approved && files.has('seedance-input.mp4') && !isBusy() ? el('button', { type: 'button', class: 'ghost sm', text: 'Go to Edit', onclick: () => goStep('edit') }) : null);
    // draft / final
    const hd = files.has('hd/final-preview.mp4'), draft = files.has('final-preview.mp4'), caps = state.providers[providerName()] || {}, finalRes = caps.final_resolution || '1080p';
    draftBox.hidden = !(draft || hd);
    if (draft || hd) {
      const url = base + (hd ? 'hd/' : '') + 'final-preview.mp4';
      if (video.dataset.src !== url) { video.dataset.src = url; video.src = url; }
      download.href = url; download.setAttribute('download', hd ? 'final.mp4' : 'draft.mp4'); download.textContent = hd ? 'Download the final' : 'Download the draft';
      q('[data-draft-title]').textContent = hd ? 'Final' : 'Draft'; quality.className = 'chip ' + (hd ? 'final' : 'draft'); quality.textContent = hd ? finalRes + ' · original audio' : (caps.draft_resolution || 'draft') + ' · original audio';
      const estimates = (state.run && state.run.estimates && state.run.estimates.complete) || {};
      const noFinalize = caps.name && !caps.finalize;
      upgrade.hidden = !!noFinalize || hd;
      withCost(upgrade, 'Make the final', finalRes + ' · ' + usd(estimates[providerName()]));
      finalizeHint.textContent = hd ? 'The final keeps the whole original audio.' : noFinalize ? (caps.finalize_hint || caps.label + ' renders once: this is the final.') : (caps.finalize_identical ? 'The same draft, rendered at ' + finalRes + '.' : '');
      finalizeWarning.hidden = hd || noFinalize || caps.finalize_identical !== false;
      upgrade.disabled = isBusy() || hd || (state.hd && state.hd.state === 'running');
    }
    const s = state.hd;
    if (s && s.state && s.state !== 'idle') { upgradeStatus.hidden = false; upgradeStatus.className = 'line ' + (s.state === 'error' ? 'error' : s.state === 'done' ? 'ok' : 'info'); upgradeStatus.textContent = (s.status || '') + (s.state === 'error' && s.fix ? ' ' + s.fix : ''); }
    else upgradeStatus.hidden = true;
    const g = state.generation;
    if (g) {
      sent.hidden = false; q('[data-generation-id]').textContent = providerLabel(g.provider) + (g.mode ? ' · ' + (g.mode === 'multi_reference' ? 'reference mode (character video)' : 'edit mode') : '') + ' · request ' + (g.request_id || '—'); q('[data-sent-prompt]').textContent = g.prompt || '';
      const filesBox = q('[data-request-files]'); filesBox.replaceChildren(...['seedance-request.json', 'seedance-response.json', 'generation.json', 'seedance-result.mp4'].filter(f => files.has(f)).map(f => el('a', { href: base + f, target: '_blank', rel: 'noopener', download: f.endsWith('.mp4') ? f : null, text: f })));
    } else sent.hidden = true;
  }

  form.onsubmit = async e => {
    e.preventDefault();
    const review = state.review || {};
    if (!review.approved) { notice('Approve the prepared clip first.', { kind: 'warn', fix: 'Watch the whole clip in Edit, then click "Approve the prepared clip".', key: 'draft' }); return; }
    button.disabled = true;
    let data;
    try {
      hiddenPrompt.value = worldPrompt.text();
      data = new FormData(form);
      for (const name of ['char1', 'char2']) {
        if (form.elements[name].files.length) continue;
        const saved = savedReference(state.files, name);
        if (!saved) { data.delete(name); if (name === 'char1') throw new Error("Choose Character 1's picture first."); continue; }
        data.set(name, new File([await (await fetch('/runs/' + state.jobId + '/' + saved)).blob()], saved));
      }
      data.set('confirm_cost', 'true');   // the price was on the button, so this click is the confirmation
    } catch (e2) { showError(e2, { key: 'draft' }); button.disabled = false; return; }
    const submit = async () => { await api.seedance(state.jobId, data); await loadJob(); };
    try { await submit(); }
    catch (e2) { showError(e2, { key: 'draft', actions: costActions(e2, submit) }); button.disabled = false; }
  };
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
    try { await api.finish(state.jobId, new FormData(finishForm)); await loadJob(); notice('The render is in this run with the original audio put back.', { kind: 'ok', key: 'finish' }); }
    catch (e2) { showError(e2, { key: 'finish' }); }
    finally { b.disabled = false; }
  };
  return { node, update, shown() { if (worldPrompt.refresh && !worldPrompt.last) worldPrompt.refresh(true); } };
}

export { plain };
