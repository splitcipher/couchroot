/* Injected by the loopback preview server, before the shipped app scripts. */
(function () {
  'use strict';
  var url = new URL(location.href);
  var name = url.searchParams.get('scenario') || 'home';
  if (!Object.prototype.hasOwnProperty.call(HubScenarios, name)) name = 'home';
  var scenario = HubScenarios[name], apps = HubFixtures.catalog(scenario.catalog);
  if (scenario.missingArtwork) apps[apps.length - 1].iconPath = '/missing-preview-icon.png';
  var marker = 'hub-preview.scenario';
  if (localStorage.getItem(marker) !== name || url.searchParams.has('reset')) {
    Object.keys(localStorage).filter(function (key) {
      return key.indexOf('minimal-hub.') === 0 || key.indexOf('hub-preview.') === 0;
    }).forEach(function (key) { localStorage.removeItem(key); });
    var favorites = scenario.favorites === 'all' ? apps : scenario.favorites === 'none' ? [] :
      scenario.favorites === 'fallback' ? apps.slice(-1) : apps.slice(0, 2);
    localStorage.setItem('minimal-hub.shortcuts.v1', JSON.stringify({ version: 1, apps: favorites }));
    localStorage.setItem('minimal-hub.sound.v1', 'off');
    Object.keys(scenario.prefs || {}).forEach(function (key) { localStorage.setItem(key, scenario.prefs[key]); });
    localStorage.setItem(marker, name);
  }
  url.searchParams.delete('reset');
  history.replaceState(null, '', url);
  // The first saved shortcut stays on Home while its app leaves the simulated TV.
  HubFixtures.install(Object.assign({ launchHandoff: true }, scenario, { apps: scenario.unavailable ? apps.slice(1) : apps }));
  window.addEventListener('hub-preview-launch', function (event) {
    if (parent !== window) parent.postMessage({ type: 'hub-preview-launch', id: event.detail, failed: window.launchFail }, location.origin);
  });
  document.addEventListener('DOMContentLoaded', function () {
    var badge = document.getElementById('preview');
    badge.hidden = false;
    badge.textContent = 'LOCAL PREVIEW · SIMULATED TV';
    function click(id) { document.getElementById(id).click(); }
    if (scenario.screen === 'picker') {
      click('edit-apps'); document.querySelector('#editor-actions button').click();
    } else if (/^(edit|options|move|undo)$/.test(scenario.screen)) {
      click('edit-apps');
      var rows = document.querySelectorAll('#editor-list button');
      if (scenario.screen === 'edit') rows[1].focus(); else rows[1].click();
      if (scenario.screen === 'move') document.querySelector('#editor-list button').click();
      if (scenario.screen === 'undo') {
        document.querySelectorAll('#editor-list button')[1].click();
        document.querySelectorAll('#editor-actions button')[1].click();
      }
    } else if (scenario.screen === 'opening') {
      document.querySelector('#favorites button').click();
    } else if (scenario.screen) {
      click('settings');
      if (scenario.screen === 'reset') click('setting-reset');
      if (scenario.screen === 'monitoring') click('setting-telemetry');
      if (scenario.screen === 'start') document.getElementById('setting-start').focus();
      if (scenario.screen === 'hold') document.getElementById('setting-hold').focus();
    }
    if (scenario.launchFail) document.querySelector('#favorites button').click();
    // Preview-only polling also notices new assets. Failed polls leave the UI usable.
    if (!url.searchParams.has('static')) {
      var revision;
      setInterval(function () {
        fetch('/__preview/version').then(function (response) { return response.text(); }).then(function (next) {
          if (revision !== undefined && next !== revision) location.reload();
          revision = next;
        }).catch(function () {});
      }, 1000);
    }
  });
}());
