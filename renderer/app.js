import * as THREE from 'three';
console.log('[app] module executing at', Date.now());
import { loadConfig, cfg } from './core/ConfigManager.js';
import { bus } from './core/EventBus.js';
import { backend } from './core/BackendClient.js';
import { SceneManager } from './scene/SceneManager.js';
import { AvatarController } from './avatar/AvatarController.js';
import { CostumeManager } from './avatar/CostumeManager.js';
import { ParticleSystem } from './avatar/ParticleSystem.js';
import { AnimationController } from './animation/AnimationController.js';
import { EmotionController } from './emotion/EmotionController.js';
import { LipSyncController } from './lipsync/LipSyncController.js';
import { EyeTrackingController } from './interaction/EyeTrackingController.js';
import { MouseInteractionController } from './interaction/MouseInteractionController.js';
import { VoiceController } from './interaction/VoiceController.js';
import { ActionDispatcher } from './actions/ActionDispatcher.js';
import { initToast, show } from './ui/Toast.js';
import { initToolbar } from './ui/Toolbar.js';
import { initChatPanel, toggle as toggleChat, addAI as addAIBubble, addUser as addChatUser } from './ui/ChatPanel.js';
import { initSettingsPanel, toggle as toggleSettings } from './ui/SettingsPanel.js';

