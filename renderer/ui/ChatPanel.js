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

export function addAI(text, emotion, opts = {}) {
  const el = document.createElement('div');
  el.className = 'chat-msg ai md' + (opts.error ? ' error' : '');
  el.innerHTML = renderRich(text); // escaped-then-assembled, XSS-safe
  if (emotion) el.dataset.emotion = emotion;
  logEl.appendChild(el);
  scrollDown();
}

// Minimal Markdown renderer for AI bubbles (safe: plain text is fully HTML-
// escaped FIRST, then a small subset is re-introduced with our own tags only):
// [label](url) and bare http(s) links -> clickable <a target=_blank>
// **bold** -> <strong>, `code` -> <code>, newlines -> <br>
export function renderRich(text) {
  const esc = String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  // link builder: trailing chars that may actually be sentence punctuation
  // ('?' '!' '.' ',' etc.) are kept OUTSIDE the anchor
  const link = (rawUrl) => {
    const core = rawUrl.replace(/[?!,.;:'"'）』」…]+$/, '');
    const tail = rawUrl.slice(core.length);
    return `<a href="${core}" target="_blank" rel="noopener noreferrer">${core}</a>${tail}`;
  };
  let html = esc
    // markdown links [label](url)
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
      (_m, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`)
    // bare urls (not already inside href="..." / after a generated tag '>').
    // INSIDE the url: bare '&' is excluded so esc'd text like &quot; never
    // bleeds in, but the sequence &amp; (an escaped query-string &) is kept.
    // '?' allowed (query strings); tail punctuation trimmed by link().
    .replace(/(^|[^"'=&>\w])(https?:\/\/(?:(?:&amp;)|[^<>"&'。，、；：！？「」『』（）)\]}!~,;'"…\u2026\s])+)/g,
      (_m, pre, url) => pre + link(url));
  html = html
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>');
  return html;
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
