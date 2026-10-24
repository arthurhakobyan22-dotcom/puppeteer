// World & Look: Set · Look · Light as three slots (slots.json via GET/PUT /jobs/{id}/slots), the Background behind
// the person under Set (the one place it is configured: the set image placement and "Apply as background · free ·
// new version"), "Describe the set and light" with Claude vision (paid, the price on the button; needs an Anthropic
// key), the read-only prompt preview (level 1) and "Edit prompt" (level 2: the text box, rebuild from set & look,
// insert spoken lines, the references list, the task line). The prompt text lives here; Generate reads it through
// `worldPrompt` and mirrors the preview.
import { api, plain, getJSON, send } from './api.js';
import { $, el, usd, showError, notice, tpl, remember, withCost } from './ui.js';
import { state, navigate } from './state.js';
import { edits } from './editlayer.js';
import { SET_MODES, LOOK_MODES, BACKGROUND_FOR, BACKGROUND_LABEL, assetPicker, backgroundControls, fitText, parseFit } from './slots.js';

export const DEFAULT_PROMPT = "@Image1 defines the character's identity only (face, hair, outfit, proportions); do not copy its pose, expression, props, background or lighting. Pose, motion, timing and lip-sync come from @Video1.";
const SLOT_LABEL = { char1: 'Character 1', char2: 'Character 2', set: 'Set', look: 'Look' };

/** The shared prompt: Generate reads the text and mirrors the assembled preview. */
const listeners = new Set();
export const worldPrompt = {
  textarea: null, last: null, provider: '',
  text() { return this.textarea ? this.textarea.value : ''; },
  setProvider(name) { if (name !== this.provider) { this.provider = name; if (this.refresh) this.refresh(true); } },
  onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  refresh: null,
};
const emit = () => { for (const fn of [...listeners]) { try { fn(worldPrompt.last); } catch (e) { console.warn('prompt listener failed', e); } } };

/** The time the viewer is paused on when the timeline editor is open (its active <video>), else null → the middle frame. */
export function viewerTime() {
  const v = document.querySelector('.editor .stage-view video.active') || document.querySelector('.editor .stage-view video');
  return v && Number.isFinite(v.currentTime) && v.readyState >= 1 ? v.currentTime : null;
}

function refThumb(ref) {
  if (ref.kind === 'video') return el('span', { class: 'ref-thumb video', 'aria-label': 'Character video', text: '▶' });
  const src = ref.slot === 'set' || ref.slot === 'look' ? '/assets/' + ref.file : '/runs/' + state.jobId + '/' + ref.file;
  return el('img', { class: 'ref-thumb', src, alt: SLOT_LABEL[ref.slot] + ' reference' });
}

