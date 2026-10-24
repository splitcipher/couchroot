/* Ordinary signed-app APIs only. No network bridge or privileged process. */
(function (root) {
  'use strict';
  var apps = {
    plex: { name: 'Plex', id: 'kIciSQlYEM.plex' },
    youtube: { name: 'YouTube', id: '9Ur5IzDKqV.TizenYouTube' },
    home: { name: 'Samsung Home', id: 'com.samsung.tv.csfs' }
  };
  function localIcon(path) {
    // Never load remote artwork, even when supplied by an installed app.
    return typeof path === 'string' && (/^file:\/\/\//.test(path) || /^\/(?!\/)/.test(path)) ? path : '';
  }
  function eligible(app) {
    // This TV marks hundreds of internal tools show=true. Store-package IDs
    // identify installable app entries; native consumer apps use explicit IDs.
    var nativeApps = ['org.tizen.netflix-app', 'org.tizen.primevideo', 'org.tizen.browser', 'com.samsung.tv.tvplus'];
    if (!app || typeof app.id !== 'string' ||
        (app.packageId && typeof app.packageId !== 'string')) { return false; }
    var pkg = app.packageId || app.id.split('.')[0];
    return app.show === true && (/^[A-Za-z0-9]{10}$/.test(pkg) || nativeApps.indexOf(app.id) >= 0);
  }
  function create(platform) {
    function launch(app, success, failure) {
      if (!app || typeof app.id !== 'string' || !/^[A-Za-z0-9_.-]{1,256}$/.test(app.id)) { failure(new Error('Unknown app')); return; }
      if (!platform) { success({ preview: true, name: app.name }); return; }
      var settled = false;
      var done = function () { if (!settled) { settled = true; success({ preview: false, name: app.name }); } };
      var failed = function (error) { if (!settled) { settled = true; failure(error); } };
      function ordinaryLaunch() {
        try {
        if (platform.application && typeof platform.application.launch === 'function') {
          platform.application.launch(app.id, done, failed);
        } else if (platform.application && typeof platform.application.launchAppControl === 'function' && platform.ApplicationControl) {
          var control = new platform.ApplicationControl('http://tizen.org/appcontrol/operation/default', null, null, null, null, 'SINGLE');
          platform.application.launchAppControl(control, app.id, done, failed);
        } else { failed(new Error('App launching is unavailable on this TV runtime.')); }
        } catch (error) { failed(error); }
      }
      // Verified on S90D / 2130.0: AMD skips its native spinner for this bundle
      // value. It is a firmware-specific hint, not a documented Tizen guarantee.
      // Samsung Home keeps the original launch path as an independent fallback.
      if (app.id !== apps.home.id && platform.application &&
          typeof platform.application.launchAppControl === 'function' &&
          typeof platform.ApplicationControl === 'function' && typeof platform.ApplicationControlData === 'function') {
        var pending = true;
        function rejected(error) {
          if (!pending) { return; }
          pending = false;
          if (error && ['NotSupportedError', 'InvalidValuesError', 'TypeMismatchError', 'SecurityError'].indexOf(error.name) >= 0) {
            ordinaryLaunch();
          } else { failed(error); }
        }
        try {
          var data = [new platform.ApplicationControlData('__NO_LOADING_LAUNCH', ['enable'])];
          var quietControl = new platform.ApplicationControl('http://tizen.org/appcontrol/operation/default', null, null, null, data, 'SINGLE');
          platform.application.launchAppControl(quietControl, app.id, function () {
            if (pending) { pending = false; done(); }
          }, rejected);
        } catch (error) { rejected(error); }
      } else { ordinaryLaunch(); }
    }
    return {
      preview: !platform,
      launch: function (key, success, failure) { launch(apps[key], success, failure); },
      launchApp: launch,
      discover: function (success, failure) {
        if (!platform) { success([apps.plex, apps.youtube].map(function (a) { return { id: a.id, name: a.name, icon: '' }; })); return; }
        try {
          if (!platform.application || typeof platform.application.getAppsInfo !== 'function') { throw new Error('Installed-app discovery is unavailable.'); }
          platform.application.getAppsInfo(function (list) {
            var seen = Object.create(null);
            var found = list.filter(function (app) {
              if (!app || !eligible(app) || typeof app.name !== 'string' || !app.name || app.id === 'MiniHub001.Hub' || app.id === apps.home.id || seen[app.id]) { return false; }
              seen[app.id] = true; return /^[A-Za-z0-9_.-]{1,256}$/.test(app.id);
            }).map(function (app) { return { id: app.id, name: app.name, icon: localIcon(app.iconPath) }; });
            found.sort(function (a, b) { return a.name.localeCompare(b.name) || a.id.localeCompare(b.id); });
            success(found);
          }, failure);
        } catch (error) { failure(error); }
      }
    };
  }
  root.HubBridge = { create: create, apps: apps, localIcon: localIcon, eligible: eligible };
  if (typeof module !== 'undefined') { module.exports = root.HubBridge; }
}(typeof window !== 'undefined' ? window : globalThis));
