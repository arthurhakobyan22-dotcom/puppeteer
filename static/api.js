// HTTP layer. Every failure becomes an ApiError with a plain sentence and a fix; nothing raw reaches the screen.
// GET requests retry silently (up to 3 times, backoff) on network glitches and 5xx; POST requests never retry.

export class ApiError extends Error {
  constructor(message, fix = '', status = 0, body = {}) {
    super(message); this.name = 'ApiError'; this.fix = fix; this.status = status; this.body = body || {};
  }
}

export const NETWORK_MESSAGE = 'The app could not be reached. Is it still running? Restart it and reload.';
export const NETWORK_FIX = 'Start the app again from its folder (bash start.command), then reload this page.';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function readBody(response) {
  const text = await response.text();
  if (!text) return null;
  try { return JSON.parse(text); } catch { return { raw: text }; }
}

export function errorFromResponse(response, body) {
  const b = body && typeof body === 'object' ? body : {};
  let message = typeof b.message === 'string' ? b.message : typeof b.detail === 'string' ? b.detail : '';
  if (!message) {
    if (response.status === 404) message = 'That run or file was not found.';
    else if (response.status === 422 || Array.isArray(b.detail)) message = 'The app did not understand this request.';
    else if (response.status >= 500) message = 'The app hit an internal problem while handling this request.';
    else message = 'The request could not be completed.';
  }
  let fix = typeof b.fix === 'string' ? b.fix : '';
  if (!fix) {
    if (response.status === 404) fix = 'Open the Runs page and choose an existing run.';
    else if (response.status >= 500) fix = "Check the run's log.txt for the reason, then try again.";
    else if (response.status === 422) fix = 'Reload the page and try again.';
    else if (response.status === 409) fix = 'Reload the page to see the latest state, then try again.';
    else fix = 'Check the details above and try again.';
  }
  return new ApiError(message, fix, response.status, b);
}

/** {message, fix, status, body} for anything that was thrown. Never a raw object, array or traceback. */
export function plain(error) {
  if (error instanceof ApiError) return { message: error.message, fix: error.fix, status: error.status, body: error.body };
  if (error && error.name === 'AbortError') return { message: 'The request was cancelled.', fix: '', status: 0, body: {} };
  const text = error && typeof error.message === 'string' ? error.message : '';
  if (/failed to fetch|networkerror|network request failed|load failed/i.test(text)) return { message: NETWORK_MESSAGE, fix: NETWORK_FIX, status: 0, body: {} };
  const message = text && !/^(type|reference|syntax)?error:/i.test(text) && text.length < 300 ? text : 'Something went wrong in the page.';
  return { message, fix: 'Reload the page. If it happens again, check the app log.', status: 0, body: {} };
}

/** GET JSON with silent retries for glitches (network failures and 5xx); 4xx answers are returned as errors at once. */
export async function getJSON(url, { retries = 3, signal } = {}) {
  let delay = 400;
  for (let attempt = 0; ; attempt++) {
    let response;
    try { response = await fetch(url, { cache: 'no-store', signal }); }
    catch (e) {
      if (e && e.name === 'AbortError') throw e;
      if (attempt < retries) { await sleep(delay); delay *= 2; continue; }
      throw new ApiError(NETWORK_MESSAGE, NETWORK_FIX, 0);
    }
    if (response.status >= 500 && attempt < retries) { await sleep(delay); delay *= 2; continue; }
    const body = await readBody(response);
    if (!response.ok) throw errorFromResponse(response, body);
    return body;
  }
}

/** POST (never retried: a paid request must never be sent twice by accident). `body` is FormData or a JSON object. */
export async function send(url, body, { method = 'POST' } = {}) {
  const init = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) { init.headers = { 'content-type': 'application/json' }; init.body = JSON.stringify(body); }
  let response;
  try { response = await fetch(url, init); }
  catch { throw new ApiError(NETWORK_MESSAGE, NETWORK_FIX, 0); }
  const data = await readBody(response);
  if (!response.ok) throw errorFromResponse(response, data);
  return data;
}

export const api = {
  stages: () => getJSON('/stages'),
  presets: () => getJSON('/presets'),
  providers: () => getJSON('/providers'),
  costs: () => getJSON('/costs'),
  jobs: () => getJSON('/jobs'),
  tree: () => getJSON('/jobs/tree'),
  job: id => getJSON('/jobs/' + id),
  run: id => getJSON('/jobs/' + id + '/run'),
  files: id => getJSON('/jobs/' + id + '/files'),
  review: id => getJSON('/jobs/' + id + '/mask-review'),
  hd: id => getJSON('/jobs/' + id + '/hd'),
  runFile: (id, name) => getJSON('/runs/' + id + '/' + name),
  estimatePrep: data => send('/estimate', data),
  estimateBranch: (id, data) => send('/jobs/' + id + '/estimate', data),
  branch: (id, data) => send('/jobs/' + id + '/branch', data),
  savePreset: data => send('/presets', data),
  picks: () => getJSON('/compare/picks'),
  pick: data => send('/compare/picks', data),
  create: form => send('/jobs', form),
  seedance: (id, form) => send('/jobs/' + id + '/seedance', form),
  finish: (id, form) => send('/jobs/' + id + '/finish', form),
  hdStart: (id, form) => send('/jobs/' + id + '/hd', form),
  saveReview: (id, form) => send('/jobs/' + id + '/mask-review', form),
  rename: (id, name) => send('/jobs/' + id + '/name', { name }, { method: 'PUT' }),
  calls: id => getJSON('/jobs/' + id + '/calls'),
};
