import * as THREE from 'three';
import { ACTION_DURATIONS } from '../animation/AnimationController.js';
import { bus } from '../core/EventBus.js';

// Randomized head-pat voice lines (TTS is requested from backend as normal chat,
// but with fixed intent so responses vary naturally; for instant feedback we
// also play short randomized local reactions via the backend tts action).
const HEADPAT_LINES = [
  '嘿嘿……不要一直摸我的头啦。',
  '再摸头发就乱啦。',
  '唔……你这样我会不好意思的。',
  '好啦好啦，我知道你最喜欢我了。',
  '摸头可以，但是要轻一点哦。',
  '你今天怎么这么喜欢逗我。',
];

// Randomized double-click spin voice lines (spoken via speak_line; never
// used for LLM-triggered spins, which already carry their own reply + TTS).
const SPIN_LINES = [
  '哇，转晕啦。',
  '嘿嘿，我转得快不快？',
  '再来一个？看好咯。',
  '呼——有点小头晕。',
  '转圈这种事，我最拿手了。',
];

// Central dispatcher: maps LLM / UI / tray intents into animation + emotion
// + system actions. All action names live here as the single source of truth.
export class ActionDispatcher {
  constructor({ animation, emotion, avatar, costume, particles, lipsync, chat, backend }) {
    this.animation = animation;
    this.emotion = emotion;
    this.avatar = avatar;
    this.costume = costume;
    this.particles = particles;
    this.lipsync = lipsync;
    this.chat = chat;
    this.backend = backend;
    this.busyLeave = false;
  }

  // emotion strings -> expressions + optional matching animation
  static EMOTION_ANIMS = {
    happy: 'wave', shy: 'shy', angry: 'angry', sad: 'surprised',
    surprised: 'surprised', caring: 'comfort', neutral: null,
  };

  async run(action, payload = {}) {
    const anim = this.animation;
    // invalidate any pending wake-up fade-in: a new action supersedes it
    this._returnToken = (this._returnToken || 0) + 1;
    switch (action) {
      case 'idle':
        anim.interrupt();
        break;
      case 'wave':
        anim.play('wave', { dur: ACTION_DURATIONS.wave });
        break;
      case 'happy': case 'jump':
        this.emotion.set('happy', { hold: 4 });
        anim.play('jump', { dur: ACTION_DURATIONS.jump });
        break;
      case 'dance':
        this.emotion.set('happy', { hold: 5 });
        anim.play('dance', { dur: ACTION_DURATIONS.dance });
        break;
      case 'shy':
        this.emotion.set('shy', { hold: 4 });
        anim.play('shy', { dur: ACTION_DURATIONS.shy });
        const hp = this.avatar.headWorldPos().clone().add(new THREE.Vector3(0, 0.15, 0));
        this.particles.spawnHearts(hp, 10);
        break;
      case 'angry':
        this.emotion.set('angry', { hold: 4 });
        anim.play('angry', { dur: ACTION_DURATIONS.angry });
        break;
      case 'surprised':
        this.emotion.set('surprised', { hold: 3 });
        anim.play('surprised', { dur: ACTION_DURATIONS.surprised });
        break;
      case 'comfort':
        this.emotion.set('caring', { hold: 5 });
        anim.play('comfort', { dur: ACTION_DURATIONS.comfort });
        break;
      case 'think':
        anim.play('think', { dur: ACTION_DURATIONS.think });
        break;
      case 'nod':
        anim.play('nod', { dur: ACTION_DURATIONS.nod });
        break;
      case 'blow_kiss': {
        this.emotion.set('shy', { hold: 3 });
        anim.play('blow_kiss', { dur: ACTION_DURATIONS.blow_kiss });
        const kp = this.avatar.headWorldPos().clone().add(new THREE.Vector3(0.1, 0.2, 0.3));
        this.particles.spawnHearts(kp, 6);
        break;
      }
      case 'stretch':
        anim.play('stretch', { dur: ACTION_DURATIONS.stretch });
        break;
      case 'shake_head':
        anim.play('shake_head', { dur: ACTION_DURATIONS.shake_head });
        break;
      case 'greet':
        this.emotion.set('happy', { hold: 4 });
        anim.play('greet', { dur: ACTION_DURATIONS.greet });
        break;
      case 'spin': {
        this.emotion.set('happy', { hold: 3 });
        anim.play('spin', { dur: ACTION_DURATIONS.spin });
        // sparkle trail while she twirls
        let sn = 0;
        const siv = setInterval(() => {
          if (sn++ > 9) { clearInterval(siv); return; }
          this.particles.spawnStars(this.avatar.chestWorldPos(), 4, { life: 1.0 });
        }, 150);
        // double-click interaction gets an extra cute spoken line
        // (LLM-triggered spins already have their own reply + TTS)
        if (payload && payload.source === 'dblclick') {
          const line = SPIN_LINES[Math.floor(Math.random() * SPIN_LINES.length)];
          this.backend.send({ type: 'speak_line', text: line, emotion: 'happy' });
        }
        break;
      }
      case 'head_pat': {
        this.emotion.set('shy', { hold: 3.5 });
        anim.play('head_pat', { dur: ACTION_DURATIONS.head_pat });
        const hp = this.avatar.headWorldPos();
        this.particles.spawnHearts(hp, 14);
        // randomized reaction line, spoken with TTS, does not enter chat history
        const line = HEADPAT_LINES[Math.floor(Math.random() * HEADPAT_LINES.length)];
        this.backend.send({ type: 'speak_line', text: line, emotion: 'shy' });
        break;
      }
      case 'body_click': {
        // small attention reaction
        this.emotion.set('happy', { hold: 2 });
        const p = this.avatar.chestWorldPos();
        this.particles.spawnStars(p, 8, { life: 0.8 });
        break;
      }
      case 'leave': {
        if (anim.state === 'leave') break;
        anim.play('leave', {
          dur: ACTION_DURATIONS.leave,
          onDone: () => {
            window.desktop.setHeartMode(true);
            bus.emit('avatar:gone');
          },
        });
        break;
      }
      case 'return': {
        // window becomes visible again first, then she walks in.
        // The window-show path is initiated here (LLM intent "回来" via voice/chat);
        // for tray/hotkey wake-up, main calls setHeartMode itself and then sends
        // 'app:awaken' so the renderer only plays the animation (no callback loop).
        await window.desktop.setHeartMode(false);
        this.playReturnAnim();
        break;
      }
      case 'change_costume': {
        const id = payload.costume;
        if (!id || !this.costume.slots[id]) break;
        anim.play('change_costume', {
          dur: ACTION_DURATIONS.change_costume,
          onMid: async () => {
            try { await this.costume.switch(id); } catch (e) { console.error(e); }
          },
        });
        // sparkle particles around her during the twirl
        let n = 0;
        const iv = setInterval(() => {
          if (n++ > 14) { clearInterval(iv); return; }
          this.particles.spawnStars(this.avatar.chestWorldPos(), 4, { life: 1.2 });
        }, 140);
        break;
      }
      default:
        console.warn('[dispatcher] unknown action', action);
    }
  }

