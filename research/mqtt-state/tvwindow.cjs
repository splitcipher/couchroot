'use strict';
// Original Couchroot code. SPDX-License-Identifier: 0BSD
// OFFLINE MODEL ONLY. Not imported/packaged by the agent. A selected MAIN window
// can be hidden by another app: these values cannot establish visible TV state.
const {sourceId} = require('../../agent/service/mqtt-state');
function mainWindow(api) {
  try {
    const source=api.getSource('MAIN');
    const input=sourceId(source);
    if (!input || source.signal !== true) return null;
    const r=api.getVideoResolution('MAIN');
    if (!r || !Number.isInteger(r.width) || r.width < 1 || r.width > 16384 ||
        !Number.isInteger(r.height) || r.height < 1 || r.height > 16384 ||
        !Number.isInteger(r.frequency) || r.frequency < 1 || r.frequency > 1000) return null;
    return {input,resolution:r.width+'x'+r.height,refresh_hz:r.frequency};
  } catch (_) { return null; }
}
module.exports={mainWindow};
