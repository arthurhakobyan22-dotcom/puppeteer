// The Runs page: one card per original run (thumbnail, name with inline rename, status chip, spent, prep method,
// time, its versions on demand, Open, Details), search, status filters, "Pick to compare", 24 cards a page.
// `&flat=1` keeps the plain list (every run, newest first). Data: GET /jobs/tree (cards) and GET /jobs (list).
import { api, plain } from './api.js';
import { $, $$, el, spent, ago, when, runName, runLabel, runStatus, setChip, showError, notice, tpl, remember, runThumb, filesOf, usd, shortId } from './ui.js';
import { state, setLabRuns, hrefFor, runHref, navigate } from './state.js';
import { openDetails } from './drawer.js';

const PAGE = 24;
const FILTERS = [['all', 'All'], ['review', 'Needs review'], ['ready', 'Ready'], ['draft', 'Draft done'], ['final', 'Final done'], ['preparing', 'Preparing'], ['failed', 'Failed']];

const familyText = r => [runName(r), r.preset, runLabel(r), r.changed, r.status, r.name, r.id.slice(0, 8)].filter(Boolean).join(' ').toLowerCase();
const matches = (r, q) => !q || familyText(r).includes(q) || (r.children || []).some(c => matches(c, q));
const statusKey = r => runStatus(r).key;
const familyKeys = r => new Set([statusKey(r), ...(r.children || []).flatMap(c => [...familyKeys(c)])]);

/** One sentence under the name: what the run is and what it waits for. */
function summaryLine(r) {
  const st = runStatus(r).key, method = runLabel(r);
  if (st === 'preparing') return (r.status || 'Preparing…');
  if (st === 'failed') return '';
  if (st === 'final') return 'The final is done. Download or export it.';
  if (st === 'draft') return 'A draft is waiting for you. Judge it, then make the final or export.';
  if (st === 'ready') return 'Approved. Choose the world and the prompt, then create the draft.';
  if (st === 'review') return 'Prepared with ' + method + '. Watch the whole clip and approve it before anything paid runs.';
  return r.status || '';
}
const openLabel = r => ({ review: 'Review the clip', ready: 'Open', draft: 'Open the draft', final: 'Open the final', failed: 'Open', preparing: 'Watch' })[runStatus(r).key] || 'Open';
const openStep = r => ({ review: 'edit', ready: 'generate', draft: 'generate', final: 'generate', failed: 'prep', preparing: 'prep' })[runStatus(r).key] || null;

function renameWidget(nameEl, button, form, r, onSaved) {
  button.onclick = () => { form.hidden = false; nameEl.hidden = true; button.hidden = true; form.name.value = r.name || ''; form.name.placeholder = runName(r); form.name.focus(); form.name.select(); };
  const stop = () => { form.hidden = true; nameEl.hidden = false; button.hidden = false; button.focus(); };
  form.name.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); stop(); } });
  form.name.addEventListener('blur', () => setTimeout(() => { if (!form.hidden && !form.contains(document.activeElement)) stop(); }, 150));
  form.onsubmit = async e => {
    e.preventDefault(); const b = form.querySelector('button'); b.disabled = true;
    try { const s = await api.rename(r.id, form.name.value); r.name = s.name; nameEl.textContent = runName(r); stop(); onSaved && onSaved(); }
    catch (e2) { showError(e2, { key: 'rename' }); }
    finally { b.disabled = false; }
  };
}

