// Generator slot (Agent 3): which generator renders the draft, what it supports for the chosen slots and at what price.
// Mounted into [data-generator] of the Generate step (static/generate.js). Everything shown comes
// from GET /jobs/{id}/generators (providers/capabilities.py: normalized capabilities, `summary`, `limits` = supports(caps, slots)),
// so the UI never guesses what a generator can do. The choice is saved as slots.generator.name / .resolution (PUT /jobs/{id}/slots)
// and mirrored into the legacy <select name=provider> so the old form field still submits the same value.
import { getJSON, send } from './api.js';
import { el, usd, showError } from './ui.js';
import { state } from './state.js';

const SLOT_LABEL = { set: 'Set', look: 'Look', char2: 'Character 2', char1: 'Character 1', task: 'Task', resolution: 'Resolution', length: 'Length' };

/** `host`: the [data-slot=generator] div. `select`: the legacy provider <select> to keep in sync. `facts()`: {char1_video, char2} for
 *  references picked in the form but not saved yet. `onChange({name, resolution, estimate_usd, caps})` after every choice or reload. */
export function mountGenerator(host, { select = null, facts = () => ({}), onChange = () => {} } = {}) {
  const list = el('div', { class: 'generator-list', role: 'radiogroup', 'aria-label': 'Generator' });
  const summary = el('p', { class: 'hint generator-summary' });
  const limits = el('ul', { class: 'generator-limits', 'aria-label': 'What this generator cannot do here' });
  const resolution = el('select', { 'aria-label': 'Resolution' });
  const resolutionRow = el('label', { class: 'field', hidden: true }, 'Resolution', resolution);
  const draftLine = el('p', { class: 'line info', role: 'status' });
  const node = el('div', { class: 'generator' }, list, summary, limits, resolutionRow, draftLine);
  list.className = 'gens';
  host.replaceChildren(node);
  let data = null, loadedFor = null, chosen = null, busy = false;

  const byName = name => (data && data.generators.find(g => g.name === name)) || null;
  const usable = () => {
    if (!data) return null;
    const saved = state.generation && state.generation.provider && byName(state.generation.provider);
    if (saved) return saved.name;
    if (data.chosen && byName(data.chosen)) return data.chosen;
    const preferred = byName(state.providerDefault);
    if (preferred && preferred.configured) return preferred.name;
    const first = data.generators.find(g => g.configured);
    return first ? first.name : (preferred ? preferred.name : (data.generators[0] || {}).name || null);
  };

  async function load(force = false) {
    const id = state.jobId; if (!id || (loadedFor === id && !force)) return;
    const f = facts() || {};
    const query = [f.char1_video ? 'char1_video=1' : '', f.char2 ? 'char2=1' : ''].filter(Boolean).join('&');
    try { data = await getJSON('/jobs/' + id + '/generators' + (query ? '?' + query : '')); loadedFor = id; chosen = usable(); render(); }
    catch (e) { showError(e, { key: 'generator' }); }
  }
  async function save(patch) {
    const id = state.jobId; if (!id) return;
    busy = true;
    try { await send('/jobs/' + id + '/slots', { generator: patch }, { method: 'PUT' }); await load(true); }
    catch (e) { showError(e, { key: 'generator' }); }
    finally { busy = false; render(); }
  }
  function choose(name) {
    if (!byName(name) || name === chosen) return;
    chosen = name; render();
    const caps = byName(name);
    const res = caps.resolutions.includes(data.resolution) ? data.resolution : null;
    save({ name, resolution: res });
  }
  resolution.onchange = () => save({ resolution: resolution.value });

  /** Unsupported slot choices in the Set / Look selects (slots.js) are disabled with the limit sentence as their title; the
   *  current value stays selectable so the sentence above explains that it is ignored rather than silently changing the slot. */
  function applySlotLimits(caps) {
    const panel = host.closest('.slots'); if (!panel) return;
    const limitFor = slot => caps.limits.find(l => l.slot === slot);
    for (const [box, option, slot] of [['[data-set] select', 'set_ref', 'set_ref'], ['[data-look] select', 'style_ref', 'look_ref']]) {
      const sel = panel.querySelector(box); if (!sel) continue;
      const opt = [...sel.options].find(o => o.value === option); if (!opt) continue;
      const ok = !!caps.slots[slot]; const limit = limitFor(slot === 'look_ref' ? 'look' : 'set');
      opt.disabled = !ok && sel.value !== option;
      opt.title = ok ? '' : (limit ? limit.message + ' ' + limit.fix : caps.label + ' takes no ' + (slot === 'look_ref' ? 'look' : 'set') + ' image here.');
      opt.textContent = opt.textContent.replace(/ · not with .*$/, '') + (ok ? '' : ' · not with ' + caps.label);
    }
  }

  function render() {
    if (!data) return;
    const locked = !!(state.generation && state.generation.provider);   // a draft exists: the generator that made it is shown, not changed
    list.replaceChildren();
    for (const g of data.generators) {
      const active = g.name === chosen;
      const why = g.configured ? g.summary : 'Not set up yet: add ' + g.key + ' to the .env file in the project folder and restart the app.';
      const b = el('button', { type: 'button', class: 'genopt' + (active ? ' on' : '') + (g.configured ? '' : ' off'), role: 'radio', 'aria-checked': active ? 'true' : 'false',
        disabled: busy || locked || !g.configured, title: g.label + ' · ' + why, onclick: () => choose(g.name) },
        el('span', { class: 'radio' }), el('span', {}, el('b', { text: g.label }), el('small', { text: g.configured ? g.summary : why })), el('span', { class: 'price', text: g.configured ? usd(g.estimate_usd) + (g.draft ? ' draft' : ' · one render') : '—' }));
      list.append(b);
    }
    const caps = byName(chosen);
    if (!caps) { summary.hidden = false; summary.textContent = 'No generator is set up yet. Add FAL_KEY or ENHANCOR_API_KEY to .env and restart the app.'; limits.replaceChildren(); resolutionRow.hidden = true; draftLine.hidden = true; return; }
    summary.hidden = true; summary.textContent = '';
    limits.replaceChildren(...caps.limits.map(l => el('li', {}, el('strong', { text: (SLOT_LABEL[l.slot] || l.slot) + ' · ' }), l.message + ' ', el('span', { class: 'hint', text: l.fix }))));
    limits.hidden = !caps.limits.length;
    const offersChoice = caps.resolutions.length > 1 && !caps.draft;   // Seedance drafts are fixed (480p / 1080p); Wan renders once at the chosen resolution
    resolutionRow.hidden = !offersChoice;
    if (offersChoice) {
      resolution.replaceChildren(...caps.resolutions.map(r => el('option', { value: r, text: r + (caps.estimates && caps.estimates[r] != null ? ' · ' + usd(caps.estimates[r]) : '') })));
      resolution.value = caps.resolutions.includes(data.resolution) ? data.resolution : caps.resolutions[0];
      resolution.disabled = busy || locked;
    }
    draftLine.hidden = !!caps.finalize;
    draftLine.textContent = caps.finalize ? '' : 'One render at ' + (offersChoice ? resolution.value : (caps.resolutions[0] || '')) + '. ' + (caps.finalize_hint || 'There is no draft to finish; the first render is the final.');
    applySlotLimits(caps);
    if (select && byName(chosen)) {
      if (![...select.options].some(o => o.value === chosen)) select.append(el('option', { value: chosen, text: caps.label }));
      select.value = chosen;
    }
    onChange({ name: chosen, resolution: offersChoice ? resolution.value : null, estimate_usd: offersChoice && caps.estimates ? caps.estimates[resolution.value] : caps.estimate_usd, caps });
  }
  return {
    node,
    update() { if (state.jobId !== loadedFor) { data = null; chosen = null; } load(); if (data) { const want = usable(); if (want && want !== chosen && state.generation) { chosen = want; } render(); } },
    refresh: () => load(true),
    current: () => ({ name: chosen, caps: byName(chosen) }),
  };
}
