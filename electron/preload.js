'use strict';

const { contextBridge, ipcRenderer } = require('electron');

const listeners = {};

contextBridge.exposeInMainWorld('desktop', {
  // config
  getConfig: () => ipcRenderer.invoke('config:get'),
  updateConfig: (patch) => ipcRenderer.invoke('config:update', patch),
  // window
  moveWindowBy: (dx, dy) => ipcRenderer.send('window:moveBy', dx, dy),
  setIgnoreMouse: (ignore) => ipcRenderer.send('window:setIgnoreMouse', !!ignore),
  getWindowInfo: () => ipcRenderer.invoke('window:info'),
  showWindow: () => ipcRenderer.send('window:show'),
  // lifecycle
  setHeartMode: (showHeart) => ipcRenderer.invoke('app:setHeartMode', showHeart),
  setLaunchAtStartup: (enabled) => ipcRenderer.invoke('app:setLaunchAtStartup', enabled),
  quitApp: () => ipcRenderer.send('app:quit'),
  openDevTools: () => ipcRenderer.send('dev:openDevTools'),
  // events from main
  onGlobalMouse: (cb) => {
    ipcRenderer.on('global-mouse', (_e, pos) => cb(pos));
  },
  onShortcutToggle: (cb) => {
    ipcRenderer.on('shortcut-toggle', (_e, info) => cb(info));
  },
  onAwaken: (cb) => {
    ipcRenderer.on('app:awaken', () => cb());
  },
  onTrayAction: (cb) => {
    ipcRenderer.on('tray:action', (_e, action) => cb(action));
  },
  // heart window side (used by heart.html)
  summon: () => ipcRenderer.send('heart:clicked'),
  setHeartHover: (hovering) => ipcRenderer.send('heart:hover', hovering),
});
