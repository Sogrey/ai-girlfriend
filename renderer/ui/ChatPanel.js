import { bus } from '../core/EventBus.js';

let panelEl, logEl, inputEl, sendEl;
let open = false;

export function initChatPanel({ backend }) {
  panelEl = document.getElementById('chat-panel');
  logEl = document.getElementById('chat-log');
  inputEl = document.getElementById('chat-input');
  sendEl = document.getElementById('chat-send');

  sendEl.addEventListener('click', send);
  inputEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); send(); } });

  bus.on('backend:ai_response', (msg) => addAI(msg.reply, msg.emotion));
  bus.on('backend:stt_result', (msg) => addUser(msg.text, 'voice'));
  bus.on('backend:tts_audio', () => {
    const dots = logEl.querySelector('.typing');
    if (dots) dots.remove();
  });
}

function send() {
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  addUser(text, 'me');
  bus.emit('backend:send_user', { text });
}

export function toggle() {
  open = !open;
  if (open) { panelEl.classList.remove('hidden'); bus.emit('panel:open'); inputEl.focus(); }
  else { panelEl.classList.add('hidden'); bus.emit('panel:close'); }
  return open;
}

export function addUser(text, who = 'me') {
  const el = document.createElement('div');
  el.className = 'chat-msg ' + (who === 'me' ? 'user' : who === 'voice' ? 'user' : 'sys');
  if (who === 'voice') el.style.background = 'rgba(150,180,255,.3)';
  el.textContent = text;
  logEl.appendChild(el);
  scrollDown();
}

export function addAI(text, emotion) {
  const el = document.createElement('div');
  el.className = 'chat-msg ai';
  el.textContent = text;
  if (emotion) el.dataset.emotion = emotion;
  logEl.appendChild(el);
  scrollDown();
}

export function addSys(text) {
  const el = document.createElement('div');
  el.className = 'chat-msg sys';
  el.textContent = text;
  logEl.appendChild(el);
  scrollDown();
}

function scrollDown() {
  requestAnimationFrame(() => { logEl.scrollTop = logEl.scrollHeight; });
}
