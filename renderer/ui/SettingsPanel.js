import { cfg, saveConfig } from '../core/ConfigManager.js';
import { bus } from '../core/EventBus.js';

let panelEl;
let open = false;
let loaded = false;   // set by load(); a save without a prior load is
                      // always an anomaly (inputs empty / selects defaulted)
                      // and would corrupt user.json via deep-merge
let promptDefaultTemplate = '';   // built-in template (raw, from get_prompt)

export function initSettingsPanel({ voice }) {
  panelEl = document.getElementById('settings-panel');

  document.querySelector('[data-close="settings"]')?.addEventListener('click', () => toggle(false));
  document.getElementById('set-cancel')?.addEventListener('click', () => toggle(false));
  document.getElementById('set-save')?.addEventListener('click', save);

  // provider toggles show/hide per-provider fields (llm: deepseek/ollama,
  // tts: azure-tts)
  const sel = document.getElementById('set-llm-provider');
  sel.addEventListener('change', refreshFields);
  const ttsSel = document.getElementById('set-tts-provider');
  ttsSel?.addEventListener('change', refreshFields);

  // clear long-term memory (independent of the save flow)
  document.getElementById('set-clear-memory')?.addEventListener('click', () => {
    if (!confirm('确定让她忘掉全部长期记忆吗？（对话历史不受影响）')) return;
    bus.emit('backend:send', { type: 'clear_memory' });
    bus.emit('toast:show', { text: '长期记忆已清除', kind: 'ok', ms: 2000 });
  });

  // persona (System Prompt) editor
  const promptEl = document.getElementById('set-prompt');
  const updateCount = () => {
    const n = (promptEl?.value || '').length;
    const c = document.getElementById('prompt-count');
    if (c) c.textContent = n + ' 字';
  };
  promptEl?.addEventListener('input', updateCount);
  document.getElementById('set-prompt-load-default')?.addEventListener('click', () => {
    promptEl.value = promptDefaultTemplate || '(默认模板获取失败，请稍后重试)';
    updateCount();
    promptEl.focus();
  });
  document.getElementById('set-prompt-reset')?.addEventListener('click', () => {
    promptEl.value = '';
    updateCount();
    bus.emit('toast:show', { text: '已清空，点底部「保存」即恢复内置默认人设', kind: 'ok', ms: 3000 });
  });
}

