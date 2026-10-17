import { bus } from '../core/EventBus.js';

// Character manager panel (Phase 40): list / create / edit / delete
// character profiles through the backend's save_character /
// delete_character endpoints — nobody has to hand-write JSON files.
//
// Layout: one panel, two modes.
//   list mode: rows (name + desc + current badge / primary note) with
//              per-row edit & delete buttons + "new character" action
//   form mode: name (required), optional id (new only), desc, system
//              prompt (load-default helper), exclusive model & voice
let panelEl, listEl, formEl, listWrapEl, memoryEl;
let backendRef = null;
let open = false;
let editingId = null;      // null = creating
let currentId = null;
let promptDefault = '';
let memoryChar = null;      // {id, name} while the memory view is open

function byId(id) { return document.getElementById(id); }

function setVal(id, v) { const el = byId(id); if (el) el.value = v ?? ''; }
function getVal(id) { return byId(id)?.value ?? ''; }

export function initCharacterPanel({ backend }) {
  backendRef = backend;
  panelEl = byId('character-panel');
  listEl = byId('char-list');
  listWrapEl = byId('char-list-wrap');
  formEl = byId('char-form');
  memoryEl = byId('char-memory');

  panelEl?.querySelector('.panel-close')?.addEventListener('click', () => toggle(false));
  byId('char-new')?.addEventListener('click', () => showForm(null));
  byId('char-cancel')?.addEventListener('click', () => showList());
  byId('char-save')?.addEventListener('click', save);
  byId('char-prompt-default')?.addEventListener('click', async () => {
    if (!promptDefault) {
      try {
        const m = await backendRef.request({ type: 'get_prompt' });
        promptDefault = m.default || '';
      } catch (e) { return; }
    }
    if (promptDefault) { setVal('char-prompt', promptDefault); updatePromptCount(); }
  });
  byId('char-prompt')?.addEventListener('input', updatePromptCount);

  listEl?.addEventListener('click', (e) => {
    const btn = e.target?.closest('button[data-char-act]');
    if (!btn) return;
    const cid = btn.dataset.charId;
    if (btn.dataset.charAct === 'edit') editCharacter(cid);
    else if (btn.dataset.charAct === 'del') deleteCharacter(cid);
    else if (btn.dataset.charAct === 'mem') showMemory(cid);
  });

  byId('char-mem-back')?.addEventListener('click', () => showList());
  byId('char-mem-clear')?.addEventListener('click', () => memoryChar && clearMemory(memoryChar.id, memoryChar.name));

  return toggle;   // app.js wires bus('characters:manage') onto this
}

export function toggle(force) {
  open = force === undefined ? !open : force;
  if (open) {
    showList();
    panelEl?.classList.remove('hidden');
    bus.emit('panel:open');
  } else {
    panelEl?.classList.add('hidden');
    bus.emit('panel:close');
  }
  return open;
}

// ---------- list mode ----------

async function showList() {
  formEl?.classList.add('hidden');
  memoryEl?.classList.add('hidden');
  memoryChar = null;
  listWrapEl?.classList.remove('hidden');
  await refreshList();
}

async function refreshList() {
  let items = [], current = null;
  try {
    const m = await backendRef.request({ type: 'get_characters' });
    items = m.items || [];
    current = m.current;
  } catch (e) {
    listEl.innerHTML = '<div class="hint">角色列表加载失败：' + (e.message || e) + '</div>';
    return;
  }
  currentId = current;
  renderList(items, current);
  // keep the quick bar in the toolbar in sync too
  bus.emit('characters:updated', { items, current });
  return items;
}

function renderList(items, current) {
  if (!listEl) return;
  listEl.innerHTML = '';
  for (const c of items) {
    const row = document.createElement('div');
    row.className = 'char-row' + (c.id === current ? ' current' : '');
    const info = document.createElement('div');
    info.className = 'char-info';
    const nameLine = document.createElement('div');
    nameLine.className = 'char-name-line';
    const nm = document.createElement('span');
    nm.className = 'char-name';
    nm.textContent = c.name || c.id;
    nameLine.appendChild(nm);
    if (c.id === current) {
      const b = document.createElement('span');
      b.className = 'char-badge';
      b.textContent = '当前';
      nameLine.appendChild(b);
    }
    if (c.primary) {
      const b = document.createElement('span');
      b.className = 'char-badge primary';
      b.textContent = '默认';
      nameLine.appendChild(b);
    }
    info.appendChild(nameLine);
    if (c.desc) {
      const d = document.createElement('div');
      d.className = 'char-desc';
      d.textContent = c.desc;
      info.appendChild(d);
    }
    row.appendChild(info);
    const actions = document.createElement('div');
    actions.className = 'char-actions';
    // 🧠 memory entry on EVERY row (Phase 41): the default character's
    // profile is locked to the settings panel, but her memory is still
    // viewable/clearable here
    const mb = document.createElement('button');
    mb.type = 'button';
    mb.className = 'mem';
    mb.dataset.charAct = 'mem';
    mb.dataset.charId = c.id;
    mb.title = '查看她的长期记忆';
    mb.textContent = '🧠 ' + (typeof c.mem_count === 'number' ? c.mem_count : '');
    actions.appendChild(mb);
    if (c.primary) {
      const hint = document.createElement('span');
      hint.className = 'hint';
      hint.textContent = '在设置面板修改';
      actions.appendChild(hint);
    } else {
      const eb = document.createElement('button');
      eb.type = 'button';
      eb.dataset.charAct = 'edit';
      eb.dataset.charId = c.id;
      eb.textContent = '编辑';
      actions.appendChild(eb);
      const db = document.createElement('button');
      db.type = 'button';
      db.className = 'danger';
      db.dataset.charAct = 'del';
      db.dataset.charId = c.id;
      db.textContent = '删除';
      actions.appendChild(db);
    }
    row.appendChild(actions);
    listEl.appendChild(row);
  }
}

