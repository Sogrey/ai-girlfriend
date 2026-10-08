'use strict';

const {
  app, BrowserWindow, Tray, Menu, globalShortcut, screen,
  ipcMain, protocol, session, nativeImage, shell,
} = require('electron');
const path = require('path');
const fs = require('fs');
const { pathToFileURL } = require('url');

// Keep the hidden (heart-mode) window fully alive: these flags prevent
// Chromium from backgrounding/occluding the renderer while the window is
// hidden, which otherwise leads to GPU resources (character textures) being
// evicted — the cause of untextured "ghost" frames right after wake-up.
// Must be set before the app is ready.
app.commandLine.appendSwitch('disable-renderer-backgrounding');
app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');
app.commandLine.appendSwitch('disable-background-timer-throttling');

// ---------- paths ----------
const ROOT = path.join(__dirname, '..');
const CONFIG_PATH = path.join(ROOT, 'config', 'config.json');
const USER_CONFIG_PATH = path.join(ROOT, 'config', 'user.json');
const ICON_PATH = path.join(ROOT, 'assets', 'icons', 'girl.png');
const FALLBACK_ICON_PATH = path.join(ROOT, 'assets', 'icons', 'heart.png');

// ---------- single instance lock ----------
// Prevents accidental double-launch (two characters on screen, two tray
// icons). A second launch just wakes the existing instance and exits.
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  console.log('[main] another instance is running - exiting');
  app.quit();
} else {
  // Someone tried to launch the app again — wake the existing one instead.
  app.on('second-instance', () => { try { setHeartMode(false); } catch {} });
}

// ---------- protocol registration (before app ready) ----------
protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: true } },
]);

let mainWindow = null;
let heartWindow = null;
let tray = null;
let mouseTimer = null;
let configCache = null;
let bootShowTimer = null; // safety net: force-show window if boot stalls

// ---------- config helpers ----------
// tolerant JSON reader: strips UTF-8 BOM (PowerShell writes add one and
// JSON.parse barfs on it, silently killing the whole base config)
function readJsonSafe(p) {
  try {
    let s = fs.readFileSync(p, 'utf8');
    if (s.charCodeAt(0) === 0xFEFF) s = s.slice(1); // BOM
    return JSON.parse(s);
  } catch { return {}; }
}

function loadConfig() {
  const base = readJsonSafe(CONFIG_PATH);
  const user = readJsonSafe(USER_CONFIG_PATH);
  const merged = deepMerge(structuredClone(base), user);
  configCache = merged;
  return merged;
}

function deepMerge(base, over) {
  for (const k of Object.keys(over || {})) {
    if (over[k] && typeof over[k] === 'object' && !Array.isArray(over[k]) && base[k] && typeof base[k] === 'object') {
      deepMerge(base[k], over[k]);
    } else {
      base[k] = over[k];
    }
  }
  return base;
}

function saveUserConfig(patch) {
  let user = readJsonSafe(USER_CONFIG_PATH);
  deepMerge(user, patch);
  // write WITHOUT BOM (utf8 string, no BOM prefix) so JSON.parse elsewhere stays happy
  fs.writeFileSync(USER_CONFIG_PATH, JSON.stringify(user, null, 2), 'utf8');
  return loadConfig();
}

function ensureIcon() {
  if (fs.existsSync(ICON_PATH)) return; // real app icon from repo
  if (fs.existsSync(FALLBACK_ICON_PATH)) return;
  // Minimal pink heart PNG (16x16) embedded as base64, written once for tray.
  const b64 = 'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAL0lEQVR42u3OOQ0AAAjEsPn5GTsBBa1ZgQZpEhBwVlO/zMzMBnZ3d3f3d4arxwYc3wAAAABJRU5ErkJggg==';
  try {
    fs.mkdirSync(path.dirname(ICON_PATH), { recursive: true });
    fs.writeFileSync(FALLBACK_ICON_PATH, Buffer.from(b64, 'base64'));
  } catch {}
}

// ---------- windows ----------
function getPrimarySize() {
  const d = screen.getPrimaryDisplay();
  return { width: d.bounds.width, height: d.bounds.height };
}

