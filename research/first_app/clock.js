/* Original ES5 teaching example. No root, network, storage or Hub preference keys. */
(function (root) {
  'use strict';
  function start(document, platform, timer, now) {
    var twelve = false, paused = false, exited = false;
    var clock = document.getElementById('clock'), status = document.getElementById('status');
    function draw() {
      if (paused || exited) { return; }
      var date = now(), hours = date.getHours(), minutes = date.getMinutes();
      clock.textContent = (twelve ? (hours % 12 || 12) : hours) + ':' + (minutes < 10 ? '0' : '') + minutes + (twelve ? (hours < 12 ? ' AM' : ' PM') : '');
    }
    function key(event) {
      if (exited) { return; }
      var code = event.keyCode;
      if (code === 37 || code === 39) { twelve = !twelve; draw(); }
      else if (code === 13) { paused = !paused; status.textContent = paused ? 'Paused' : 'Running'; draw(); }
      else if (code === 27 || code === 10009) {
        exited = true; timer.clearInterval(interval);
        try {
          if (platform && platform.application) { platform.application.getCurrentApplication().exit(); }
          else { status.textContent = 'Exit requested (browser preview)'; }
        } catch (_) { status.textContent = 'Exit failed; use physical Home'; }
      } else { return; }
      event.preventDefault();
    }
    draw(); var interval = timer.setInterval(draw, 1000);
    document.addEventListener('keydown', key);
    return { stop: function () { exited = true; timer.clearInterval(interval); document.removeEventListener('keydown', key); } };
  }
  if (typeof module !== 'undefined') { module.exports = start; }
  else { start(root.document, root.tizen, root, function () { return new Date(); }); }
}(typeof window !== 'undefined' ? window : this));
