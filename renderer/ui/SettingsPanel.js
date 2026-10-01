import { cfg, saveConfig } from '../core/ConfigManager.js';
import { bus } from '../core/EventBus.js';

let panelEl;
let open = false;

export function initSettingsPanel({ voice }) {
  panelEl = document.getElementById('settings-panel');

  document.querySelector('[data-close="settings"]')?.addEventListener('click', () => toggle(false));
  document.getElementById('set-cancel')?.addEventListener('click', () => toggle(false));
  document.getElementById('set-save')?.addEventListener('click', save);

  // provider toggle shows/hides ollama vs deepseek fields
  const sel = document.getElementById('set-llm-provider');
  sel.addEventListener('change', refreshFields);
}

function refreshFields() {
  const prov = document.getElementById('set-llm-provider').value;
  document.querySelectorAll('#settings-panel [data-for]').forEach((el) => {
    el.style.display = el.dataset.for === prov ? '' : 'none';
  });
}

function load() {
  const c = cfg();
  setVal('set-llm-provider', c.llm.provider);
  setVal('set-deepseek-key', c.llm.deepseek.api_key);
  setVal('set-deepseek-model', c.llm.deepseek.model);
  setVal('set-ollama-url', c.llm.ollama.base_url);
  setVal('set-ollama-model', c.llm.ollama.model);
  setVal('set-persona', c.app.persona_name);
  setVal('set-username', c.app.user_name);
  setVal('set-whisper-model', c.stt.model);
  setVal('set-whisper-lang', c.stt.language);
  document.getElementById('set-vad').checked = !!c.stt.vad_enabled;
  setVal('set-tts-voice', c.tts.edge.voice);
  setVal('set-tts-rate', c.tts.edge.rate);
  document.getElementById('set-tts-volume').value = Math.round((c.tts.volume || 0.9) * 100);
  document.getElementById('set-startup').checked = !!c.window.launch_at_startup;
  refreshFields();
}

function save() {
  const patch = {
    llm: {
      provider: getVal('set-llm-provider'),
      deepseek: { api_key: getVal('set-deepseek-key'), model: getVal('set-deepseek-model') },
      ollama: { base_url: getVal('set-ollama-url'), model: getVal('set-ollama-model') },
    },
    app: { persona_name: getVal('set-persona'), user_name: getVal('set-username') },
    stt: {
      model: getVal('set-whisper-model'),
      language: getVal('set-whisper-lang'),
      vad_enabled: document.getElementById('set-vad').checked,
    },
    tts: {
      edge: { voice: getVal('set-tts-voice'), rate: getVal('set-tts-rate') },
      volume: parseInt(document.getElementById('set-tts-volume').value, 10) / 100,
    },
    window: { launch_at_startup: document.getElementById('set-startup').checked },
  };
  saveConfig(patch).then(() => {
    window.desktop.setLaunchAtStartup(patch.window.launch_at_startup);
    bus.emit('backend:send', { type: 'reload_config' });
    bus.emit('toast:show', { text: '设置已保存', kind: 'ok', ms: 1800 });
    toggle(false);
  }).catch((e) => {
    bus.emit('toast:show', { text: '保存失败: ' + e.message, kind: 'error' });
  });
}

function setVal(id, v) { const el = document.getElementById(id); if (el) el.value = v ?? ''; }
function getVal(id) { return document.getElementById(id)?.value; }

export function toggle(force) {
  open = force === undefined ? !open : force;
  if (open) { load(); panelEl.classList.remove('hidden'); bus.emit('panel:open'); }
  else { panelEl.classList.add('hidden'); bus.emit('panel:close'); }
  return open;
}
