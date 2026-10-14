// Reminder panel: the ⏰ button next to 🧠 in the chat header opens an
// overlay listing scheduled reminders with add/delete + quick presets.
import { bus } from '../core/EventBus.js';

let panelEl;
let open = false;

const TYPE_LABEL = { once: '一次', daily: '每天', hourly: '每小时' };

export function initReminderPanel() {
  panelEl = document.getElementById('reminder-panel');

  document.getElementById('chat-remind')?.addEventListener('click', () => toggle());
  document.querySelector('[data-close="reminders"]')?.addEventListener('click', () => toggle(false));
  document.getElementById('rem-cancel')?.addEventListener('click', () => toggle(false));

  // type switch: show the matching time input
  document.getElementById('rem-type')?.addEventListener('change', refreshTypeInputs);

  document.getElementById('rem-add')?.addEventListener('click', () => addFromForm(false));
  // quick presets -> hourly water at :00 / stretch at :30
  document.getElementById('rem-water')?.addEventListener('click', () => {
    submit({ rtype: 'hourly', minute: 0, text: '主人，{time} 了，起来倒杯水喝吧～记得活动一下肩膀！', emotion: 'caring' });
  });
  document.getElementById('rem-stretch')?.addEventListener('click', () => {
    submit({ rtype: 'hourly', minute: 30, text: '{time} 啦，久坐对身体不好，站起来伸个懒腰吧！', emotion: 'happy' });
  });

  // a reminder fired: text bubble (speech plays via tts_audio the server
  // already broadcast alongside). Never let it be silent when TTS is down.
  bus.on('backend:reminder_due', (msg) => {
    bus.emit('chat:sys', { text: '⏰ ' + (msg.text || '') });
    if (!panelEl.classList.contains('hidden')) refresh();
  });
}

function refreshTypeInputs() {
  const t = document.getElementById('rem-type').value;
  document.querySelectorAll('#reminder-panel [data-type-field]').forEach((el) => {
    el.style.display = el.dataset.typeField === t ? '' : 'none';
  });
}

async function refresh() {
  try {
    const msg = await window.__backend.request({ type: 'get_reminders' });
    renderList(msg.items || []);
  } catch (e) {
    renderList(null, e.message);
  }
}

function renderList(items, err) {
  const listEl = document.getElementById('rem-list');
  if (!listEl) return;
  if (err) {
    listEl.innerHTML = `<div class="rem-empty">读取失败：${err}</div>`;
    return;
  }
  if (!items.length) {
    listEl.innerHTML = '<div class="rem-empty">还没有提醒。用下面的表单或快捷按钮添加一个吧，比如每小时提醒喝水～</div>';
    return;
  }
  listEl.innerHTML = items.map((it) => `
    <div class="rem-item" data-id="${it.id}">
      <div class="rem-line1">
        <span class="rem-badge rem-${it.type}">${TYPE_LABEL[it.type] || it.type}</span>
        <span class="rem-schedule">${it.schedule || ''}${it.next_due ? ' · 下次 ' + fmtLeft(it.next_due) : ''}</span>
        <button class="rem-del" data-id="${it.id}" title="删除">✕</button>
      </div>
      <div class="rem-text">${escapeHtml(it.text)}</div>
    </div>`).join('');
  listEl.querySelectorAll('.rem-del').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        await window.__backend.request({ type: 'delete_reminder', id: btn.dataset.id });
        refresh();
      } catch {}
    });
  });
}

function fmtLeft(epochSec) {
  const dt = epochSec * 1000 - Date.now();
  if (dt <= 0) return '即将';
  const m = Math.round(dt / 60000);
  if (m < 60) return m + ' 分钟后';
  return (m / 60).toFixed(1) + ' 小时后';
}

async function addFromForm() {
  const t = document.getElementById('rem-type').value;
  const text = (document.getElementById('rem-text')?.value || '').trim();
  const emotion = document.getElementById('rem-emotion')?.value || 'caring';
  if (!text) { toast('提醒内容不能为空'); return; }
  const body = { rtype: t, text, emotion };
  if (t === 'once') {
    const v = document.getElementById('rem-at').value;   // datetime-local
    if (!v) { toast('选一个触发时间'); return; }
    body.at = Math.floor(new Date(v).getTime() / 1000);
  } else if (t === 'daily') {
    const v = document.getElementById('rem-hhmm').value; // time
    if (!v) { toast('选一个每天的时间'); return; }
    body.hhmm = v;
  } else {
    body.minute = parseInt(document.getElementById('rem-minute').value, 10) || 0;
  }
  const ok = await submit(body);
  if (ok) document.getElementById('rem-text').value = '';
}

async function submit(body) {
  try {
    const msg = await window.__backend.request({ type: 'add_reminder', ...body });
    renderList(msg.items || []);
    toast('已添加提醒');
    return true;
  } catch (e) {
    toast('添加失败：' + e.message);
    return false;
  }
}

function toast(text) {
  bus.emit('toast:show', { text, kind: 'ok', ms: 2000 });
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function toggle(force) {
  open = force === undefined ? !open : force;
  if (open) {
    refresh();
    refreshTypeInputs();
    panelEl.classList.remove('hidden');
    bus.emit('panel:open');
  } else {
    panelEl.classList.add('hidden');
    bus.emit('panel:close');
  }
  return open;
}
