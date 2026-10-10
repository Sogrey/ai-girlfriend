import { bus } from '../core/EventBus.js';

let panelEl, logEl, inputEl, sendEl;
let open = false;

// ---- bubble text copy: right-click mini menu ----
// Selection itself is re-enabled via CSS on .chat-msg (the global
// user-select:none at the top of main.css is a desktop-pet default that
// prevents accidental selection while dragging her around).
let ctxEl = null;

function hideCtx() {
  if (ctxEl) { ctxEl.remove(); ctxEl = null; }
  document.removeEventListener('pointerdown', onDocPointer, true);
}

function onDocPointer(e) {
  if (ctxEl && !ctxEl.contains(e.target)) hideCtx();
}

function copyText(text) {
  const done = () => bus.emit('toast:show', { text: '已复制', kind: 'ok', ms: 1500 });
  const fail = () => bus.emit('toast:show', { text: '复制失败', kind: 'error', ms: 2000 });
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => { fallbackCopy(text) ? done() : fail(); });
  } else {
    fallbackCopy(text) ? done() : fail();
  }
}

function fallbackCopy(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch { return false; }
}

function showCtx(e, msgEl) {
  hideCtx();
  const sel = window.getSelection();
  const hasSel = sel && !sel.isCollapsed && msgEl.contains(sel.anchorNode);
  ctxEl = document.createElement('div');
  ctxEl.className = 'chat-ctx-menu';
  const addBtn = (label, fn) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(); hideCtx(); });
    ctxEl.appendChild(b);
  };
  if (hasSel) addBtn('复制选中文字', () => copyText(sel.toString()));
  addBtn('复制本条', () => copyText(msgEl.innerText));
  document.body.appendChild(ctxEl);
  const r = ctxEl.getBoundingClientRect();
  const x = Math.max(4, Math.min(e.clientX, window.innerWidth - r.width - 8));
  const y = Math.max(4, Math.min(e.clientY, window.innerHeight - r.height - 8));
  ctxEl.style.left = x + 'px';
  ctxEl.style.top = y + 'px';
  document.addEventListener('pointerdown', onDocPointer, true);
}

export function initChatPanel({ backend }) {
  panelEl = document.getElementById('chat-panel');
  logEl = document.getElementById('chat-log');
  inputEl = document.getElementById('chat-input');
  sendEl = document.getElementById('chat-send');

  sendEl.addEventListener('click', send);
  inputEl.addEventListener('keydown', (e) => {
    // user starts editing the live voice preview -> stop stomping their input
    if (voicePreviewOn && e.key !== 'Enter') voicePreviewOn = false;
    if (e.key === 'Enter') { e.preventDefault(); send(); }
  });

  // long-term memory viewer: list what she remembers about the user
  document.getElementById('chat-memory')?.addEventListener('click', async () => {
    try {
      const msg = await backend.request({ type: 'get_memory' });
      const items = (msg && Array.isArray(msg.items)) ? msg.items : [];
      if (!items.length) {
        addSys('🧠 我还没有记住关于你的长期记忆，多聊聊你的事吧～');
      } else {
        const lines = items.map((it, i) => `${i + 1}. ${it.text}${it.score > 1 ? `（${it.score} 次）` : ''}`);
        addSys('🧠 我记得关于你的事：\n' + lines.join('\n'));
      }
    } catch {
      addSys('🧠 记忆读取失败，稍后再试');
    }
  });

  // bubble right-click copy menu
  logEl.addEventListener('contextmenu', (e) => {
    const msg = e.target.closest('.chat-msg');
    if (!msg || msg.classList.contains('typing')) { hideCtx(); return; }
    e.preventDefault();
    showCtx(e, msg);
  });

  bus.on('backend:ai_response', (msg) => { finalizeStream(msg.reply, msg.emotion); });
  bus.on('backend:llm_partial', (msg) => showStreaming(msg.text));
  bus.on('backend:stt_partial', (msg) => showVoicePreview(msg.text));
  bus.on('backend:stt_result', (msg) => { clearVoicePreview(); addUser(msg.text, 'voice'); });
  bus.on('backend:error', () => removeThinking());
  bus.on('backend:tts_audio', () => {
    // first TTS chunk arrived -> the reply is complete; stop the stream view
    const dots = logEl.querySelector('.typing');
    if (dots) dots.remove();
  });
}

// ---- live reply bubble (thinking -> typewriter streaming) ----
let streamEl = null;

