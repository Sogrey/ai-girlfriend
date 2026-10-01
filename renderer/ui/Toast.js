import { bus } from '../core/EventBus.js';

let container;
let idc = 0;

export function initToast() {
  container = document.getElementById('toast-container');
  bus.on('toast:show', ({ text, kind = 'info', ms = 3500 }) => show(text, kind, ms));
}

export function show(text, kind = 'info', ms = 3500) {
  if (!container) container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = 'toast ' + (kind === 'ok' ? 'ok' : kind === 'error' ? 'error' : kind === 'warn' ? 'warn' : '');
  el.textContent = text;
  el.id = 'toast-' + (idc++);
  container.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .4s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 400);
  }, ms);
}
