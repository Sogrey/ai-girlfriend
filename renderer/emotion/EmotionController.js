// Expression (emotion + blink) controller over VRM blendshapes.
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// emotion -> VRM expression weight targets
const EMOTIONS = {
  neutral: {},
  happy:    { happy: 0.8, relaxed: 0.15 },
  shy:      { happy: 0.5, relaxed: 0.35 },
  angry:    { angry: 0.85 },
  sad:      { sad: 0.85 },
  surprised:{ surprised: 0.95 },
  caring:   { happy: 0.3, relaxed: 0.6 },
};

// expression keys owned by this controller (mouth keys belong to LipSync)
const OWNED_KEYS = ['happy', 'angry', 'sad', 'surprised', 'relaxed'];

export class EmotionController {
  constructor(avatar) {
    this.avatar = avatar;
    this.target = {};
    this.current = {};
    this.holdTimer = 0;
    // blink state
    this.nextBlink = 2 + Math.random() * 3;
    this.blinkTimer = 0;
    this.blinking = false;
  }

  set(emotion, { hold = 6.0 } = {}) {
    const map = EMOTIONS[emotion] || EMOTIONS.neutral;
    this.target = {};
    for (const k of OWNED_KEYS) this.target[k] = map[k] || 0;
    this.holdTimer = hold;
    if (emotion === 'shy') this._tryBlush(0.9);
    else this._tryBlush(emotion === 'angry' ? 0.0 : 0.35);
  }

  _tryBlush(v) {
    // many VRM girls ship a custom "blush" expression
    if (this.avatar.hasExpression('blush')) this.avatar.setExpression('blush', v);
  }

  update(dt) {
    // decay to neutral after hold
    if (this.holdTimer > 0) {
      this.holdTimer -= dt;
      if (this.holdTimer <= 0) {
        for (const k of OWNED_KEYS) this.target[k] = 0;
        this._tryBlush(0);
      }
    }

    // approach targets
    const k = 1 - Math.exp(-6 * dt);
    for (const key of OWNED_KEYS) {
      const t = this.target[key] || 0;
      const c = this.current[key] || 0;
      const n = c + (t - c) * k;
      this.current[key] = n;
      this.avatar.setExpression(key, n);
    }

    // blink scheduling
    if (!this.blinking) {
      this.nextBlink -= dt;
      if (this.nextBlink <= 0) {
        this.blinking = true;
        this.blinkTimer = 0;
      }
    } else {
      this.blinkTimer += dt;
      const d = 0.16; // total blink duration
      let v;
      if (this.blinkTimer < d * 0.4) v = this.blinkTimer / (d * 0.4);
      else if (this.blinkTimer < d) v = 1 - (this.blinkTimer - d * 0.4) / (d * 0.6);
      else { v = 0; this.blinking = false; this.nextBlink = 2 + Math.random() * 3.5; }
      this.avatar.setExpression('blink', clamp(v, 0, 1));
    }
  }
}
