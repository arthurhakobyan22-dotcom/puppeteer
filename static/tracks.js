// The editor's tracks, one line each. Agents 2–4 swap their placeholder for the real track with a one-line change
// (registerTrack replaces a track with the same id, so the later import wins either way).
import { registerTrack } from './timeline.js';
import { maskPlaceholder, facePlaceholder, wordsPlaceholder } from './track-placeholders.js';

registerTrack(maskPlaceholder);    // Agent 2: replace this line with  import './track-mask.js';
registerTrack(facePlaceholder);    // Agent 3: replace this line with  import './track-face.js';
registerTrack(wordsPlaceholder);   // Agent 4: replace this line with  import './track-words.js';
