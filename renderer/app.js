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
import { initChatPanel, toggle as toggleChat } from './ui/ChatPanel.js';
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

  bus.on('backend:connected', () => show('后端已连接', 'ok', 1500));
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
  bus.on('backend:error', (msg) => show(msg.message || '后端错误', 'error', 5000));

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
  sm.onFrame((dt) => {
    const gaze = eye.update(dt);
    animation.update(dt, gaze);
    emotion.update(dt);
    lipsync.update(dt);
    particles.update(dt);
    mouse.update();
    avatar.update(dt);   // sync normalized bones -> raw bones, springbones, expressions
    avatar.tickOpacity(dt);
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
