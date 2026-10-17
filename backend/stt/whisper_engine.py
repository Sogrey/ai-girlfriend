# -*- coding: utf-8 -*-
"""Faster-Whisper STT engine with CUDA support and CPU fallback.

Real implementation notes:
- faster-whisper uses ctranslate2; on Windows CUDA requires cuBLAS & cuDNN DLLs.
- We auto-locate pip-installed nvidia wheels (.venv/Lib/site-packages/nvidia/*/bin)
  and register them via os.add_dll_directory().
- If CUDA is unavailable or DLL loading fails, we fall back to CPU int8 which
  still transcribes faster than realtime on a modern CPU.
"""
import io
import os
import glob
import time
import logging

logger = logging.getLogger('stt')


class WhisperEngine:
    def __init__(self, config):
        self.config = config.get('stt', {})
        self.model = None
        self.device = None
        self.compute_type = None
        self.ready = False
        self.error = None
        self.note = None   # non-fatal degrade notice (rides status once)
        self._last_load_time = 0

    def _add_cuda_dlls(self):
        """Register pip nvidia wheel DLL directories so ctranslate2 can load cuBLAS/cuDNN.

        Uses three methods for reliability across threads on Windows:
        1. Prepend bin dirs to PATH (legacy search, always checked)
        2. os.add_dll_directory (modern Windows 10+)
        3. ctypes preload of critical DLLs (permanent process-wide load)
        """
        try:
            venv_site = os.path.abspath(os.path.join(
                os.path.dirname(__file__), '..', '..', '.venv', 'Lib', 'site-packages'))
            bin_dirs = []
            for d in glob.glob(os.path.join(venv_site, 'nvidia', '*', 'bin')):
                if os.path.isdir(d):
                    bin_dirs.append(os.path.abspath(d))
            # Method 1: PATH
            for d in bin_dirs:
                os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH', '')
            # Method 2: add_dll_directory
            for d in bin_dirs:
                try:
                    os.add_dll_directory(d)
                    logger.info('registered CUDA DLL dir: %s', d)
                except Exception as e:
                    logger.warning('add_dll_directory failed %s: %s', d, e)
            # Method 3: preload critical DLLs permanently via ctypes
            import ctypes
            critical = ['cublas64_12.dll', 'cublasLt64_12.dll', 'cudnn64_9.dll',
                        'cudnn_ops64_9.dll', 'cudnn_graph64_9.dll',
                        'nvrtc64_120_0.dll']
            for d in bin_dirs:
                for dll in critical:
                    p = os.path.join(d, dll)
                    if os.path.exists(p):
                        try:
                            ctypes.WinDLL(p)
                            logger.info('preloaded %s', dll)
                        except Exception as e:
                            logger.warning('preload failed %s: %s', dll, e)
        except Exception as e:
            logger.warning('CUDA DLL discovery failed: %s', e)

    def load(self):
        """Load (or reload) the whisper model according to config. Safe to call repeatedly.

        DEGRADE CHAIN (10-17): a single CUDA->CPU fallback is not enough on
        a 6GB GPU shared with the GPT-SoVITS voice service (~2.1GB resident)
        and a 15GB RAM box running Electron: float16 OOMs on CUDA and int8
        OOMs on system RAM. We now walk a resource-lighter chain and keep
        the FIRST combo that loads:
          cuda float16 -> cuda int8 -> cpu int8 -> cpu int8 (one model
          smaller: base -> tiny), each attempt tightening the budget.
        The user-visible error becomes an actionable hint instead of the
        raw exception soup."""
        model_name = self.config.get('model', 'small')
        device = self.config.get('device', 'auto')
        compute_type = self.config.get('compute_type', 'auto')

        if device in ('auto', 'cuda') or compute_type == 'auto':
            self._add_cuda_dlls()
            cuda_ok = False
            try:
                import ctranslate2
                cuda_ok = ctranslate2.get_cuda_device_count() > 0
            except Exception as e:
                logger.warning('ctranslate2 cuda probe failed: %s', e)
            if device == 'auto':
                device = 'cuda' if cuda_ok else 'cpu'
            if compute_type == 'auto':
                compute_type = 'float16' if (cuda_ok and device == 'cuda') else 'int8'

        # release old model before loading new one
        self.model = None
        self.ready = False
        t0 = time.time()

        # candidate chain from heaviest to lightest
        candidates = [(model_name, device, compute_type)]
        if device == 'cuda' and compute_type != 'int8':
            candidates.append((model_name, 'cuda', 'int8'))
        if device != 'cpu' or compute_type != 'int8':
            candidates.append((model_name, 'cpu', 'int8'))
        # memory-tight last resort: step the MODEL down too (keep order stable for tiny)
        for smaller in ('base', 'tiny'):
            if smaller != model_name:
                candidates.append((smaller, 'cpu', 'int8'))

        attempts = []
        for m, d, c in candidates:
            try:
                from faster_whisper import WhisperModel
                logger.info('loading whisper model=%s device=%s compute_type=%s', m, d, c)
                self.model = WhisperModel(m, device=d, compute_type=c)
                self.device = d
                self.compute_type = c
                self.ready = True
                self.note = None
                if m != model_name or (d, c) != (device, compute_type):
                    self.note = ('语音识别已降级运行（%s/%s%s）以适配显存/内存。'
                                 '如需全速可在设置→语音识别里换更小的模型。'
                                 % (d, c, '' if m == model_name else '，模型 ' + m))
                    logger.warning(self.note)
                self.error = None
                logger.info('whisper ready on %s %s (%s) in %.1fs', m, d, c, time.time() - t0)
                return
            except Exception as e:
                attempts.append('%s/%s/%s: %s' % (m, d, c, e))
                logger.warning('whisper attempt failed %s/%s/%s: %s', m, d, c, e)
        self.error = ('语音识别引擎启动失败：显存或内存不足（本地语音服务会占用较多资源）。'
                      '可到 设置 → 语音识别 把模型换成 base 或 tiny 再试；'
                      '或暂时把语音合成切到 Edge 在线，释放本地资源。')
        logger.error('all whisper candidates failed:\n%s', '\n'.join(attempts))

    def reload_config(self, config):
        stt = config.get('stt', {})
        changed = (
            stt.get('model') != self.config.get('model') or
            stt.get('device') != self.config.get('device') or
            stt.get('compute_type') != self.config.get('compute_type')
        )
        self.config = stt
        if changed and self.model is not None:
            self.load()

    def transcribe(self, audio_bytes, fmt='webm', vad=None):
        """Transcribe audio bytes -> text.
        `vad`: None = config default (final utterances); False = no VAD
        (live partials: silero would trim mid-sentence pauses and the
        still-open tail, making the previewed text jump backwards)."""
        if not self.ready:
            raise RuntimeError('语音识别引擎未就绪: ' + (self.error or 'loading'))
        lang = self.config.get('language', 'zh')
        if vad is None:
            vad = bool(self.config.get('vad_enabled', True))
        buf = io.BytesIO(audio_bytes)
        # PyAV needs a hint for webm container without filename
        buf.name = 'audio.' + (fmt or 'webm')
        t0 = time.time()
        segments, info = self.model.transcribe(
            buf,
            language=lang if lang and lang != 'auto' else None,
            vad_filter=vad,
            vad_parameters={'min_silence_duration_ms': 300, 'speech_pad_ms': 200},
            beam_size=1,
            best_of=1,
        )
        text = ''.join(seg.text for seg in segments).strip()
        logger.info('transcribed in %.2fs -> %r', time.time() - t0, text)
        return text