// Clamp a dragged-away full-screen window so a usable slice always stays
// on screen (at least MIN_VISIBLE px wide & tall), then apply.
const MIN_VISIBLE = 300;
function clampWindowPos(x, y, w, h) {
  const d = screen.getPrimaryDisplay().bounds;
  const minX = -(w - MIN_VISIBLE);
  const maxX = d.width - MIN_VISIBLE;
  const minY = -(h - MIN_VISIBLE);
  const maxY = d.height - MIN_VISIBLE;
  return {
    x: Math.round(Math.max(minX, Math.min(maxX, x))),
    y: Math.round(Math.max(minY, Math.min(maxY, y))),
  };
}

// Apply a remembered (or default) window position with clamping.
function applyWindowPos(x, y) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const b = mainWindow.getBounds();
  const pos = clampWindowPos(x, y, b.width, b.height);
  mainWindow.setBounds({ x: pos.x, y: pos.y, width: b.width, height: b.height });
}

function createMainWindow(cfg) {
  const sz = getPrimarySize();
  // restore the last dragged position (persisted by the renderer), or (0,0).
  // NOTE: we always CREATE the window at (0,0) and reposition afterwards.
  // Windows inflates a full-screen frameless window when it is created at a
  // non-zero position (observed: width = screen.width + x + y), which shifted
  // the avatar's projected geometry; creating at the origin then setBounds()
  // keeps the size exact.
  let initX = 0, initY = 0;
  if (Number.isFinite(cfg.window?.x) && Number.isFinite(cfg.window?.y)) {
    const pos = clampWindowPos(cfg.window.x, cfg.window.y, sz.width, sz.height);
    initX = pos.x; initY = pos.y;
  }
  mainWindow = new BrowserWindow({
    x: 0, y: 0,
    width: sz.width, height: sz.height,
    show: false, // hidden until the renderer reports the model is ready
    transparent: true,
    frame: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    hasShadow: false,
    skipTaskbar: cfg.window.skip_taskbar !== false,
    alwaysOnTop: true,
    backgroundColor: '#00000000',
    icon: path.join(ROOT, 'assets', 'icons', 'girl-256.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });
  // Highest level so she floats above fullscreen games / other topmost apps.
  try { mainWindow.setAlwaysOnTop(true, 'screen-saver'); } catch {}
  // Move to the remembered position now that the window exists with the
  // correct full-screen size (see NOTE above about creation-time inflation).
  if (initX !== 0 || initY !== 0) {
    mainWindow.setBounds({ x: initX, y: initY, width: sz.width, height: sz.height });
  }
  mainWindow.setIgnoreMouseEvents(true, { forward: true });
  // Links in chat bubbles (target=_blank) open in the user's default
  // browser instead of trying to spawn an Electron child window.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.loadURL('app://local/renderer/index.html');
  // forward renderer console to main stdout for debugging
  mainWindow.webContents.on('console-message', (_e, _level, message, line, sourceId) => {
    console.log(`[renderer] ${message}${sourceId ? ` (${sourceId}:${line})` : ''}`);
  });
  // Fallback: if the renderer never reports ready (e.g. model load fails
  // early), still show the window after 15s so error toasts are visible.
  if (bootShowTimer) clearTimeout(bootShowTimer);
  bootShowTimer = setTimeout(() => {
    try { if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) mainWindow.show(); } catch {}
  }, 15000);
  mainWindow.on('closed', () => { mainWindow = null; });
}

function createHeartWindow() {
  const sz = getPrimarySize();
  heartWindow = new BrowserWindow({
    x: sz.width - 140, y: sz.height - 180,
    width: 120, height: 140,
    transparent: true,
    frame: false,
    resizable: false,
    movable: false,
    hasShadow: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    show: false,
    backgroundColor: '#00000000',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true },
  });
  try { heartWindow.setAlwaysOnTop(true, 'screen-saver'); } catch {}
  heartWindow.setIgnoreMouseEvents(false);
  heartWindow.loadURL('app://local/heart/heart.html');
  heartWindow.on('closed', () => { heartWindow = null; });
}

// ---------- mouse polling ----------
function startMousePolling() {
  if (mouseTimer) return;
  mouseTimer = setInterval(() => {
    if (!mainWindow || mainWindow.isDestroyed() || !mainWindow.isVisible()) return;
    const p = screen.getCursorScreenPoint();
    // b = window position on screen. The renderer needs BOTH:
    //  - global x/y: drag deltas (move the window)
    //  - local lx/ly: proximity/hit tests — the character lives in window
    //    coordinates, so after the window is dragged away from (0,0) the
    //    global cursor no longer matches, and "near" silently broke
    //    (toolbar never appeared, character undraggable). That was the bug.
    const b = mainWindow.getBounds();
    mainWindow.webContents.send('global-mouse', {
      x: p.x, y: p.y,
      lx: p.x - b.x, ly: p.y - b.y,
    });
  }, 33);
}
function stopMousePolling() {
  if (mouseTimer) { clearInterval(mouseTimer); mouseTimer = null; }
}

// ---------- leave / return ----------
function setHeartMode(showHeart) {
  if (showHeart) {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.hide();
    if (heartWindow && !heartWindow.isDestroyed()) heartWindow.show();
    stopMousePolling();
  } else {
    if (heartWindow && !heartWindow.isDestroyed()) heartWindow.hide();
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
      startMousePolling();
      // notify renderer to play walk-in animation (no callback loop: renderer must NOT call setHeartMode in response)
      mainWindow.webContents.send('app:awaken');
    }
  }
}

