import { bus } from '../core/EventBus.js';

let toolbarEl, costumeBarEl;
let near = false;
let panelOpen = false;
let hideTimer = null;

export function initToolbar({ voice, chat, settings, dispatcher, costume }) {
  toolbarEl = document.getElementById('toolbar');
  costumeBarEl = document.getElementById('costume-bar');

  // proximity from avatar drives toolbar fade
  bus.on('avatar:proximity', ({ near: n }) => {
    near = !!n;
    refresh();
  });
  bus.on('panel:open', () => { panelOpen = true; refresh(); });
  bus.on('panel:close', () => { panelOpen = false; refresh(); });

  toolbarEl.addEventListener('click', (e) => {
    const act = e.target?.dataset?.act;
    if (!act) return;
    switch (act) {
      case 'mic':
        voice.toggle().then(on => {
          const btn = toolbarEl.querySelector('[data-act="mic"]');
          if (btn) btn.style.background = on ? 'rgba(255,120,170,.5)' : '';
        });
        break;
      case 'chat':
        chat.toggle();
        break;
      case 'costume':
        toggleCostumeBar();
        break;
      case 'leave':
        dispatcher.run('leave');
        break;
      case 'settings':
        settings.toggle();
        break;
    }
  });

  costumeBarEl.addEventListener('click', (e) => {
    const c = e.target?.dataset?.costume;
    if (c) {
      dispatcher.run('change_costume', { costume: c });
      toggleCostumeBar(false);
    }
    if (e.target?.classList?.contains('cb-close')) toggleCostumeBar(false);
  });

  function toggleCostumeBar(force) {
    const open = force === undefined ? costumeBarEl.classList.contains('hidden') : force;
    if (open) { costumeBarEl.classList.remove('hidden'); bus.emit('panel:open'); }
    else { costumeBarEl.classList.add('hidden'); bus.emit('panel:close'); }
  }
}

function refresh() {
  const show = near || panelOpen;
  if (show) {
    // cancel any pending hide so a quick near→far→near doesn't blink
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    toolbarEl.classList.remove('hidden');
  } else if (!hideTimer) {
    // delay the fade-out: gives the cursor time to travel from the avatar
    // to the toolbar without the bar vanishing mid-move
    hideTimer = setTimeout(() => {
      hideTimer = null;
      if (!near && !panelOpen) toolbarEl.classList.add('hidden');
    }, 260);
  }
}

export function setMicActive(active) {
  const btn = toolbarEl?.querySelector('[data-act="mic"]');
  if (!btn) return;
  btn.style.background = active ? 'rgba(255,120,170,.5)' : '';
}
