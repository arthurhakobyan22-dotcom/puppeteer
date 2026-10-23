// Runs page: the branch tree (parent → children, newest roots first) with state, date, what changed and spend;
// a "flat list" toggle keeps the old newest-first list.
import { api } from './api.js';
import { $, el, spent, when, runLabel, modeLabel, setChip, showError, tpl, shortId } from './ui.js';
import { state, setLabRuns, hrefFor, navigate } from './state.js';

function suffix(r) { return r.final ? ' · final ready' : r.draft ? ' · draft ready' : r.request ? ' · draft submitted' : r.reviewed ? ' · reviewed' : ''; }

export async function renderRuns(container) {
  const node = tpl('tpl-runs'); container.append(node);
  const list = $('[data-list]', node), flat = $('[data-flat]', node), title = $('[data-title]', node), openLab = $('[data-open-lab]', node);
  flat.checked = state.query.get('flat') === '1';
  flat.onchange = () => { history.replaceState(null, '', hrefFor({ view: 'runs', flat: flat.checked ? '1' : '' })); draw(); };
  function labButton() {
    openLab.hidden = state.labRuns.length < 2; openLab.textContent = 'Open Lab (' + state.labRuns.length + ')';
    openLab.href = hrefFor({ view: 'lab', runs: state.labRuns, stage: state.labStage }); openLab.setAttribute('data-nav', '');
  }
  labButton();

  function row(r, depth) {
    const node = tpl('tpl-run-row');
    if (r.id === state.jobId) node.classList.add('current');
    node.style.paddingLeft = (12 + depth * 18) + 'px';
    const branch = $('[data-branch]', node); branch.hidden = !depth;
    const link = $('[data-title]', node); link.textContent = runLabel(r) + suffix(r); link.href = hrefFor({ job: r.id, view: 'quick' });
    setChip($('[data-state]', node), r.state);
    $('[data-when]', node).textContent = when(r.created);
    $('[data-changed]', node).textContent = depth || r.changed ? 'What changed: ' + (r.changed || 'nothing recorded') : (r.status || '') + ' · ' + shortId(r.id) + '…';
    $('[data-spent]', node).textContent = 'Spent ' + spent(r.cost_usd_total);
    $('[data-studio]', node).href = hrefFor({ job: r.id, view: 'studio' });
    $('[data-quick]', node).href = hrefFor({ job: r.id, view: 'quick' });
    const lab = $('[data-lab]', node);
    const paint = () => { lab.textContent = state.labRuns.includes(r.id) ? 'In Lab ✓' : 'Add to Lab'; };
    paint();
    lab.onclick = () => { setLabRuns(state.labRuns.includes(r.id) ? state.labRuns.filter(x => x !== r.id) : [...state.labRuns, r.id]); paint(); labButton(); };
    return node;
  }

  async function draw() {
    list.replaceChildren(el('div', { class: 'hint', text: 'Loading…' }));
    try {
      if (flat.checked) {
        const j = await api.jobs(); list.replaceChildren(); title.textContent = 'Runs · ' + j.runs.length;
        for (const r of j.runs) {
          const a = el('a', { class: 'flat' + (r.id === state.jobId ? ' current' : ''), href: hrefFor({ job: r.id, view: 'quick' }), 'data-nav': true },
            el('span', { text: modeLabel(r.mode) + suffix(r) }), el('span', { class: 'when', text: when(r.created) }), el('span', { class: 'detail', text: r.status }), el('span', { class: 'detail mono', text: r.id }));
          list.append(a);
        }
        if (!j.runs.length) list.append(el('div', { class: 'empty', text: 'No runs yet.' }));
      } else {
        const j = await api.tree(); list.replaceChildren();
        let total = 0; const walk = (nodes, depth) => { for (const r of nodes) { total++; list.append(row(r, depth)); walk(r.children || [], depth + 1); } };
        walk(j.runs, 0); title.textContent = 'Runs · ' + total;
        if (!total) list.append(el('div', { class: 'empty', text: 'No runs yet. Prepare a video in Quick first.' }));
      }
    } catch (e) { list.replaceChildren(); showError(e, { key: 'runs' }); }
  }
  draw();
}
