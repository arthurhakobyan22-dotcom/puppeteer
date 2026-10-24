// The editor's lanes, one line each (registerTrack replaces a lane with the same id, so the last import wins).
import './track-mask.js';    // the Mask lane: fixes, apply, flagged frames, Find hands, the Mask and Overlay views
import './track-face.js';    // the Face lane: hide the mesh, move / resize / turn, expressions
import './track-words.js';   // the Words lane: transcribe, word blocks, split / merge / add / delete