function removeThinking() {
  const dots = logEl.querySelector('.typing');
  if (dots) dots.remove();
  streamEl = null;
}

// The streamed bubble IS the reply bubble: on ai_response, finalize it in
// place (definitive content, caret removed). Prevents the duplicate-bubble
// bug where the final reply was APPENDED next to the still-caret-ed one.
function finalizeStream(text, emotion) {
  const shown = (text == null ? '' : String(text)).trim() || '……';
  if (streamEl && streamEl.parentNode) {
    streamEl.innerHTML = renderRich(shown);
    if (emotion) streamEl.dataset.emotion = emotion;
    streamEl = null;
  } else {
    // no stream bubble existed (e.g. no-key error path) - add fresh
    removeThinking();
    addAI(shown, emotion);
  }
  const dots = logEl.querySelector('.typing');
  if (dots) dots.remove();
  scrollDown();
}

function showStreaming(partialRaw) {
  // The backend streams the RAW LLM output (JSON per system prompt).
  // Extract the reply string so far for a readable typewriter effect;
  // fall back to the raw prefix until the key appears.
  let shown = extractPartialReply(partialRaw);
  if (shown == null) {
    // JSON key not arrived yet - keep (or create) the 'thinking' dots
    ensureThinkingBubble();
    return;
  }
  if (!streamEl || !streamEl.parentNode) {
    removeThinking();
    streamEl = document.createElement('div');
    streamEl.className = 'chat-msg ai md';
    logEl.appendChild(streamEl);
  }
  streamEl.innerHTML = renderRich(shown) + '<span class="caret"></span>';
  scrollDown();
}

function ensureThinkingBubble() {
  if (logEl.querySelector('.typing')) return;
  const el = document.createElement('div');
  el.className = 'chat-msg ai typing';
  el.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
  logEl.appendChild(el);
  scrollDown();
}

// Pull a best-effort partial reply from streamed raw JSON.
// Returns null while 'reply' value hasn't started arriving yet.
function extractPartialReply(raw) {
  const m = raw.match(/"reply"\s*:\s*"((?:[^"\\]|\\.)*)/);
  if (!m || !m[1]) return null;
  let s = m[1];
  // unescape common JSON escapes progressively (partial-safe)
  s = s.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\').replace(/\\t/g, '\t');
  return s;
}

// ---- live voice preview (streaming STT) ----
// While the user is still speaking, recognized-so-far text is previewed in
// the input box (italic gray); the final stt_result replaces it with the
// voice bubble. Any user keystroke stops the preview from stomping input.
let voicePreviewOn = false;

function showVoicePreview(text) {
  if (!text) return;
  // don't stomp text the user is typing
  if (!voicePreviewOn && inputEl.value.trim()) return;
  voicePreviewOn = true;
  inputEl.value = text + ' …';
  inputEl.classList.add('voice-preview');
}

function clearVoicePreview() {
  if (!voicePreviewOn) return;
  voicePreviewOn = false;
  inputEl.value = '';
  inputEl.classList.remove('voice-preview');
}

function send() {
  let text = inputEl.value.trim();
  if (voicePreviewOn) { voicePreviewOn = false; text = text.replace(/…$/, '').trim(); inputEl.classList.remove('voice-preview'); }
  if (!text) return;
  inputEl.value = '';
  addUser(text, 'me');
  ensureThinkingBubble(); // immediate feedback while LLM is thinking
  bus.emit('backend:send_user', { text });
}

export function toggle() {
  open = !open;
  if (open) { panelEl.classList.remove('hidden'); bus.emit('panel:open'); inputEl.focus(); }
  else { hideCtx(); panelEl.classList.add('hidden'); bus.emit('panel:close'); }
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
  // last line of defense: never render a blank bubble
  const shown = (text == null ? '' : String(text)).trim() || '……';
  const el = document.createElement('div');
  el.className = 'chat-msg ai md' + (opts.error ? ' error' : '');
  el.innerHTML = renderRich(shown); // escaped-then-assembled, XSS-safe
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
  // Rolling trim: long chats used to pile bubbles up in the DOM forever.
  // Keep the most recent 60; never remove the active thinking/stream bubble.
  const MAX = 60;
  const msgs = logEl.querySelectorAll('.chat-msg');
  if (msgs.length > MAX) {
    for (let i = 0; i < msgs.length - MAX; i++) {
      if (msgs[i].classList.contains('typing')) continue;
      msgs[i].remove();
    }
  }
  requestAnimationFrame(() => { logEl.scrollTop = logEl.scrollHeight; });
}