export function mountWorld(host) {
  const node = tpl('tpl-world'); host.append(node); remember(node);
  const q = s => $(s, node);
  const setBox = q('[data-set]'), lookBox = q('[data-look]'), light = q('input[name=light]'), saved = q('[data-saved]');
  const preview = q('[data-prompt-preview]'), warnings = q('[data-warnings]'), textarea = q('textarea[name=prompt]'), refs = q('[data-refs]'), finalLine = q('[data-final-line]'), taskLine = q('[data-task]');
  const describeButton = q('[data-describe]'), describeHint = q('[data-describe-hint]'), described = q('[data-described]'), beatsButton = q('[data-beats]'), beatsHint = q('[data-beats-hint]'), buildButton = q('[data-build]');
  worldPrompt.textarea = textarea;

  // ---- Set / Look / Light
  const modeSelect = (modes, label) => { const s = el('select', { 'aria-label': label }); for (const [name, text, hint] of modes) s.append(el('option', { value: name, text, title: hint })); return s; };
  const setSelect = modeSelect(SET_MODES, 'Set'), lookSelect = modeSelect(LOOK_MODES, 'Look');
  const setHint = el('p', { class: 'hint' }), lookHint = el('p', { class: 'hint' });
  const setPrompt = el('textarea', { rows: 2, placeholder: 'e.g. a small kitchen with a window on the left, white tiles, wooden counter', 'aria-label': 'Set description' });
  const lookPrompt = el('textarea', { rows: 2, placeholder: 'e.g. 16 mm film, muted palette, soft grain, high contrast', 'aria-label': 'Look description' });
  const setPicker = assetPicker({ kind: 'set', label: 'Set images', onChange: name => { slots.set.image = name; save({ set: { image: name } }); } });
  const lookPicker = assetPicker({ kind: 'look', label: 'Look images', onChange: name => { slots.look.image = name; save({ look: { image: name } }); } });
  const setPickerRow = el('div', {}, setPicker.node), lookPickerRow = el('div', {}, lookPicker.node);
  const bgBox = el('div', { class: 'bg-plate' }), bgNote = el('p', { class: 'hint' }), applyButton = el('button', { type: 'button', class: 'sm' }); withCost(applyButton, 'Apply as background', 'free · new version');
  const bgRow = el('div', { class: 'row' }, applyButton);
  setBox.append(setSelect, setHint, setPickerRow, el('label', { class: 'field' }, 'Set description', setPrompt), bgBox, bgNote, bgRow);
  lookBox.append(lookSelect, lookHint, lookPickerRow, el('label', { class: 'field' }, 'Look description', lookPrompt));
  let slots = null, loadedFor = null, timer = 0, busy = false, bgControls = null, bgParams = null, bgKey = '';

  async function load(force = false) {
    const id = state.jobId; if (!id || (loadedFor === id && !force)) return;
    try { slots = await getJSON('/jobs/' + id + '/slots'); loadedFor = id; render(); }
    catch (e) { showError(e, { key: 'slots' }); }
  }
  async function save(patch) {
    const id = state.jobId; if (!id) return;
    saved.textContent = 'Saving…';
    try { slots = await send('/jobs/' + id + '/slots', patch, { method: 'PUT' }); saved.textContent = 'Saved with this run. Nothing re-runs when you change the set, the look or the light.'; render(); refresh(true); }
    catch (e) { saved.textContent = ''; showError(e, { key: 'slots' }); }
  }
  const debounced = patch => { clearTimeout(timer); timer = setTimeout(() => save(patch), 500); };
  setSelect.onchange = () => {
    const patch = { mode: setSelect.value };
    const plate = ((((state.run && state.run.run && state.run.run.chain) || {}).composite || {}).params || {}).set_image;
    if (setSelect.value === 'true_swap' && !slots.set.image && plate) patch.image = plate;   // the run already has an image behind the person: start from it
    slots.set.mode = patch.mode; if (patch.image) slots.set.image = patch.image; save({ set: patch });
  };
  lookSelect.onchange = () => { slots.look.mode = lookSelect.value; save({ look: { mode: lookSelect.value } }); };
  setPrompt.oninput = () => debounced({ set: { prompt: setPrompt.value } });
  lookPrompt.oninput = () => debounced({ look: { prompt: lookPrompt.value } });
  light.oninput = () => debounced({ light: light.value });

  applyButton.onclick = async () => {
    if (!slots) return;
    const needed = BACKGROUND_FOR[slots.set.mode]; if (!needed) return;
    const fit = bgParams && bgParams.set_fit !== undefined ? bgParams.set_fit : fitText(slots.set.fit);
    const params = needed === 'set_image' ? { background: 'set_image', set_image: slots.set.image || '', set_fit: fit || '' } : { background: 'full_depth' };
    if (needed === 'set_image' && !slots.set.image) { notice('Choose or upload the set image first.', { kind: 'warn', fix: 'Pick a picture in the Set images list; it goes behind the person.', key: 'slots' }); return; }
    applyButton.disabled = true; busy = true;
    const go = async confirm => {
      const body = { stage: 'composite', tool: 'depth_cutout', params }; if (confirm) body.confirm_cost = 'true';
      const r = await api.branch(state.jobId, body);
      const patch = { set: { mode: slots.set.mode, image: slots.set.image, prompt: slots.set.prompt, fit: fit ? parseFit(fit) : slots.set.fit }, look: slots.look, light: slots.light, generator: slots.generator };
      try { await send('/jobs/' + r.id + '/slots', patch, { method: 'PUT' }); } catch (e) { showError(e, { key: 'slots' }); }
      navigate({ job: r.id, step: 'prep' });
      notice('New version with the ' + BACKGROUND_LABEL[needed].toLowerCase() + ' background (this one). The motion clip and the face mesh run again on this computer, free; the run you came from stays as it was.', { kind: 'ok', key: 'slots' });
    };
    try { await go(false); }
    catch (e) { const p = plain(e); showError(e, { key: 'slots', actions: p.status === 402 ? [{ label: 'Yes, spend ' + usd(p.body.estimated_cost_usd), run: () => go(true), primary: true }] : [] }); }
    finally { busy = false; applyButton.disabled = false; }
  };

  function renderBackground(run, composite) {
    const needed = BACKGROUND_FOR[slots.set.mode], can = !!needed && composite.tool === 'depth_cutout';
    const key = state.jobId + '|' + slots.set.mode + '|' + (slots.set.image || '') + '|' + composite.tool;
    bgRow.hidden = !needed; bgBox.hidden = !(needed === 'set_image' && can);
    if (!needed) { bgNote.textContent = ''; bgKey = ''; bgBox.replaceChildren(); return; }
    if (composite.tool !== 'depth_cutout') { bgNote.textContent = 'This run has no motion clip (the original frames are the background), so there is nothing to put behind the person. Prepare the clip with a Motion clip preset (Full body, Expressive) to use this set mode.'; bgBox.replaceChildren(); bgKey = ''; return; }
    if (slots.background_applied) bgNote.textContent = 'Done in this run: the motion clip already has the ' + BACKGROUND_LABEL[needed].toLowerCase() + ' background.';
    else bgNote.textContent = 'This set mode needs the ' + BACKGROUND_LABEL[needed].toLowerCase() + ' background behind the person (this run has ' + (slots.background === needed ? 'a different set image' : (slots.background_label || 'the original frames').toLowerCase()) + '). "Apply as background" makes a new version with it and keeps these settings there.';
    if (needed === 'set_image' && key !== bgKey) {   // the placement canvas: the same component as the Motion clip stage row in Details
      bgKey = key; bgBox.replaceChildren();
      const tool = (((state.registry || {}).stages || []).find(s => s.name === 'composite') || { tools: [] }).tools.find(t => t.name === 'depth_cutout') || { params: {} };
      bgParams = { background: 'set_image', set_image: slots.set.image || '', set_fit: fitText(slots.set.fit) };
      const holder = el('div');
      bgControls = backgroundControls(holder, { tool, params: bgParams, set: (name, value) => { bgParams[name] = value; if (name === 'set_image' && value !== slots.set.image) { slots.set.image = value; save({ set: { image: value } }); } if (name === 'set_fit') debounced({ set: { fit: parseFit(value) } }); }, jobId: state.jobId });
      const bgSelectLabel = holder.querySelector('label.field'); if (bgSelectLabel) bgSelectLabel.hidden = true;   // the background kind follows the set mode here
      const plainRow = holder.querySelector('label.field + label.field'); if (plainRow) plainRow.hidden = true;
      bgBox.append(holder);
    }
    applyButton.disabled = busy || !can || (state.job && state.job.state === 'running') || !!slots.background_applied;
  }

  function render() {
    if (!slots) return;
    const run = (state.run && state.run.run) || {}, chain = run.chain || {}, composite = chain.composite || {};
    setSelect.value = slots.set.mode; lookSelect.value = slots.look.mode;
    setHint.textContent = (SET_MODES.find(m => m[0] === slots.set.mode) || [])[2] || ''; lookHint.textContent = (LOOK_MODES.find(m => m[0] === slots.look.mode) || [])[2] || '';
    if (document.activeElement !== setPrompt) setPrompt.value = slots.set.prompt || '';
    if (document.activeElement !== lookPrompt) lookPrompt.value = slots.look.prompt || '';
    if (document.activeElement !== light) light.value = slots.light || '';
    setPicker.set(slots.set.image); lookPicker.set(slots.look.image);
    const needsImage = ['set_ref', 'true_swap'].includes(slots.set.mode);
    setPickerRow.hidden = !needsImage || slots.set.mode === 'true_swap'; setPrompt.closest('label').hidden = slots.set.mode !== 'prompt';
    lookPickerRow.hidden = slots.look.mode !== 'style_ref'; lookPrompt.closest('label').hidden = slots.look.mode !== 'prompt';
    renderBackground(run, composite);
    const provider = (state.generation && state.generation.provider) || (slots.generator && slots.generator.name) || '';
    const caps = state.providers[provider] || null;
    const noTask = !!(caps && Array.isArray(caps.tasks) && !caps.tasks.length);
    const why = slots.task_source === 'user' ? 'chosen by you' : slots.set.mode === 'original' ? 'the set is the original' : 'the set changed';
    taskLine.textContent = 'Generator task: ' + slots.task + ' (' + why + ')' + (noTask ? '. ' + caps.label + ' has no task setting' + (caps.control === 'pose' ? ' (it always keeps the pose and timing of the prepared clip)' : ' (it always edits the prepared clip)') + '.' : '.');
  }

  // ---- prompt: preview (level 1), editor (level 2)
  let key = '', ptimer = 0, pbusy = false;
  async function assemble(useText) {
    const body = { provider: worldPrompt.provider || '' };
    if (useText && textarea.value.trim()) body.text = textarea.value;
    return send('/jobs/' + state.jobId + '/prompt/assemble', body);
  }
  function renderPrompt(r) {
    worldPrompt.last = r;
    preview.textContent = r.full_prompt || r.text || '';
    refs.replaceChildren();
    if (!r.refs.length) refs.append(el('span', { class: 'hint', text: 'No reference attached yet. Choose Character 1 under Generate; set and look images come from the slots.' }));
    for (const ref of r.refs) refs.append(el('div', { class: 'ref-card', role: 'listitem', title: ref.fence }, refThumb(ref), el('span', { class: 'ref-token', text: ref.token }), el('span', { class: 'ref-slot', text: SLOT_LABEL[ref.slot] || ref.slot }), el('span', { class: 'ref-job', text: ref.job_line || ref.job })));
    refs.append(el('div', { class: 'ref-card clip', role: 'listitem' }, el('span', { class: 'ref-thumb video', text: '▶' }), el('span', { class: 'ref-token', text: '@Video1' }), el('span', { class: 'ref-slot', text: 'Prepared clip' }), el('span', { class: 'ref-job', text: 'Pose, motion, timing and lip-sync' })));
    const label = (state.providers[r.provider] && state.providers[r.provider].label) || r.provider || 'the generator';
    finalLine.textContent = r.provider_note ? r.provider_note : 'Sent through ' + label + (r.mode ? ' · ' + (r.mode === 'multi_reference' ? 'reference mode (character video)' : 'edit mode') : '') + (r.edited ? ' · from the text in the box' : ' · built from the set, the look and the light') + '. The last lines are the rules added for the generator.';
    warnings.replaceChildren(...(r.warnings || []).map(w => el('li', { text: w })));
    warnings.hidden = !(r.warnings || []).length;
    emit();
  }
  async function refresh(useText = true) {
    if (!state.jobId || pbusy) return;
    pbusy = true;
    try { renderPrompt(await assemble(useText)); }
    catch (e) { if (!e || e.status !== 404) showError(e, { key: 'promptkit' }); }
    finally { pbusy = false; }
  }
  worldPrompt.refresh = refresh;
  textarea.addEventListener('input', () => { clearTimeout(ptimer); ptimer = setTimeout(() => refresh(true), 600); });
  buildButton.onclick = async () => {
    buildButton.disabled = true;
    try {
      const r = await assemble(false);
      textarea.value = r.text; textarea.dataset.loaded = 'true';
      renderPrompt(r);
      notice(`Prompt rebuilt: ${r.refs.length} reference${r.refs.length === 1 ? '' : 's'}, one rule each.` + (r.beats ? ' Spoken lines included.' : ' No words yet, so no spoken lines (transcribe on the Words lane in Edit).'), { kind: r.warnings.length ? 'warn' : 'ok', fix: r.warnings[0] || '', key: 'promptkit' });
    } catch (e) { showError(e, { key: 'promptkit' }); }
    finally { buildButton.disabled = false; }
  };
  const hasWords = () => (state.files && state.files.has('words.json')) || (edits.jobId === state.jobId && edits.layer.words && Array.isArray(edits.layer.words.words) && edits.layer.words.words.length > 0);
  beatsButton.onclick = async () => {
    beatsButton.disabled = true;
    try {
      const r = await getJSON('/jobs/' + state.jobId + '/words/beats');
      const lines = textarea.value.split('\n'), start = lines.findIndex(l => l.startsWith('Dialogue beats'));
      if (start >= 0) { let end = start + 1; while (end < lines.length && /^\d+(\.\d+)?–\d+(\.\d+)? s says: /.test(lines[end])) end++; lines.splice(start, end - start, ...r.text.split('\n')); textarea.value = lines.join('\n'); }
      else textarea.value = textarea.value.replace(/\s+$/, '') + '\n\n' + r.text;
      textarea.focus(); textarea.scrollTop = textarea.scrollHeight; refresh(true);
      notice(`Inserted ${r.lines.length} spoken line${r.lines.length === 1 ? '' : 's'} from ${r.source === 'edits' ? 'your unsaved word edits' : 'the transcript'}. Edit them as you like; the text in the box is what is sent.`, { kind: 'ok', key: 'beats' });
    } catch (e) { showError(e, { key: 'beats' }); }
    finally { beatsButton.disabled = !hasWords(); }
  };
  const describeEstimate = () => { const t = state.costs && state.costs.tools && state.costs.tools.claude_vision; return t ? Number(t.estimate_usd_per_10s_clip || 0) : 0.01; };
  describeButton.onclick = async () => {
    describeButton.disabled = true;
    const t = viewerTime();
    try {
      const r = await send('/jobs/' + state.jobId + '/describe', { t: t == null ? '' : t, confirm_cost: 'true', apply: 'true' });   // the price is on the button; this click confirms it
      described.hidden = false;
      described.replaceChildren(el('strong', { text: `Described from the frame at ${Number(r.frame_s).toFixed(1)} s (${usd(r.usd)}${r.masked ? ', person masked out' : ''}). ` }), el('span', { text: 'Set: ' + (r.set || '—') + '  ·  Light: ' + (r.light || '—') + ' — saved into the Set description and Light fields; edit them before you create the draft.' }));
      await load(true);
      for (const w of r.warnings || []) notice(w, { kind: 'warn', key: 'describe-' + w.slice(0, 12) });
      refresh(true);
    } catch (e) { showError(e, { key: 'describe' }); }
    finally { describeButton.disabled = false; }
  };

  function update() {
    const files = state.files || new Set(), run = (state.run && state.run.run) || {}, generation = state.generation;
    if (state.jobId !== loadedFor) { slots = null; saved.textContent = ''; described.hidden = true; textarea.dataset.loaded = ''; }
    load(); if (slots) render();
    if (!textarea.dataset.loaded) { textarea.value = (generation && generation.prompt) || (run.chain && run.chain.prompt && run.chain.prompt.params && run.chain.prompt.params.text) || DEFAULT_PROMPT; textarea.dataset.loaded = 'true'; }
    beatsButton.disabled = !hasWords();
    beatsHint.textContent = hasWords() ? 'Adds timed lines like  0.0–1.8 s says: "…"  from the words (your unsaved word edits first), so the generator keeps the dialogue timing.' : 'Transcribe on the Words lane in Edit (free) to insert timed spoken lines here.';
    withCost(describeButton, 'Describe the set and light from this frame', usd(describeEstimate()));
    const t = viewerTime();
    describeHint.textContent = 'Claude looks at one frame of the prepared clip (' + (t == null ? 'the middle one' : 'the one paused in Edit, ' + t.toFixed(1) + ' s') + ') with the person masked out and fills the Set description and the Light. Needs an Anthropic key (ANTHROPIC_API_KEY in .env).';
    describeButton.disabled = !files.has('original.mp4');
    const refsKey = ['png', 'jpg', 'jpeg', 'webp', 'mp4', 'mov', 'webm'].flatMap(ext => ['char1', 'char2'].map(n => n + '-reference.' + ext)).filter(f => files.has(f)).join(',');
    const k = state.jobId + '|' + refsKey + '|' + worldPrompt.provider + '|' + (files.has('words.json') ? 'w' : '') + '|' + (files.has('original.mp4') ? 'o' : '');
    if (k !== key) { key = k; refresh(true); }
  }
  return { node, update, refresh: () => refresh(true) };
}
