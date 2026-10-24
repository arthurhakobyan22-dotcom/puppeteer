// Prompt builder with fences (World stage, Agent 2), mounted into [data-slot=prompt-builder] inside the slots panel of step 03.
// "Build prompt from slots" fills the prompt textarea from POST /jobs/{id}/prompt/assemble (what is in the box is what is sent),
// a refs strip shows every attached reference with its @ImageN / @VideoN number, slot and one-line job, the "Final prompt" preview
// shows the exact text the adapter will send (build_prompt output, `full_prompt`), warnings come from fences_ok, and the paid
// "Describe set & light from this frame" button (POST /jobs/{id}/describe, Claude vision) fills the SET and LIGHT slots.
import { getJSON, send } from './api.js';
import { $, el, usd, showError, notice } from './ui.js';
import { state } from './state.js';

const SLOT_LABEL = { char1: 'Character 1', char2: 'Character 2', set: 'Set', look: 'Look' };

/** The time the viewer is paused on when the timeline editor is open (its active <video>), else null → the middle frame. */
export function viewerTime() {
  const v = document.querySelector('.editor .stage-view video.active') || document.querySelector('.editor .stage-view video');
  return v && Number.isFinite(v.currentTime) && v.readyState >= 1 ? v.currentTime : null;
}

function refThumb(ref) {
  if (ref.kind === 'video') return el('span', { class: 'ref-thumb video', 'aria-label': 'Identity video', text: '▶' });
  const src = ref.slot === 'set' || ref.slot === 'look' ? '/assets/' + ref.file : '/runs/' + state.jobId + '/' + ref.file;
  return el('img', { class: 'ref-thumb', src, alt: SLOT_LABEL[ref.slot] + ' reference' });
}