export async function renderRuns(container) {
  const node = tpl('tpl-runs'); container.append(node); remember(node);
  const list = $('[data-list]', node), search = $('[data-search]', node), filters = $('[data-filters]', node), pickMode = $('[data-pick-mode]', node), pickCount = $('[data-pick-count]', node), openCompare = $('[data-open-compare]', node), foot = $('[data-foot]', node), more = $('[data-more]', node), flatToggle = $('[data-flat-toggle]', node);
  const local = { tree: [], flat: [], filter: 'all', query: '', shown: PAGE, pick: state.labRuns.length > 0 && state.query.get('pick') === '1' };
  pickMode.checked = local.pick;
  flatToggle.href = hrefFor({ view: 'runs', flat: state.flat ? '' : '1' }); flatToggle.textContent = state.flat ? 'Card view' : 'List view';
  for (const [key, label] of FILTERS) filters.append(el('button', { type: 'button', class: key === 'all' ? 'on' : '', dataset: { filter: key }, text: label, onclick: () => { local.filter = key; local.shown = PAGE; for (const b of $$('button', filters)) b.classList.toggle('on', b.dataset.filter === key); draw(); } }));
  search.oninput = () => { local.query = search.value.trim().toLowerCase(); local.shown = PAGE; draw(); };
  pickMode.onchange = () => { local.pick = pickMode.checked; draw(); };
  more.onclick = () => { local.shown += PAGE; draw(); };

  function paintPicks() {
    const n = state.labRuns.length;
    pickCount.hidden = !n; pickCount.textContent = n + ' picked';
    openCompare.hidden = n < 2; openCompare.href = hrefFor({ view: 'compare', runs: state.labRuns, stage: state.labStage });
    for (const box of $$('input[data-pick-id]', list)) box.checked = state.labRuns.includes(box.dataset.pickId);
  }
  function pickBox(id, holder) {
    const input = holder.querySelector('input'); input.dataset.pickId = id; input.checked = state.labRuns.includes(id);
    input.onchange = () => {
      const next = input.checked ? [...state.labRuns, id] : state.labRuns.filter(x => x !== id);
      if (next.length > 4) { input.checked = false; notice('Compare takes up to four runs at a time.', { kind: 'warn', key: 'compare', fix: 'Untick one run before picking another.' }); return; }
      setLabRuns(next); paintPicks();
    };
  }

  function versionRow(c) {
    const row = tpl('tpl-version-row');
    filesOf(c.id).then(set => { const src = set.has('preview.jpg') ? '/runs/' + c.id + '/preview.jpg' : set.has('original.mp4') ? '/jobs/' + c.id + '/mask/frame?i=0' : ''; if (src) $('[data-thumb]', row).replaceChildren(el('img', { src, alt: '', loading: 'lazy', onerror: e => e.target.remove() })); });
    $('[data-name]', row).textContent = c.name || (c.changed ? c.changed.split(/[;.]/)[0].slice(0, 70) : runLabel(c));
    const st = runStatus(c); setChip($('[data-state]', row), st.key, st.text);
    $('[data-facts]', row).textContent = [spent(c.cost_usd_total) !== '$0.00' ? spent(c.cost_usd_total) : 'free', ago(c.created), ...(c.imported || []).map(s => 'own ' + s + ' file')].filter(Boolean).join(' · ');
    const open = $('[data-open]', row); open.href = runHref(c.id, openStep(c)); open.textContent = openLabel(c);
    $('[data-details]', row).onclick = e => openDetails({ id: c.id, source: e.currentTarget });
    const pick = $('[data-pick]', row); pick.hidden = !local.pick; pickBox(c.id, pick);
    if (c.id === state.jobId) row.classList.add('current');
    return row;
  }

  function card(r) {
    const node = tpl('tpl-run-card'); remember(node);
    const thumb = runThumb(r.id, { state: runStatus(r).text }); const holder = $('[data-thumb]', node);
    thumb.append(...holder.children); holder.replaceWith(thumb);
    const st = runStatus(r); setChip($('.state', thumb), st.key, st.text);
    const pick = $('[data-pick]', thumb); pick.hidden = !local.pick; pickBox(r.id, pick);
    const nameEl = $('[data-name]', node); nameEl.textContent = runName(r);
    renameWidget(nameEl, $('[data-rename]', node), $('[data-rename-form]', node), r);
    $('[data-summary]', node).textContent = summaryLine(r);
    const msg = $('[data-msg]', node);
    if (st.key === 'failed') { msg.hidden = false; msg.replaceChildren(el('span', { text: (r.status || 'Preparation failed.') + (r.fix ? ' ' + r.fix : '') })); }
    const facts = $('[data-facts]', node);
    facts.replaceChildren(el('span', {}, el('b', { text: spent(r.cost_usd_total) }), ' spent'), el('span', { text: (r.preset ? r.preset + ' · ' : '') + runLabel({ mode: r.mode }) }), el('span', { text: ago(r.created), title: when(r.created) }), ...(r.imported || []).map(s => el('span', { class: 'chip imported', text: 'own ' + s + ' file' })));
    const open = $('[data-open]', node); open.href = runHref(r.id, openStep(r)); open.textContent = openLabel(r);
    $('[data-details]', node).onclick = e => openDetails({ id: r.id, source: e.currentTarget });
    const versions = $('[data-versions]', node), kids = r.children || [];
    if (kids.length) {
      versions.hidden = false; versions.querySelector('summary').replaceChildren(`${countAll(kids)} version${countAll(kids) === 1 ? '' : 's'} of this run`, el('span', { class: 'hint', text: 'level 2' }));
      const body = $('[data-versions-body]', versions); const walk = (nodes, depth) => { for (const c of nodes) { const row = versionRow(c); row.style.marginLeft = (depth * 16) + 'px'; body.append(row); walk(c.children || [], depth + 1); } };
      walk(kids, 0);
    }
    if (r.id === state.jobId || kids.some(c => c.id === state.jobId)) node.classList.add('current');
    return node;
  }
  const countAll = nodes => nodes.reduce((n, c) => n + 1 + countAll(c.children || []), 0);

  function draw() {
    list.replaceChildren();
    if (state.flat) {
      const rows = local.flat.filter(r => matches(r, local.query) && (local.filter === 'all' || statusKey(r) === local.filter));
      list.className = 'flat-list';
      for (const r of rows.slice(0, local.shown)) {
        const st = runStatus(r);
        list.append(el('div', { class: 'flat-row' + (r.id === state.jobId ? ' current' : '') },
          el('span', { class: 'name' }, el('a', { href: runHref(r.id, openStep(r)), 'data-nav': true, text: runName(r) }), el('span', { class: 'chip ' + st.key, text: st.text })),
          el('span', { class: 'row' }, el('span', { class: 'hint', text: ago(r.created) }), el('button', { type: 'button', class: 'ghost sm', text: 'Details', onclick: e => openDetails({ id: r.id, source: e.currentTarget }) })),
          el('span', { class: 'detail', text: (r.preset ? r.preset + ' · ' : '') + runLabel({ mode: r.mode }) + ' · ' + spent(r.cost_usd_total) + (r.changed ? ' · ' + r.changed : '') })));
      }
      if (!rows.length) list.append(empty());
      foot.hidden = rows.length <= local.shown; return;
    }
    list.className = 'grid';
    const roots = local.tree.filter(r => matches(r, local.query) && (local.filter === 'all' || familyKeys(r).has(local.filter)));
    for (const r of roots.slice(0, local.shown)) list.append(card(r));
    if (!roots.length) list.append(empty());
    foot.hidden = roots.length <= local.shown;
    paintPicks();
    for (const [key] of FILTERS) { const b = filters.querySelector(`[data-filter="${key}"]`); const n = key === 'all' ? local.tree.length : local.tree.filter(r => familyKeys(r).has(key)).length; b.textContent = FILTERS.find(f => f[0] === key)[1] + (n ? ' · ' + n : ''); b.hidden = key !== 'all' && !n; }
  }
  function empty() {
    if (!local.tree.length && !local.flat.length && !local.query) return el('div', { class: 'empty', style: 'grid-column:1/-1' }, el('div', { class: 'ill', text: '▶' }), el('h3', { text: 'No runs yet.' }), el('p', { text: 'Start with a clip of someone talking, five to thirty seconds. The free Talking head preset runs on this computer and needs no account.' }), el('a', { class: 'btn primary', href: hrefFor({ view: 'new' }), 'data-nav': true, text: 'New run' }));
    return el('div', { class: 'empty sm', style: 'grid-column:1/-1', text: local.query ? 'No run matches “' + local.query + '”.' : 'No run in this state.' });
  }

  list.replaceChildren(...Array.from({ length: 6 }, () => el('div', { class: 'skel-card' }, el('i', { class: 'pic' }), el('div', { class: 'skel' }, el('i', { style: 'width:60%' }), el('i', { style: 'width:90%' }), el('i', { style: 'width:40%' })))));
  try {
    if (state.flat) local.flat = (await api.jobs()).runs; else local.tree = (await api.tree()).runs;
    draw();
  } catch (e) { list.replaceChildren(el('div', { class: 'line error', style: 'grid-column:1/-1', text: 'The runs could not be listed. ' + plain(e).fix })); showError(e, { key: 'runs', actions: [{ label: 'Try again', run: async () => navigate({ view: 'runs' }, { replace: true }) }] }); }
}

export { usd, shortId };