// ---------- tray ----------
function buildTray(cfg) {
  ensureIcon();
  const icon = nativeImage.createFromPath(ICON_PATH);
  const fb = nativeImage.createFromPath(FALLBACK_ICON_PATH);
  const use = !icon.isEmpty() ? icon : (!fb.isEmpty() ? fb : nativeImage.createEmpty());
  tray = new Tray(use);
  tray.setToolTip('AI 女友');

  const costumeSub = [
    { label: '日常装', click: () => sendToMain('tray:action', { action: 'change_costume', costume: 'casual' }) },
    { label: '水手服', click: () => sendToMain('tray:action', { action: 'change_costume', costume: 'school' }) },
    { label: '时尚装', click: () => sendToMain('tray:action', { action: 'change_costume', costume: 'stylish' }) },
    { label: '洋装', click: () => sendToMain('tray:action', { action: 'change_costume', costume: 'gothic' }) },
    { label: '未来科技装', click: () => sendToMain('tray:action', { action: 'change_costume', costume: 'seed' }) },
  ];
  const menu = Menu.buildFromTemplate([
    { label: '唤醒', click: () => setHeartMode(false) },
    { label: '隐藏', click: () => { if (mainWindow && mainWindow.isVisible()) mainWindow.hide(); } },
    { type: 'separator' },
    { label: '位置复位', click: () => { applyWindowPos(0, 0); } },
    { label: '换装', submenu: costumeSub },
    { label: '休息', click: () => sendToMain('tray:action', { action: 'leave' }) },
    { type: 'separator' },
    { label: '设置', click: () => sendToMain('tray:action', { action: 'open_settings' }) },
    { type: 'separator' },
    { label: '退出', click: () => app.quit() },
  ]);
  tray.setContextMenu(menu);
  tray.on('click', () => setHeartMode(false)); // click tray icon also wakes
}

function sendToMain(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, payload);
}

// ---------- shortcut ----------
function registerShortcut(cfg) {
  try {
    globalShortcut.register(cfg.hotkey || 'Control+Alt+G', () => {
      const heartVisible = heartWindow && heartWindow.isVisible();
      const mainVisible = mainWindow && mainWindow.isVisible();
      if (heartVisible || !mainVisible) {
        setHeartMode(false); // bring her back (renderer animates on app:awaken)
      } else {
        // renderer plays leave transition; renderer will call setHeartMode(true) when ready
        sendToMain('shortcut-toggle', { reason: 'leave' });
      }
    });
  } catch {}
}

// ---------- permissions ----------
function setupPermissions() {
  session.defaultSession.setPermissionRequestHandler((wc, perm, cb) => {
    if (perm === 'media') return cb(true);
    cb(false);
  });
  app.commandLine.appendSwitch('enable-features', 'HardwareMediaKeyHandling');
}