function refreshFields() {
  const prov = document.getElementById('set-llm-provider').value;
  const tprov = document.getElementById('set-tts-provider')?.value || 'edge';
  document.querySelectorAll('#settings-panel [data-for]').forEach((el) => {
    const f = el.dataset.for;
    const show = f === 'azure-tts' ? tprov === 'azure'
               : f === 'openai-tts' ? tprov === 'openai'
               : f === 'elevenlabs-tts' ? tprov === 'elevenlabs'
               : f === 'gptsovits-tts' ? tprov === 'gptsovits'
               : f === 'elevenlabs-voice' ? tprov === 'elevenlabs'
               : f === 'openai-voice' ? tprov === 'openai'
               : f === 'voice-ea' ? (tprov === 'edge' || tprov === 'azure')
               : f === prov;
    el.style.display = show ? '' : 'none';
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
  const ttsAz = c.tts.azure || {};
  const ttsOi = c.tts.openai || {};
  const ttsEl = c.tts.elevenlabs || {};
  const ttsGs = c.tts.gptsovits || {};
  setVal('set-tts-provider', c.tts.provider || 'edge');
  setVal('set-azure-key', ttsAz.subscription_key || '');
  setVal('set-azure-region', ttsAz.region || 'eastasia');
  setVal('set-openai-key', ttsOi.api_key || '');
  setVal('set-openai-base-url', ttsOi.base_url || '');
  setVal('set-openai-model', ttsOi.model || 'tts-1');
  setVal('set-openai-voice', ttsOi.voice || 'nova');
  setVal('set-el-key', ttsEl.api_key || '');
  setVal('set-el-base-url', ttsEl.base_url || '');
  setVal('set-el-model', ttsEl.model || 'eleven_multilingual_v2');
  setVal('set-el-voice', ttsEl.voice_id || '21m00Tcm4TlvDq8ikWAM');
  setVal('set-gs-base-url', ttsGs.base_url || 'http://127.0.0.1:9880');
  setVal('set-gs-ref-audio', ttsGs.ref_audio || 'assets/voices/ref_default.wav');
  setVal('set-gs-ref-text', ttsGs.ref_text || '');
  setVal('set-tts-voice', c.tts.voice || c.tts.edge.voice);
  setVal('set-tts-rate', c.tts.rate || c.tts.edge.rate);
  document.getElementById('set-tts-volume').value = Math.round((c.tts.volume || 0.9) * 100);
  document.getElementById('set-startup').checked = !!c.window.launch_at_startup;
  setVal('set-hotkey', c.hotkey || 'Control+Alt+G');
  document.getElementById('set-fps').checked = !!c.app.fps_overlay;
  refreshFields();
  loaded = true;

  // persona editor: stored custom + built-in default (async fill)
  window.__backend?.request({ type: 'get_prompt' })?.then((m) => {
    promptDefaultTemplate = m.default || '';
    setVal('set-prompt', m.custom || '');
    const st = document.getElementById('prompt-status');
    if (st) st.textContent = (m.custom || '').trim() ? '当前使用：自定义人设' : '当前使用：内置默认';
    updatePromptCount();
  }).catch?.(() => {});
}

function updatePromptCount() {
  const el = document.getElementById('set-prompt');
  const c = document.getElementById('prompt-count');
  if (el && c) c.textContent = (el.value || '').length + ' 字';
}

function save() {
  // ---- loaded guard (10-12 lesson) ----
  // The panel must have been loaded (values populated) before any save;
  // saving from a never-loaded panel writes EMPTY inputs and DEFAULTED
  // selects through deep-merge and silently corrupts user.json (this is
  // exactly how 10-10's verify_pending wiped the DeepSeek key, and the
  // 10-12 CDP acceptance reproduced it live on api_key).
  if (!loaded) {
    bus.emit('toast:show', { text: '设置面板未加载完成，已跳过本次保存', kind: 'error', ms: 3000 });
    return;
  }
  // ---- field-level empty-save defense ----
  // A save fired while the panel was never loaded (scripted clicks, hotkey
  // paths, UI races) reads EMPTY inputs; deep-merge then blanks real config
  // (the 10-10 verify_pending incident wiped the DeepSeek key that way;
  // 10-12 CDP acceptance reproduced it on api_key). Credentials and
  // identity fields are therefore only written when non-empty; list-valued
  // selects only when they actually carry a value.
  const dsKey = (getVal('set-deepseek-key') || '').trim();
  const dsModel = (getVal('set-deepseek-model') || '').trim();
  const ollamaUrl = (getVal('set-ollama-url') || '').trim();
  const ollamaModel = (getVal('set-ollama-model') || '').trim();
  const whisperModel = getVal('set-whisper-model');
  const whisperLang = getVal('set-whisper-lang');
  const ttsVoice = getVal('set-tts-voice');
  const ttsRate = (getVal('set-tts-rate') || '').trim();
  const patch = {
    llm: {
      provider: getVal('set-llm-provider') || 'deepseek',
      ...(dsModel ? { deepseek: { ...(dsKey ? { api_key: dsKey } : {}), model: dsModel } } :
            (dsKey ? { deepseek: { api_key: dsKey } } : {})),
      ...((ollamaUrl || ollamaModel) ? { ollama: {
        ...(ollamaUrl ? { base_url: ollamaUrl } : {}),
        ...(ollamaModel ? { model: ollamaModel } : {}),
      } } : {}),
    },
    // app: omit empty persona/username so a save from a non-loaded panel
    // (e.g. scripted tests) can never blank out the defaults from config.json
    app: (() => {
      const p = { fps_overlay: document.getElementById('set-fps').checked };
      const persona = (getVal('set-persona') || '').trim();
      const uname = (getVal('set-username') || '').trim();
      if (persona) p.persona_name = persona;
      if (uname) p.user_name = uname;
      return p;
    })(),
    stt: (() => {
      const s = {};
      if (whisperModel) s.model = whisperModel;
      if (whisperLang) s.language = whisperLang;
      if (document.getElementById('set-vad')) s.vad_enabled = document.getElementById('set-vad').checked;
      return s;
    })(),
    tts: (() => {
      const provider = getVal('set-tts-provider') || 'edge';
      const t = {
        provider,
        volume: parseInt(document.getElementById('set-tts-volume').value, 10) / 100,
      };
      // shared zh-CN voice/rate only managed while edge/azure is active —
      // when openai/elevenlabs is selected the old voice stays untouched,
      // so switching back restores it (they have their own voice sets)
      if (provider !== 'openai' && provider !== 'elevenlabs' && ttsVoice) {
        t.voice = ttsVoice;
        if (ttsRate) t.rate = ttsRate;
        t.edge = { ...(ttsRate ? { rate: ttsRate } : {}), voice: ttsVoice };
      }
      // Azure key: omit when blank so a save from a non-loaded panel can
      // never blank a stored key (same defense as persona, 10-10 lesson)
      const azKey = (getVal('set-azure-key') || '').trim();
      if (provider === 'azure' && azKey) {
        t.azure = { subscription_key: azKey, region: getVal('set-azure-region') || 'eastasia' };
      }
      // OpenAI: key/base_url omit-when-blank (blank never overwrites a
      // stored value); model/voice are selects that always carry a value
      if (provider === 'openai') {
        const oiKey = (getVal('set-openai-key') || '').trim();
        const oiBase = (getVal('set-openai-base-url') || '').trim();
        t.openai = {
          ...(oiKey ? { api_key: oiKey } : {}),
          ...(oiBase ? { base_url: oiBase } : {}),
          model: getVal('set-openai-model') || 'tts-1',
          voice: getVal('set-openai-voice') || 'nova',
        };
      }
      // ElevenLabs: key/base_url omit-when-blank; model/voice are selects
      if (provider === 'elevenlabs') {
        const elKey = (getVal('set-el-key') || '').trim();
        const elBase = (getVal('set-el-base-url') || '').trim();
        t.elevenlabs = {
          ...(elKey ? { api_key: elKey } : {}),
          ...(elBase ? { base_url: elBase } : {}),
          model: getVal('set-el-model') || 'eleven_multilingual_v2',
          voice_id: getVal('set-el-voice') || '21m00Tcm4TlvDq8ikWAM',
        };
      }
      // GPT-SoVITS local: all three omit-when-blank (defaults live in
      // config.json; a blank save never blanks a stored path/transcript)
      if (provider === 'gptsovits') {
        const gsBase = (getVal('set-gs-base-url') || '').trim();
        const gsRef = (getVal('set-gs-ref-audio') || '').trim();
        const gsText = (getVal('set-gs-ref-text') || '').trim();
        t.gptsovits = {
          ...(gsBase ? { base_url: gsBase } : {}),
          ...(gsRef ? { ref_audio: gsRef } : {}),
          ...(gsText ? { ref_text: gsText } : {}),
        };
      }
      return t;
    })(),
    window: { launch_at_startup: document.getElementById('set-startup').checked },
    hotkey: (getVal('set-hotkey') || 'Control+Alt+G').trim() || 'Control+Alt+G',
    prompt: (() => {
      // blank OR identical to the built-in template = clear the override
      // (empty string falls back to the default file in load_prompt)
      const t = (getVal('set-prompt') || '').trim();
      if (!t || t === (promptDefaultTemplate || '').trim()) {
        return { system_prompt: '' };
      }
      return { system_prompt: t };
    })(),
  };
  saveConfig(patch).then((saved) => {
    window.desktop.setLaunchAtStartup(patch.window.launch_at_startup);
    bus.emit('backend:send', { type: 'reload_config' });
    bus.emit('settings:saved', patch); // let app.js apply live (TTS volume, FPS badge)
    if (saved && saved._hotkey_error) {
      bus.emit('toast:show', { text: '快捷键「' + saved._hotkey_error + '」注册失败（无效或被占用），已保留原快捷键', kind: 'error', ms: 5000 });
    } else if (saved && saved._hotkey_applied) {
      bus.emit('toast:show', { text: '快捷键已更新为「' + saved._hotkey_applied + '」', kind: 'ok', ms: 2500 });
    } else {
      bus.emit('toast:show', { text: '设置已保存', kind: 'ok', ms: 1800 });
    }
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