export function mountPromptBuilder(host, { textarea, select, form, slotsPanel }) {
  if (!host) return { update() {}, refresh() {} };
  const buildButton = el('button', { type: 'button', class: 'small', text: 'Build prompt from slots' });
  const buildHint = el('span', { class: 'hint', text: 'Fills the prompt box from the references, the Set / Look / Light slots and the dialogue beats, with one fence per reference. Edit it as you like: what is in the box is what is sent.' });
  const strip = el('div', { class: 'refs-strip', role: 'list', 'aria-label': 'Attached references' });
  const final = el('pre', { class: 'final-prompt', 'aria-label': 'Final prompt' });
  const finalLine = el('p', { class: 'hint' });
  const warnings = el('ul', { class: 'warnings', hidden: true });
  const describeButton = el('button', { type: 'button', class: 'small secondary' });
  const describeHint = el('span', { class: 'hint' });
  const described = el('p', { class: 'line info', hidden: true, role: 'status' });
  const details = el('details', { class: 'final-box' }, el('summary', {}, 'Final prompt ', el('span', { class: 'hint', text: '· what the adapter sends, with the references beside it' })),
    el('div', { class: 'final-grid' }, el('div', {}, el('h4', { text: 'References · attach in this order' }), strip), el('div', {}, el('h4', { text: 'Text sent' }), final, finalLine)));
  host.append(el('div', { class: 'prompt-builder' },
    el('h4', { text: 'Prompt builder' }),
    el('div', { class: 'row', style: 'align-items:center' }, buildButton, buildHint),
    details, warnings,
    el('div', { class: 'row', style: 'align-items:center' }, describeButton, describeHint), described));

  let last = null, key = '', timer = 0, busy = false;

  function describeEstimate() {
    const t = state.costs && state.costs.tools && state.costs.tools.claude_vision;
    return t ? Number(t.estimate_usd_per_10s_clip || 0) : 0.01;
  }

  /** The assembled result for the current slots; with `useText` the textarea's text is sent so the preview shows what would really go out. */
  async function assemble(useText) {
    const body = { provider: select && select.value ? select.value : '' };
    if (useText && textarea.value.trim()) body.text = textarea.value;
    return send('/jobs/' + state.jobId + '/prompt/assemble', body);
  }

  function render(r) {
    last = r;
    strip.replaceChildren();
    if (!r.refs.length) strip.append(el('span', { class: 'hint', text: 'No reference attached yet. Choose Character 1 above; set and style images come from the slots.' }));
    for (const ref of r.refs) strip.append(el('div', { class: 'ref-card', role: 'listitem', title: ref.fence }, refThumb(ref), el('span', { class: 'ref-token', text: ref.token }), el('span', { class: 'ref-slot', text: SLOT_LABEL[ref.slot] || ref.slot }), el('span', { class: 'ref-job', text: ref.job_line || ref.job })));
    strip.append(el('div', { class: 'ref-card clip', role: 'listitem' }, el('span', { class: 'ref-thumb video', text: '▶' }), el('span', { class: 'ref-token', text: '@Video1' }), el('span', { class: 'ref-slot', text: 'Prepared clip' }), el('span', { class: 'ref-job', text: 'Pose, motion, timing and lip-sync' })));
    final.textContent = r.full_prompt || r.text || '';
    const label = (state.providers[r.provider] && state.providers[r.provider].label) || r.provider || 'the provider';
    finalLine.textContent = r.provider_note ? r.provider_note : 'Sent through ' + label + (r.mode ? ' · ' + (r.mode === 'multi_reference' ? 'omni reference (identity video)' : 'edit') + ' mode' : '') + (r.edited ? ' · from the text in the box' : ' · from the slots') + '. The last lines are the rules the adapter appends.';
    warnings.replaceChildren(...(r.warnings || []).map(w => el('li', { text: w })));
    warnings.hidden = !(r.warnings || []).length;
  }

  async function refresh(useText = true) {
    if (!state.jobId || busy) return;
    busy = true;
    try { render(await assemble(useText)); }
    catch (e) { if (!e || e.status !== 404) showError(e, { key: 'promptkit' }); }
    finally { busy = false; }
  }
  const later = () => { clearTimeout(timer); timer = setTimeout(() => refresh(true), 600); };

  buildButton.onclick = async () => {
    buildButton.disabled = true;
    try {
      const r = await assemble(false);
      textarea.value = r.text; textarea.dataset.loaded = 'true'; textarea.focus();
      render(r);
      const beats = r.beats ? ' Dialogue beats included.' : ' No transcript yet, so no dialogue beats (transcribe on the Words track in step 02).';
      notice(`Prompt built from the slots: ${r.refs.length} reference${r.refs.length === 1 ? '' : 's'} with one fence each.${beats} Edit the text as you like; the box is what is sent.`, { kind: r.warnings.length ? 'warn' : 'ok', fix: r.warnings[0] || '', key: 'promptkit' });
    } catch (e) { showError(e, { key: 'promptkit' }); }
    finally { buildButton.disabled = false; }
  };

  describeButton.onclick = async () => {
    describeButton.disabled = true;
    const t = viewerTime();
    try {
      const r = await send('/jobs/' + state.jobId + '/describe', { t: t == null ? '' : t, confirm_cost: 'true', apply: 'true' });   // the estimate is on the button; this click confirms it
      described.hidden = false;
      described.replaceChildren(el('strong', { text: `Described from the frame at ${Number(r.frame_s).toFixed(1)} s (${usd(r.usd)}, ${r.model}${r.masked ? ', person masked out' : ''}). ` }), el('span', { text: 'SET: ' + (r.set || '—') + '  ·  LIGHT: ' + (r.light || '—') + '  — saved into the Set description and Light fields above; edit them before you create the draft.' }));
      if (slotsPanel && slotsPanel.reload) await slotsPanel.reload();
      for (const w of r.warnings || []) notice(w, { kind: 'warn', key: 'describe-' + w.slice(0, 12) });
      refresh(true);
    } catch (e) { showError(e, { key: 'describe' }); }
    finally { describeButton.disabled = false; }
  };

  textarea.addEventListener('input', later);
  if (select) select.addEventListener('change', () => refresh(true));
  if (form) for (const input of form.querySelectorAll('input[type=file]')) input.addEventListener('change', () => setTimeout(() => refresh(true), 300));
  const saved = slotsPanel && slotsPanel.node && slotsPanel.node.querySelector('[data-saved]');
  if (saved) new MutationObserver(() => { if (/^Saved/.test(saved.textContent)) refresh(true); }).observe(saved, { childList: true, characterData: true, subtree: true });

  function update() {
    const files = state.files || new Set();
    const refs = ['png', 'jpg', 'jpeg', 'webp', 'mp4', 'mov', 'webm'].flatMap(ext => ['char1', 'char2'].map(n => n + '-reference.' + ext)).filter(f => files.has(f)).join(',');
    const k = state.jobId + '|' + refs + '|' + (select ? select.value : '') + '|' + (files.has('words.json') ? 'w' : '') + '|' + (files.has('original.mp4') ? 'o' : '');
    describeButton.textContent = 'Describe set & light from this frame · ' + usd(describeEstimate());
    const t = viewerTime();
    describeHint.textContent = 'Claude looks at one frame of the prepared clip (' + (t == null ? 'the middle one' : 'the one paused in the viewer, ' + t.toFixed(1) + ' s') + ') with the person masked out and fills the Set description and Light fields; you edit them. Paid, about a cent; needs ANTHROPIC_API_KEY in .env.';
    describeButton.disabled = !files.has('original.mp4');
    if (k !== key) { key = k; if (state.jobId !== (last && last.id)) { last = null; described.hidden = true; } refresh(true); }
  }
  return { update, refresh, node: host };
}