// ---------- ipc ----------
function setupIpc() {
  ipcMain.handle('config:get', () => loadConfig());
  ipcMain.handle('config:update', (_e, patch) => saveUserConfig(patch));
  ipcMain.handle('window:info', () => {
    const sz = getPrimarySize();
    const b = mainWindow ? mainWindow.getBounds() : { x: 0, y: 0, width: sz.width, height: sz.height };
    const wa = screen.getPrimaryDisplay().workArea; // excludes the taskbar
    return { bounds: b, screen: sz, workArea: wa };
  });
  // restore / reset the remembered window position
  ipcMain.on('window:applyPos', (_e, x, y) => {
    if (!mainWindow || mainWindow.isDestroyed() || !Number.isFinite(x) || !Number.isFinite(y)) return;
    applyWindowPos(x, y);
  });
  ipcMain.on('window:show', () => {
    // renderer says model + textures are ready → reveal the window
    if (bootShowTimer) { clearTimeout(bootShowTimer); bootShowTimer = null; }
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) mainWindow.show();
  });
  ipcMain.on('window:moveBy', (_e, dx, dy) => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    const b = mainWindow.getBounds();
    // clamp so a runaway drag can never strand the character off-screen
    const pos = clampWindowPos(b.x + dx, b.y + dy, b.width, b.height);
    mainWindow.setBounds({ x: pos.x, y: pos.y, width: b.width, height: b.height });
  });
  ipcMain.on('window:setIgnoreMouse', (_e, ignore) => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.setIgnoreMouseEvents(!!ignore, { forward: true });
  });
  ipcMain.handle('app:setHeartMode', (_e, showHeart) => { setHeartMode(!!showHeart); return true; });
  ipcMain.handle('app:setLaunchAtStartup', (_e, enabled) => {
    app.setLoginItemSettings({ openAtLogin: !!enabled });
    return true;
  });
  ipcMain.on('app:quit', () => app.quit());
  ipcMain.on('dev:openDevTools', () => { if (mainWindow) mainWindow.webContents.openDevTools({ mode: 'detach' }); });
  ipcMain.on('heart:clicked', () => setHeartMode(false));
  ipcMain.on('heart:hover', (_e, hovering) => {
    if (heartWindow && !heartWindow.isDestroyed()) heartWindow.setIgnoreMouseEvents(!hovering);
  });
}

// ---------- app lifecycle ----------
app.whenReady().then(() => {
  if (!gotSingleInstanceLock) return; // second instance: just quitting
  const cfg = loadConfig();
  setupPermissions();
  setupIpc();

  protocol.handle('app', (req) => {
    let rel = decodeURIComponent(new URL(req.url).pathname).replace(/^\/+/, '').replace(/\\/g, '/');
    // allow app://local/<path> (host 'local') and app://<path>
    if (rel === '') rel = 'renderer/index.html';
    console.log('[app-url]', req.method, rel);
    const full = path.join(ROOT, rel);
    if (!full.startsWith(ROOT)) return new Response('Forbidden', { status: 403 });
    const ext = path.extname(full).toLowerCase();
    const mimeMap = {
      '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
      '.css': 'text/css', '.json': 'application/json', '.txt': 'text/plain',
      '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
      '.webp': 'image/webp', '.svg': 'image/svg+xml', '.vrm': 'model/gltf-binary',
      '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.bin': 'application/octet-stream',
      '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ttf': 'font/ttf', '.otf': 'font/otf', '.woff': 'font/woff', '.woff2': 'font/woff2',
      '.ktx2': 'image/ktx2',
    };
    const mime = mimeMap[ext] || 'application/octet-stream';
    try {
      const data = fs.readFileSync(full);
      return new Response(data, { headers: { 'Content-Type': mime, 'Cache-Control': 'no-store, max-age=0' } });
    } catch {
      return new Response('Not Found: ' + rel, { status: 404 });
    }
  });

  createMainWindow(cfg);
  createHeartWindow();
  buildTray(cfg);
  registerShortcut(cfg);

  if (cfg.window.launch_at_startup) app.setLoginItemSettings({ openAtLogin: true });

  startMousePolling();

  // debug screenshot support: AIGF_DEBUG_SHOT=ms or "ms,ms,ms"
  if (process.env.AIGF_DEBUG_SHOT) {
    const times = String(process.env.AIGF_DEBUG_SHOT).split(',').map(s => parseInt(s, 10)).filter(n => !isNaN(n));
    for (const delay of times) {
      setTimeout(async () => {
        try {
          if (!mainWindow || mainWindow.isDestroyed()) return;
          const img = await mainWindow.webContents.capturePage();
          const dir = path.join(ROOT, '.temp');
          fs.mkdirSync(dir, { recursive: true });
          fs.writeFileSync(path.join(dir, `screenshot-${delay}.png`), img.toPNG());
          console.log(`[debug-shot] saved .temp/screenshot-${delay}.png`);
        } catch (e) { console.error('[debug-shot] failed', e); }
      }, delay);
    }
  }
});

app.on('window-all-closed', () => { app.quit(); });
app.on('before-quit', () => { try { globalShortcut.unregisterAll(); } catch {} if (tray) tray.destroy(); });