// ---------- memory view (Phase 41) ----------

async function showMemory(cid) {
  let items = null, name = cid;
  try {
    const [mem, roster] = await Promise.all([
      backendRef.request({ type: 'get_character_memory', id: cid }),
      backendRef.request({ type: 'get_characters' }),
    ]);
    items = mem.items || [];
    name = ((roster.items || []).find((x) => x.id === cid) || {}).name || cid;
  } catch (e) {
    bus.emit('toast:show', { text: '记忆读取失败: ' + (e.message || e), kind: 'error', ms: 4000 });
    return;
  }
  memoryChar = { id: cid, name };
  const title = byId('char-mem-title');
  if (title) title.textContent = '「' + name + '」的长期记忆';
  const list = byId('char-mem-items');
  if (list) {
    list.innerHTML = '';
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'hint';
      empty.style.padding = '10px 4px';
      empty.textContent = '还没有记住关于你的任何事。聊天的时侯透露点自己的事，她会长久记下来。';
      list.appendChild(empty);
    }
    for (const it of items) {
      const li = document.createElement('div');
      li.className = 'mem-item';
      li.textContent = it.text || '';
      list.appendChild(li);
    }
  }
  const clearBtn = byId('char-mem-clear');
  if (clearBtn) clearBtn.style.display = items.length ? '' : 'none';
  listWrapEl?.classList.add('hidden');
  formEl?.classList.add('hidden');
  memoryEl?.classList.remove('hidden');
}

async function clearMemory(cid, name) {
  if (!window.confirm('让「' + name + '」忘掉全部长期记忆吗？（对话历史不受影响）')) return;
  try {
    await backendRef.request({ type: 'clear_character_memory', id: cid });
    bus.emit('toast:show', { text: '已清除「' + name + '」的长期记忆', kind: 'ok', ms: 2200 });
    await showList();
  } catch (e) {
    bus.emit('toast:show', { text: '清除失败: ' + (e.message || e), kind: 'error', ms: 4000 });
  }
}

// ---------- form mode ----------

async function editCharacter(cid) {
  // full profile through the BACKEND (not a raw file fetch) so the
  // side-backend's redirected characters dir stays authoritative in tests
  let full = null;
  try {
    const m = await backendRef.request({ type: 'get_character', id: cid });
    full = m.profile || {};
  } catch {
    full = {};
  }
  showForm(cid, full);
}

function showForm(cid, full = {}) {
  editingId = cid;
  setVal('char-name', full.name || '');
  setVal('char-desc', full.desc || '');
  setVal('char-prompt', full.system_prompt || '');
  setVal('char-model', full.model || '');
  const gs = (full.voice && full.voice.gptsovits) || {};
  setVal('char-voice-audio', gs.ref_audio || '');
  setVal('char-voice-text', gs.ref_text || '');
  const idInput = byId('char-id');
  if (cid) {
    idInput.value = cid;
    idInput.readOnly = true;
    byId('char-form-title').textContent = '编辑角色';
  } else {
    idInput.value = '';
    idInput.readOnly = false;
    byId('char-form-title').textContent = '新建角色';
  }
  updatePromptCount();
  listWrapEl?.classList.add('hidden');
  memoryEl?.classList.add('hidden');
  formEl?.classList.remove('hidden');
}

function updatePromptCount() {
  const n = (getVal('char-prompt') || '').length;
  const el = byId('char-prompt-count');
  if (el) el.textContent = n + ' 字' + (n ? '' : '（空 = 沿用全局人设）');
}

async function save() {
  const name = getVal('char-name').trim();
  if (!name) {
    bus.emit('toast:show', { text: '角色名字不能为空', kind: 'error', ms: 3000 });
    return;
  }
  const req = {
    type: 'save_character',
    data: {
      name,
      desc: getVal('char-desc').trim(),
      system_prompt: getVal('char-prompt').trim(),
      model: getVal('char-model').trim(),
      voice: {
        ref_audio: getVal('char-voice-audio').trim(),
        ref_text: getVal('char-voice-text').trim(),
      },
    },
  };
  if (editingId) req.id = editingId;
  try {
    const m = await backendRef.request(req);
    bus.emit('toast:show', {
      text: m.reloaded ? '已保存，当前人设已热更新' : '角色「' + name + '」已保存',
      kind: 'ok', ms: 2200,
    });
    await showList();
  } catch (e) {
    bus.emit('toast:show', { text: '保存失败: ' + (e.message || e), kind: 'error', ms: 4000 });
  }
}

async function deleteCharacter(cid) {
  let items = [];
  let name = cid;
  try {
    const m = await backendRef.request({ type: 'get_characters' });
    items = m.items || [];
    name = (items.find((x) => x.id === cid) || {}).name || cid;
  } catch {}
  // deleted profiles keep their own history/memory files (same-id recreate
  // brings the memory back) — say so, then remove only the profile
  const ok = window.confirm('删除角色「' + name + '」？\n' +
    '她自己的聊天记录与记忆文件会保留（config/history-' + cid + '…），重建同名档案还能找回记忆。');
  if (!ok) return;
  try {
    const m = await backendRef.request({ type: 'delete_character', id: cid });
    bus.emit('toast:show', {
      text: m.switched ? '已删除，并回到小满' : '已删除角色「' + name + '」',
      kind: 'ok', ms: 2200,
    });
    await showList();
  } catch (e) {
    bus.emit('toast:show', { text: '删除失败: ' + (e.message || e), kind: 'error', ms: 4000 });
  }
}