async function boot() {
  window.__backend = backend;
  await loadConfig();
  const c = cfg();
  initToast();

  const canvas = document.getElementById('scene');
  const sm = new SceneManager(canvas);
  const avatar = new AvatarController(sm);
  const costume = new CostumeManager(avatar, c);
  const animation = new AnimationController(avatar);
  const emotion = new EmotionController(avatar);
  const eye = new EyeTrackingController(avatar, sm);
  const lipsync = new LipSyncController(avatar, { volume: c.tts.volume || 0.9 });
  window.__lipsync = lipsync; // debug/verification hook (gain readable in tests)
  const particles = new ParticleSystem(sm);
  const mouse = new MouseInteractionController(sm, avatar);

  // Voice input with VAD
  const recIndicator = document.getElementById('rec-indicator');
  const voice = new VoiceController({
    silenceMs: c.stt.silence_ms || 800,
    minSpeechMs: c.stt.min_speech_ms || 250,
    onStatus: (status, msg) => {
      if (status === 'listening') recIndicator.classList.add('hidden');
      else if (status === 'speech') { recIndicator.classList.remove('hidden'); recIndicator.textContent = '● 正在聆听'; }
      else if (status === 'processing') { recIndicator.classList.remove('hidden'); recIndicator.textContent = '● 识别中…'; }
      else if (status === 'off') recIndicator.classList.add('hidden');
      else if (status === 'error') show(msg, 'error', 5000);
    },
  });

  // UI
  const chat = { toggle: () => toggleChat() };
  initChatPanel({ backend });
  const settings = { toggle: () => toggleSettings() };
  initSettingsPanel({ voice });

  const dispatcher = new ActionDispatcher({
    animation, emotion, avatar, costume, particles, lipsync, chat, backend,
  });

  initToolbar({ voice, chat, settings, dispatcher, costume });

  // ---- wire bus events ----
  bus.on('action:request', ({ action, payload }) => dispatcher.run(action, payload || {}));
  bus.on('backend:send_user', ({ text }) => backend.send({ type: 'user_message', text }));
  bus.on('backend:send', (msg) => backend.send(msg));

  // settings saved in the panel -> apply TTS playback volume immediately
  // (previously the value was only read once at boot, so the slider did nothing)
  bus.on('settings:saved', ({ tts }) => {
    if (tts && typeof tts.volume === 'number') lipsync.setVolume(tts.volume);
  });

  // ---- FPS badge (debug overlay, toggled from settings) ----
  const fpsBadge = document.getElementById('fps-badge');
  function applyFpsOverlay() {
    try { fpsBadge?.classList.toggle('hidden', !cfg().app?.fps_overlay); } catch {}
  }
  bus.on('settings:saved', () => applyFpsOverlay());
  applyFpsOverlay();

  bus.on('backend:connected', () => {
    show('后端已连接', 'ok', 1500);
    // replay recent chat history so she "remembers" previous talks
    backend.request({ type: 'get_history' }).then((msg) => {
      const items = msg && msg.items;
      if (Array.isArray(items) && items.length) {
        for (const it of items) {
          if (it.role === 'user') addChatUser(it.content, 'me');
          else if (it.role === 'assistant') addAIBubble(it.content, null);
        }
      }
    }).catch(() => {});
  });
  bus.on('backend:ai_response', (msg) => {
    dispatcher.applyEmotion(msg.emotion);
    if (msg.action && msg.action !== 'idle') dispatcher.run(msg.action, { costume: msg.costume });
  });
  bus.on('backend:tts_audio', (msg) => {
    lipsync.speak(msg.data, { seq: msg.seq || 0, final: msg.final !== false });
  });
  bus.on('backend:status', (msg) => {
    if (msg.stt_ready === false) show('语音识别引擎: ' + (msg.stt_error || '未就绪'), 'warn', 4000);
  });
  bus.on('backend:error', (msg) => {
    // Show backend/LLM errors as her reply bubble inside the chat panel
    // (auto-opens the panel if closed). The old top-right toast could be
    // clipped off-screen for long messages containing URLs.
    const text = msg.message || '后端错误';
    const panel = document.getElementById('chat-panel');
    if (panel && panel.classList.contains('hidden')) toggleChat();
    addAIBubble(text, null, { error: true });
  });

  backend.connect();

  // ---- load VRM model ----
  console.log('[boot] persona=' + c.app.persona_name, 'llm=' + c.llm.provider, 'stt=' + c.stt.model);
  const result = await costume.initialLoad();
  console.log('[boot] model load result', JSON.stringify(result));
  if (!result.ok) {
    show('VRM 模型加载失败：' + result.error, 'error', 8000);
    show('请将 VRM 模型放到 assets/models/default.vrm（或 assets/costumes/costume_casual.vrm）', 'warn', 8000);
  } else if (result.note) {
    show(result.note, 'warn', 5000);
  }

  // intro: she appears with a fade-in, but only after the canvas has been
  // composited for a moment (textures fully uploaded on first frames)
  if (avatar.hasModel()) {
    avatar.setOpacity(0, true);
    const sceneCanvas = document.getElementById('scene');
    if (sceneCanvas) sceneCanvas.style.visibility = 'hidden';
    console.log('[boot] starting intro return animation');
    setTimeout(() => {
      if (sceneCanvas) sceneCanvas.style.visibility = '';
      animation.play('return', { dur: 3.4, onDone: () => { console.log('[boot] intro done'); emotion.set('happy', { hold: 3 }); } });
    }, 300);
  }

  // ---- main loop ----
  let uiVarsT = 0;
  let fpsAcc = 0, fpsCount = 0, fpsSum = 0, fpsSumN = 0, fpsMin = Infinity, fpsMax = 0;
  sm.onFrame((dt) => {
    const gaze = eye.update(dt);
    animation.update(dt, gaze);
    emotion.update(dt);
    lipsync.update(dt);
    particles.update(dt);
    mouse.update();
    avatar.update(dt);   // sync normalized bones -> raw bones, springbones, expressions
    avatar.tickOpacity(dt);

    // Anchor the UI refresh CSS vars (throttled - they only change on
    // drag/resize anyway): --av-x/--av-head-y keep the panels above her
    // head, --av-feet-y pins the vertical toolbar to her lower-right side.
    uiVarsT += dt;
    if (uiVarsT > 0.25 && avatar.hasModel()) {
      uiVarsT = 0;
      try {
        const head = sm.worldToScreen(avatar.headWorldPos());
        const foot = sm.worldToScreen(avatar.chestWorldPos());
        const feet = sm.worldToScreen(avatar.footWorldPos());
        const root = document.documentElement.style;
        root.setProperty('--av-head-y', `${Math.round(head.y)}px`);
        root.setProperty('--av-x', `${Math.round((head.x + foot.x) / 2)}px`);
        // guard: foot bone projection should never sit above the head
        root.setProperty('--av-feet-y', `${Math.round(Math.max(feet.y, head.y + 100))}px`);
      } catch {}
    }

    // FPS meter: 1s live value on the badge + 5s summary to console.
    // Pure additive accounting on the existing frame callback - no extra rAF.
    fpsAcc += dt; fpsCount++;
    if (fpsAcc >= 1) {
      const f = fpsCount / fpsAcc;
      fpsSum += fpsAcc; fpsSumN += fpsCount;
      fpsMin = Math.min(fpsMin, f); fpsMax = Math.max(fpsMax, f);
      if (fpsBadge && !fpsBadge.classList.contains('hidden')) {
        fpsBadge.textContent = Math.round(f) + ' fps';
        fpsBadge.classList.toggle('low', f < 50);
      }
      if (fpsSum >= 5) {
        console.log(`[fps] avg=${(fpsSumN / fpsSum).toFixed(1)} min=${fpsMin.toFixed(1)} max=${fpsMax.toFixed(1)}`);
        fpsSum = 0; fpsSumN = 0; fpsMin = Infinity; fpsMax = 0;
      }
      fpsAcc = 0; fpsCount = 0;
    }
  });
  sm.start();

  // Reveal the window only now: the model + textures are fully loaded and
  // the render loop is running, so the first visible frame is a properly
  // textured character (no half-loaded white/transparent flash).
  window.desktop.showWindow();

  // ---- shortcuts & tray ----
  window.desktop.onShortcutToggle((info) => {
    if (info.reason === 'leave') dispatcher.run('leave');
  });
  window.desktop.onAwaken(() => dispatcher.playReturnAnim());
  window.desktop.onTrayAction((a) => {
    if (a.action === 'open_settings') toggleSettings(true);
    else if (a.action === 'change_costume') dispatcher.run('change_costume', { costume: a.costume });
    else if (a.action === 'leave') dispatcher.run('leave');
    else if (a.action === 'return') dispatcher.run('return');
  });

  window.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && e.key === 'I') {
      e.preventDefault(); window.desktop.openDevTools();
    }
  });

  console.log('AI Girlfriend boot complete.');
}

window.addEventListener('error', (e) => show('运行时错误: ' + (e.error?.message || e.message), 'error', 5000));
window.addEventListener('unhandledrejection', (e) => show('异步错误: ' + (e.reason?.message || e.reason), 'error', 5000));

boot().catch((e) => { console.error(e); show('启动失败: ' + (e.message || e), 'error', 8000); });
