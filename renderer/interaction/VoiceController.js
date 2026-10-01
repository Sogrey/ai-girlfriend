// Microphone input with energy-based VAD:
//  - speech starts when RMS rises above adaptive threshold
//  - speech ends after `silence_ms` of quiet -> send audio to backend for STT
export class VoiceController {
  constructor(opts = {}) {
    this.active = false;
    this.stream = null;
    this.recorder = null;
    this.chunks = [];
    this.speechActive = false;
    this.speechStartIdx = 0;
    this.silenceTimer = 0;
    this.noiseFloor = 0.008;
    this._sending = false;
    this._onStatus = opts.onStatus || (() => {});
    this.ac = null;
    this.analyser = null;
    this.srcNode = null;
    this._raf = null;
    this._lastRms = 0;
    this.minSpeechMs = opts.minSpeechMs || 250;
    this.silenceMs = opts.silenceMs || 800;
  }

  async toggle() {
    if (this.active) { this.stop(); return false; }
    await this.start();
    return true;
  }

  async start() {
    if (this.active) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      this._onStatus('error', '麦克风获取失败: ' + (e.message || e.name));
      return;
    }
    this.active = true;
    this.speechActive = false;
    this._onStatus('listening');

    // analyser for VAD
    this.ac = new (window.AudioContext || window.webkitAudioContext)();
    this.srcNode = this.ac.createMediaStreamSource(this.stream);
    this.analyser = this.ac.createAnalyser();
    this.analyser.fftSize = 512;
    this.analyser.smoothingTimeConstant = 0.2;
    this.srcNode.connect(this.analyser);

    // recorder (webm/opus, faster-whisper decodes via PyAV)
    let mime = 'audio/webm;codecs=opus';
    if (!MediaRecorder.isTypeSupported?.(mime)) mime = 'audio/webm';
    if (!MediaRecorder.isTypeSupported?.(mime)) mime = '';
    this.recorder = mime ? new MediaRecorder(this.stream, { mimeType: mime, audioBitsPerSecond: 32000 })
                         : new MediaRecorder(this.stream);
    this.chunks = [];
    this.recorder.ondataavailable = (e) => { if (e.data && e.data.size) this.chunks.push(e.data); };
    this.recorder.onstop = () => this._onRecorderStop();
    this.recorder.start(250); // chunk every 250ms

    this._loop();
  }

  stop() {
    this.active = false;
    this._onStatus('off');
    try { this.recorder?.stop(); } catch {}
    try { this.stream?.getTracks().forEach(t => t.stop()); } catch {}
    try { this.ac?.close(); } catch {}
    if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
  }

  _loop() {
    const tick = () => {
      if (!this.active) return;
      this._vad();
      this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
  }

  _vad() {
    const buf = new Uint8Array(this.analyser.fftSize);
    this.analyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
    const rms = Math.sqrt(sum / buf.length);
    this._lastRms = rms;

    const now = performance.now();
    const threshold = Math.max(this.noiseFloor * 3.2, 0.012);

    if (!this.speechActive) {
      // adapt noise floor while silent
      this.noiseFloor = this.noiseFloor * 0.98 + rms * 0.02;
      if (rms > threshold) {
        this.speechActive = true;
        this.speechStartTime = now;
        // keep ~2s of pre-roll
        this.speechStartIdx = Math.max(0, this.chunks.length - 8);
        this._onStatus('speech');
      }
    } else {
      if (rms < Math.max(this.noiseFloor * 2.0, 0.008)) {
        if (!this.speechEndTime) this.speechEndTime = now;
        if (now - this.speechEndTime >= this.silenceMs &&
            now - this.speechStartTime >= this.minSpeechMs) {
          this.speechActive = false;
          this.speechEndTime = null;
          this._onStatus('processing');
          this._flush();
        }
      } else {
        this.speechEndTime = null;
      }
      // cap continuous speech at 30s (force cut)
      if (now - this.speechStartTime > 30000) {
        this.speechActive = false;
        this._onStatus('processing');
        this._flush();
      }
    }
  }

  async _flush() {
    if (this._sending || !this.recorder || this.recorder.state !== 'recording') return;
    this._sending = true;
    const speechChunks = this.chunks.slice(this.speechStartIdx);
    this.speechStartIdx = this.chunks.length;
    if (speechChunks.length === 0) { this._sending = false; return; }

    // stop recorder to close current blob, then restart for next utterance
    await new Promise((resolve) => {
      const rec = this.recorder;
      const prevStop = rec.onstop;
      rec.onstop = async () => {
        rec.onstop = prevStop;
        try {
          const blob = new Blob(speechChunks, { type: rec.mimeType || 'audio/webm' });
          const b64 = await blobToBase64(blob);
          window.__backend?.send({ type: 'transcribe_audio', data: b64, format: 'webm' });
          this._onStatus('listening');
        } catch (e) {
          this._onStatus('error', '发送音频失败: ' + e.message);
        }
        // restart recorder
        this.chunks = [];
        if (this.active) {
          try { rec.start(250); } catch {}
        }
        resolve();
      };
      try { rec.stop(); } catch { resolve(); }
    });
    this._sending = false;
  }

  get rms() { return this._lastRms; }
}

export function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => {
      const s = String(r.result);
      resolve(s.slice(s.indexOf(',') + 1));
    };
    r.onerror = reject;
    r.readAsDataURL(blob);
  });
}
