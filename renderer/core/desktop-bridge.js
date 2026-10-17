// `window.desktop` bridge — Tauri edition (Phase 46 migration).
//
// In the Electron shell, electron/preload.js exposed `window.desktop` via
// contextBridge (18 members). The Tauri shell serves this file instead:
// it implements the IDENTICAL API surface on top of the Tauri global
// (window.__TAURI__, injected via withGlobalTauri), so the renderer code
// is completely untouched. Skipped when a preload already provided the API.
(function () {
  if (window.desktop || !window.__TAURI__) return;
  var inv = window.__TAURI__.core.invoke;
  var listen = window.__TAURI__.event.listen;
  window.desktop = {
    // config
    getConfig: function () { return inv('config_get'); },
    updateConfig: function (patch) { return inv('config_update', { patch: patch }); },
    // window
    moveWindowBy: function (dx, dy) { return inv('window_move_by', { dx: dx, dy: dy }); },
    setIgnoreMouse: function (ignore) { return inv('window_set_ignore_mouse', { ignore: !!ignore }); },
    applyWindowPos: function (x, y) { return inv('window_apply_pos', { x: x, y: y }); },
    getWindowInfo: function () { return inv('window_info'); },
    showWindow: function () { return inv('window_show'); },
    // screen awareness (P38)
    captureScreen: function () { return inv('screen_capture'); },
    // lifecycle
    setHeartMode: function (showHeart) { return inv('set_heart_mode', { showHeart: showHeart }); },
    setLaunchAtStartup: function (enabled) { return inv('set_launch_at_startup', { enabled: enabled }); },
    quitApp: function () { return inv('quit_app'); },
    openDevTools: function () { return inv('open_devtools'); },
    // events from the shell (payload shapes identical to Electron's)
    onGlobalMouse: function (cb) { listen('global-mouse', function (e) { cb(e.payload); }); },
    onShortcutToggle: function (cb) { listen('shortcut-toggle', function (e) { cb(e.payload); }); },
    onAwaken: function (cb) { listen('app:awaken', function () { cb(); }); },
    onTrayAction: function (cb) { listen('tray:action', function (e) { cb(e.payload); }); },
    // heart window side (heart.html)
    summon: function () { return inv('heart_summon'); },
    setHeartHover: function (hovering) { return inv('heart_set_hover', { hovering: hovering }); },
  };
  // Electron opened target=_blank links in the default browser; hook
  // window.open onto the same behavior in Tauri
  var rawOpen = window.open ? window.open.bind(window) : null;
  window.open = function (url, name, features) {
    if (url && /^https?:\/\//i.test(String(url))) {
      inv('open_external', { url: String(url) }).catch(function () {});
      return null;
    }
    return rawOpen ? rawOpen(url, name, features) : null;
  };
})();
