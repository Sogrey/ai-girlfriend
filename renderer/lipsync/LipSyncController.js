// Real-time lip sync: analyses TTS audio via Web Audio FFT and maps
// frequency-band energy onto VRM mouth blendshapes (aa/ih/ou/ee/oh).
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// Hz ranges for each mouth shape (vowel formant approximations)
const BANDS = {
  ou: [90, 350],
  oh: [300, 700],
  aa: [500, 1150],
  ih: [1100, 1900],
  ee: [1800, 3200],
};
const MOUTH_KEYS = ['aa', 'ih', 'ou', 'ee', 'oh'];

export class LipSyncController {
  constructor(avatar, { volume = 0.9 } = {}) {
    this.avatar = avatar;
    this.volume = volume;
    this.ac = null;
    this.analyser = null;
    this.gain = null;
    this.freq = null;
    this._binHz = 0;
    this._queue = [];
    this._playing = false;
    this._current = null;
    this._runningMax = {};
    this._smooth = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
    this._onPlaybackEnd = null;
    this._hasSpokenSinceStart = false;
  }

  _ensureCtx() {
    if (this.ac) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    this.ac = new AC({ latencyHint: 'interactive' });
    this.gain = this.ac.createGain();
    this.gain.gain.value = this.volume;
    this.gain.connect(this.ac.destination);
    this.analyser = this.ac.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0.45;
    this.analyser.connect(this.gain);
    this.freq = new Uint8Array(this.analyser.frequencyBinCount);
    this._binHz = this.ac.sampleRate / this.analyser.fftSize;
  }

  setVolume(v) {
    this.volume = v;
    if (this.gain) this.gain.gain.value = v;
  }

  get speaking() { return this._playing || this._queue.length > 0; }

  // Queue one TTS audio chunk (base64 mp3). Chunks play in order.
  speak(base64, { seq = 0, final = true, onStart, onEnd } = {}) {
    this._ensureCtx();
    if (this.ac.state === 'suspended') this.ac.resume().catch(() => {});
    const bin = atob(base64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    this._queue.push({ data: buf.buffer, seq, final, onStart, onEnd });
    if (!this._playing) this._pump();
  }

  stopAll() {
    this._queue = [];
    if (this._current) {
      try { this._current.stop(); } catch {}
    }
    this._playing = false;
  }

  async _pump() {
    if (this._playing) return;
    const item = this._queue.shift();
    if (!item) return;
    this._playing = true;
    this._hasSpokenSinceStart = true;
    try {
      const audioBuf = await this.ac.decodeAudioData(item.data);
      const src = this.ac.createBufferSource();
      src.buffer = audioBuf;
      src.connect(this.analyser);
      this._current = src;
      item.onStart?.();
      src.onended = () => {
        this._playing = false;
        this._current = null;
        item.onEnd?.();
        if (item.final && this._queue.length === 0) this._onPlaybackEnd?.();
        this._pump();
      };
      src.start();
    } catch (e) {
      console.error('lip sync decode/play error', e);
      this._playing = false;
      this._pump();
    }
  }

  onAllPlaybackEnd(fn) { this._onPlaybackEnd = fn; }

  update(dt) {
    if (!this.ac || !this.analyser) return;
    this.analyser.getByteFrequencyData(this.freq);

    // raw band energies 0..1
    const raw = {};
    let total = 0;
    for (const [k, [lo, hi]] of Object.entries(BANDS)) {
      const i0 = Math.floor(lo / this._binHz);
      const i1 = Math.min(Math.ceil(hi / this._binHz), this.freq.length - 1);
      let s = 0, n = 0;
      for (let i = i0; i <= i1; i++) { s += this.freq[i]; n++; }
      raw[k] = n ? (s / n) / 255 : 0;
      total += raw[k];
    }

    const isSpeakingAudio = total > 0.06 || this._playing;
    if (!isSpeakingAudio) {
      // mouth relaxes to closed
      const dec = 1 - Math.exp(-9 * dt);
      for (const k of MOUTH_KEYS) {
        this._smooth[k] = Math.max(0, this._smooth[k] - dec * 0.25);
        this.avatar.setExpression(k, this._smooth[k]);
      }
      return;
    }

    // adaptive normalization: track running max per band (decaying)
    for (const k of MOUTH_KEYS) {
      const r = raw[k];
      const mx = Math.max((this._runningMax[k] || 0.08) * 0.995, r, 0.08);
      this._runningMax[k] = mx;
      const norm = clamp(r / mx, 0, 1);
      const shaped = Math.pow(norm, 1.35);
      // mouth opens fast, closes a bit slower
      const speed = shaped > this._smooth[k] ? 22 : 9;
      const kk = 1 - Math.exp(-speed * dt);
      this._smooth[k] = this._smooth[k] + (shaped - this._smooth[k]) * kk;
      this.avatar.setExpression(k, this._smooth[k]);
    }
  }
}
