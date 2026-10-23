// The editor's tracks, one line each. Agents 2–4 swap their placeholder for the real track with a one-line change
// (registerTrack replaces a track with the same id, so the later import wins either way).
import { registerTrack } from './timeline.js';
import { facePlaceholder, wordsPlaceholder } from './track-placeholders.js';

import './track-mask.js';          // Agent 2: the mask track (batch wand, ticks, Tint, Grab hands); maskPlaceholder stays exported in track-placeholders.js
registerTrack(facePlaceholder);    // Agent 3: replace this line with  import './track-face.js';
registerTrack(wordsPlaceholder);   // Agent 4: replace this line with  import './track-words.js';
