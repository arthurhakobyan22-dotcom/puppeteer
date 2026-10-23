// The edit layer client: pending manual edits of the run in the URL, kept by the server outside the run folder
// (runs/_sessions/<id>/), one shared undo/redo stack across tracks, and "Save edits" = exactly one new branch run.
//
//   import { edits } from './editlayer.js';
//   edits.load(jobId)              GET; the editor calls it on mount and on job change
//   edits.layer                    current layer {mask, mesh, words} (treat as read-only)
//   edits.commit(label, track, fn) fn(draft) mutates a structuredClone of layer[track] (or returns a new value, e.g.
//                                  for a null track); optimistic, PUT {rev, label, track, value}; rolls back + notice on error
//   edits.undo(); edits.redo()     POST; the editor wires Cmd/Ctrl+Z, Shift+Cmd/Ctrl+Z and Ctrl+Y
//   edits.discard()                DELETE (the Save bar asks first)
//   edits.save({confirm})          POST save → navigate to the child; 400 from a track's check → notice with that
//                                  track's actions (edits.saveActions[track] = (problem) => [{label, run}]); 402 → "Run anyway · about $x";
//                                  edits.saveChecks[track] = () => null | {message, fix} answers a known refusal in the page first
//   edits.on('change', fn)         after every load / commit / undo / redo / discard; returns an unsubscribe function
//   edits.pending                  {mask, mesh, words, total}; edits.summary: plain lines; edits.canUndo/canRedo, undoLabel/redoLabel, stale
import { getJSON, send, plain } from './api.js';
import { notice, showError, usd } from './ui.js';
import { state, navigate } from './state.js';

const EMPTY = () => ({ mask: {}, mesh: {}, words: null });
const listeners = { change: new Set() };
const clone = v => (v === undefined ? undefined : typeof structuredClone === 'function' ? structuredClone(v) : JSON.parse(JSON.stringify(v)));

function emit(event) { for (const fn of [...(listeners[event] || [])]) { try { fn(edits); } catch (e) { showError(e, { key: 'edits-listener' }); } } }

function adopt(body) {
  if (!body || typeof body !== 'object') return;
  edits.rev = body.rev || 0; edits.layer = { ...EMPTY(), ...(body.layer || {}) };
  edits.pending = body.pending || { total: 0 }; edits.summary = body.summary || [];
  edits.canUndo = !!body.can_undo; edits.canRedo = !!body.can_redo; edits.undoLabel = body.undo_label || ''; edits.redoLabel = body.redo_label || '';
  edits.stale = !!body.stale; edits.loaded = true;
}

const base = () => '/jobs/' + edits.jobId + '/edits';

export const edits = {
  jobId: null, rev: 0, layer: EMPTY(), pending: { total: 0 }, summary: [], canUndo: false, canRedo: false, undoLabel: '', redoLabel: '', stale: false,
  loaded: false, busy: false, generation: 0, queue: Promise.resolve(),
  saveActions: {},   // track -> (problem {message, fix, body}) => [{label, run}] shown when that track's check() refuses a save
  saveChecks: {},    // track -> () => null | {message, fix}: the same refusal answered in the page first (no 400 round trip; the server still checks)

  on(event, fn) { (listeners[event] = listeners[event] || new Set()).add(fn); return () => listeners[event].delete(fn); },

  async load(jobId = edits.jobId) {
    if (jobId !== edits.jobId) { Object.assign(edits, { jobId, rev: 0, layer: EMPTY(), pending: { total: 0 }, summary: [], canUndo: false, canRedo: false, stale: false, loaded: false }); edits.generation++; edits.queue = Promise.resolve(); }
    if (!jobId) return edits;
    const mine = edits.generation;
    try { const body = await getJSON(base()); if (mine === edits.generation && jobId === edits.jobId) adopt(body); }
    catch (e) { if (jobId === edits.jobId) showError(e, { key: 'edits' }); }
    emit('change');
    return edits;
  },

  commit(label, track, fn) {
    if (!edits.jobId) return Promise.resolve(edits);
    const generation = edits.generation, before = clone(edits.layer);
    const draft = clone(edits.layer[track]);
    let value;
    try { const returned = fn(draft); value = returned === undefined ? draft : returned; }
    catch (e) { showError(e, { key: 'edits' }); return Promise.resolve(edits); }
    edits.layer = { ...edits.layer, [track]: value };   // optimistic: tracks redraw at once
    emit('change');
    const job = edits.jobId;
    edits.queue = edits.queue.then(async () => {
      if (generation !== edits.generation || job !== edits.jobId) return;   // an earlier commit failed or the job changed: dropped
      try { adopt(await send(base(), { rev: edits.rev, label, track, value }, { method: 'PUT' })); }
      catch (e) {
        edits.generation++;   // drop the commits queued after this one; they were built on the failed state
        const p = plain(e);
        edits.layer = before;
        notice(p.status === 409 ? 'Your edits changed in another tab or window, so this edit was not kept.' : 'This edit could not be kept: ' + p.message, { fix: p.status === 409 ? 'The latest edits were reloaded; make the change again.' : p.fix, key: 'edits' });
        await edits.load(job);
        return;
      }
      emit('change');
    });
    return edits.queue.then(() => edits);
  },

  async step(direction) {
    await edits.queue;
    if (!edits.jobId || (direction === 'undo' ? !edits.canUndo : !edits.canRedo)) return edits;
    try { adopt(await send(base() + '/' + direction, { rev: edits.rev })); }
    catch (e) { const p = plain(e); showError(e, { key: 'edits' }); if (p.status === 409) await edits.load(); return edits; }
    emit('change');
    return edits;
  },
  undo() { return edits.step('undo'); },
  redo() { return edits.step('redo'); },

  async discard() {
    await edits.queue;
    try { adopt(await send(base(), undefined, { method: 'DELETE' })); edits.generation++; }
    catch (e) { showError(e, { key: 'edits' }); }
    emit('change');
    return edits;
  },

  async save({ confirm = false } = {}) {
    await edits.queue;
    if (!edits.jobId || edits.busy) return null;
    for (const [track, check] of Object.entries(edits.saveChecks)) {
      let problem = null; try { problem = check(); } catch { problem = null; }
      if (problem) { const p = { ...problem, status: 400, body: { track } }; notice(p.message, { fix: p.fix, key: 'edits', actions: edits.saveActions[track] ? edits.saveActions[track](p) : [] }); return null; }
    }
    edits.busy = true; emit('change');
    try {
      const r = await send(base() + '/save', confirm ? { confirm_cost: 'true' } : {});
      edits.busy = false;
      navigate({ job: r.id, view: state.view === 'studio' ? 'studio' : 'quick' });   // render() clears the notices, so the note comes after
      notice('Your edits were saved as a new version (this one). The run you edited stays as it was; review this version before creating a draft.', { kind: 'ok', key: 'edits' });
      return r;
    } catch (e) {
      edits.busy = false; emit('change');
      const p = plain(e);
      const track = p.body && p.body.track;
      const actions = p.status === 402 ? [{ label: 'Run anyway · ' + usd(p.body.estimated_cost_usd), run: () => edits.save({ confirm: true }) }]
        : track && edits.saveActions[track] ? edits.saveActions[track](p) : [];
      showError(e, { key: 'edits', actions });
      return null;
    }
  },
};
