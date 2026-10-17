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
    this._sources = [];   // gapless: scheduled-but-playing buffer sources
    this._nextAt = 0;     // absolute AudioContext time the next frame starts at
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

    // Queue one TTS audio chunk (base64 wav). Chunks play gapless, in order.
    // (report-6, 10-17) Each frame is decoded THE MOMENT it arrives and
    // scheduled at the exact end-time of the previous frame (start(when)),
    // instead of the old onended→decode→start chain whose decode latency
    // punched an audible gap between every pair of frames.
  speak(base64, { seq = 0, final = true, onStart, onEnd } = {}) {
    this._ensureCtx();
    if (this.ac.state === 'suspended') this.ac.resume().catch(() => {});
    const bin = atob(base64);
    // empty data frames are pure sequence-closers (final=true, no audio):
    // decodeAudioData would throw EncodingError on the empty buffer (they
    // arrive when a synthesis stream ends without a tail buffer)
    if (bin.length < 45) {
      const item = { empty: true, seq, final, onStart, onEnd };
      const wasIdle = this._queue.length === 0 && !this._playing;
      this._queue.push(item);
      if (wasIdle) this._nextAt = 0;
      this._pump();
      return;
    }
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    const item = { decoded: this.ac.decodeAudioData(buf.buffer), seq, final, onStart, onEnd };
    const wasIdle = this._queue.length === 0 && !this._playing;
    this._queue.push(item);
    if (wasIdle) this._nextAt = 0;   // fresh utterance: schedule from now
    this._pump();
  }

  stopAll() {
    this._queue = [];
    for (const src of this._sources) {
      try { src.onended = null; src.stop(); } catch {}
    }
    this._sources = [];
    this._playing = false;
    this._nextAt = 0;
    if (this._current) {
      try { this._current.stop(); } catch {}
    }
  }

    async _pump() {
      // schedule every decoded-ready frame as far ahead as possible; the
      // loop pulls from _queue as more frames arrive (streaming)
      while (this._queue.length > 0) {
        const item = this._queue.shift();
        if (item.empty) {
          // closer frame: no audio, just state bookkeeping
          if (this._sources.length === 0 && this._queue.length === 0) {
            this._playing = false;
            this._nextAt = 0;
            if (item.final) this._onPlaybackEnd?.();
          }
          item.onEnd?.();
          continue;
        }
        let audioBuf;
      try {
        audioBuf = await item.decoded;
      } catch (e) {
        console.error('lip sync decode error', e);
        // empty data frames / corrupt frames: drop silently; still close
        // the utterance state when nothing else is scheduled (report-6)
        if (this._sources.length === 0 && this._queue.length === 0) {
          this._playing = false;
          this._nextAt = 0;
          if (item.final) this._onPlaybackEnd?.();
        }
        continue;
      }
      const src = this.ac.createBufferSource();
      src.buffer = audioBuf;
      src.connect(this.analyser);
      const when = Math.max(this._nextAt || 0, this.ac.currentTime);
      this._nextAt = when + audioBuf.duration;
      this._sources.push(src);
      this._playing = true;
      this._hasSpokenSinceStart = true;
      item.onStart?.();
      src.onended = () => {
        const i = this._sources.indexOf(src);
        if (i >= 0) this._sources.splice(i, 1);
        item.onEnd?.();
        if (this._sources.length === 0 && this._queue.length === 0) {
          this._playing = false;
          this._nextAt = 0;
          if (item.final) this._onPlaybackEnd?.();
        }
      };
      src.start(when);
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