  // Pure animation entry: she walks in from the edge and waves.
  // Called both for LLM intent 'return' and for tray/hotkey wake-up.
  playReturnAnim() {
    // Texture re-upload guard: while the window was hidden (heart mode),
    // Chromium evicts the character's GPU textures. After the window becomes
    // visible again they re-upload during the first ~600ms of active
    // rendering (measured), and during that window the character renders as
    // untextured ghost frames that opacity alone cannot hide (MToon outline
    // / shade passes ignore opacity). So hide the whole canvas (element-level
    // hidden: compositing skips it, but WebGL draw calls still run and
    // re-upload textures), then reveal + fade in once textures are back.
    const canvas = document.getElementById('scene');
    if (canvas) canvas.style.visibility = 'hidden';
    this.avatar.setOpacity(0, true);
    const token = ++this._returnToken;
    setTimeout(() => {
      if (canvas) canvas.style.visibility = '';
      if (token !== this._returnToken) return; // superseded by a newer wake-up
      if (this.animation.state !== 'idle') return; // user did something else meanwhile
      this.animation.play('return', {
        dur: ACTION_DURATIONS.return,
        onDone: () => bus.emit('avatar:back'),
      });
      this.emotion.set('happy', { hold: 4 });
    }, 700);
  }

  // Called when backend produced emotion but no special action.
  applyEmotion(emotion) {
    const map = { happy: 'happy', shy: 'shy', angry: 'angry', sad: 'sad', surprised: 'surprised', caring: 'caring', neutral: 'neutral' };
    const e = map[emotion] || 'neutral';
    this.emotion.set(e, { hold: 6 });
    // light random sparkle when very happy
    if (e === 'happy' && Math.random() < 0.4) {
      this.particles.spawnStars(this.avatar.headWorldPos(), 6, { life: 1 });
    }
  }
}
