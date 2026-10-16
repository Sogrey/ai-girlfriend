# -*- coding: utf-8 -*-
"""GPT-SoVITS local TTS provider (api_v2, default 127.0.0.1:9880).

The LAST zero-key voice route: runs entirely on the local GPU, which
matters while Edge-TTS is 403-blocked and no online key is configured.
Zero-shot inference needs a reference audio + its transcript; the voice
is whatever the reference audio sounds like (swap the file to re-voice).

Key differences vs online providers:
- No auth at all; a bare REST GET per synthesis (httpx again).
- media_type is WAV (api_v2 default) — the renderer's decodeAudioData
  handles containers transparently, so the existing play path just works.
- Emotion is expressed via speed_factor (0.6..1.5 clamp; api_v2 allows
  0.5..2.0) mapped from the shared '+10%'-style rate, like openai.
- SELF-HEALING (Phase 36): when the api_v2 service is down (reboot day,
  forgotten BAT), the first ConnectError auto-launches it from
  `home_dir` (detached, survives the app), waits for the port, then
  retries the synthesis once — the user never has to remember the BAT
  again. One launch attempt per provider instance; a failed attempt
  falls back to the classic guidance error (the breaker handles noise).
- ref_audio paths are resolved against the PROJECT root so both absolute
  and repo-relative values work in config.
"""
import asyncio
import logging
import os
import subprocess
from urllib.parse import urlparse

import httpx

from tts.base import TTSProvider

logger = logging.getLogger('tts.gptsovits')

DEFAULT_BASE_URL = 'http://127.0.0.1:9880'
DEFAULT_REF_AUDIO = 'assets/voices/ref_default.wav'
# must match the transcript of the shipped reference audio exactly —
# zero-shot cloning quality depends on this pairing
DEFAULT_REF_TEXT = '今天过得怎么样呀？我一直在这里等你呢。要是累了的话，就休息一会儿，我陪你聊聊天吧。'
# local GPT-SoVITS install (venv + api_v2.py live here)
DEFAULT_HOME = r'D:\AI\GPT-SoVITS'

STARTUP_WAIT_SECONDS = 180   # detached cold start reaches listen in ~65s; generous cap
RETRY_TIMEOUT = 240           # first synthesis after a cold self-heal start (model warm-up ~30s+)
PROBE_INTERVAL = 2.0

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def rate_to_speed(rate):
    """'+10%' (edge-style percent) -> float speed, clamped to api_v2's
    sensible 0.6..1.5 band (hard API limit 0.5..2.0). Garbage -> 1.0."""
    s = str(rate or '+0%').strip().replace('%', '')
    try:
        val = float(s)
    except (TypeError, ValueError):
        val = 0.0
    return max(0.6, min(1.5, 1.0 + val / 100.0))


def resolve_ref_audio(path):
    """Absolute passthrough; repo-relative values resolve against ROOT.
    normpath unifies forward slashes so Windows paths arrive consistent."""
    p = str(path or '').strip()
    if not p:
        return ''
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(ROOT, p))


def _default_launcher(host, port, home_dir):
    """Spawn api_v2 detached (survives the app; fully background).
    Returns True when the process was spawned."""
    venv_py = os.path.join(home_dir, 'venv', 'Scripts', 'python.exe')
    script = os.path.join(home_dir, 'api_v2.py')
    if not os.path.isfile(venv_py) or not os.path.isfile(script):
        logger.warning('auto-start skipped: %s incomplete (need venv + api_v2.py)', home_dir)
        return False
    creation = 0
    if os.name == 'nt':
        creation = (subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.CREATE_NO_WINDOW)
    subprocess.Popen([venv_py, script, '-a', host, '-p', str(port)],
                     cwd=home_dir, creationflags=creation,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info('auto-started api_v2 at %s:%s (home=%s)', host, port, home_dir)
    return True


async def _default_probe(host, port):
    """True when a TCP connection to the service succeeds."""
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=2.0)
        return True
    except Exception:
        return False
    finally:
        try:
            if writer:
                writer.close()
        except Exception:
            pass


class GPTSoVITSProvider(TTSProvider):
    name = 'gptsovits'
    media_type = 'wav'

    def __init__(self, cfg, transport=None, starter=None, prober=None):
        self.base_url = (cfg.get('base_url') or '').strip().rstrip('/') or DEFAULT_BASE_URL
        self.ref_audio = resolve_ref_audio(cfg.get('ref_audio') or DEFAULT_REF_AUDIO)
        self.ref_text = (cfg.get('ref_text') or '').strip() or DEFAULT_REF_TEXT
        self.rate = cfg.get('rate', '+0%')
        self.auto_start = bool(cfg.get('auto_start', True))
        self.home_dir = (cfg.get('home_dir') or '').strip() or DEFAULT_HOME
        # how long auto-start waits for the port (test/turning knob; the
        # default is the generous cold-model-load budget)
        self.startup_wait = float(cfg.get('startup_wait') or STARTUP_WAIT_SECONDS)
        u = urlparse(self.base_url)
        self._host = u.hostname or '127.0.0.1'
        self._port = u.port or 9880
        self._transport = transport  # httpx.MockTransport for unit tests
        self._starter = starter or _default_launcher     # (host, port, home) -> bool
        self._prober = prober or _default_probe          # (host, port) -> bool
        self._start_attempted = False                    # one shot per instance
        self._start_lock = asyncio.Lock()

    async def _ensure_service(self):
        """Launch api_v2 (once) and wait until the port answers."""
        async with self._start_lock:
            if self._start_attempted:
                return await self._prober(self._host, self._port)
            self._start_attempted = True
            if not self._starter(self._host, self._port, self.home_dir):
                return False
            loop = asyncio.get_event_loop()
            deadline = loop.time() + self.startup_wait
            while loop.time() < deadline:
                if await self._prober(self._host, self._port):
                    # extra settle beat: uvicorn accepts before the model
                    # is fully warm; the retry request itself absorbs it
                    await asyncio.sleep(1.0)
                    return True
                await asyncio.sleep(PROBE_INTERVAL)
            logger.warning('auto-start: service did not come up within %ss', STARTUP_WAIT_SECONDS)
            return False

    async def synthesize(self, text, **kwargs):
        if not self.ref_audio or not os.path.isfile(self.ref_audio):
            raise ValueError('GPT-SoVITS 参考音频不存在：' + (self.ref_audio or '(未配置)') +
                             ' — 请在设置 → 语音合成 → 参考音频处填写有效 wav，或把音频放到该路径')
        if not self.ref_text:
            raise ValueError('GPT-SoVITS 参考音频文案为空：零样本合成需要参考音频对应的文字，请在设置里填写')
        speed = rate_to_speed(kwargs.get('rate', self.rate))
        params = {
            'text': str(text),
            'text_lang': 'zh',
            'ref_audio_path': self.ref_audio,
            'prompt_text': self.ref_text,
            'prompt_lang': 'zh',
            'speed_factor': speed,
            'streaming_mode': 'false',
            'media_type': 'wav',
        }
        url = f'{self.base_url}/tts'
        try:
            return await self._get(url, params)
        except httpx.ConnectError:
            # service down: self-heal (auto-start + wait + one retry).
            # The retry runs on a COLD service (first synthesis includes
            # ~30s model warm-up), so it gets the generous RETRY_TIMEOUT.
            if self.auto_start:
                logger.info('api_v2 unreachable — attempting self-heal start')
                try:
                    if await self._ensure_service():
                        return await self._get(url, params, timeout=RETRY_TIMEOUT)
                except httpx.ConnectError:
                    pass   # service flapped back down mid-retry: guidance below
            raise ValueError('本地 GPT-SoVITS 服务未启动：自动拉起失败（可手动运行 scripts\\启动GPT-SoVITS.bat），'
                             '等命令行出现 9880 端口监听后再试')

    async def _get(self, url, params, timeout=120.0):
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                resp = await client.get(url, params=params)
        except httpx.TimeoutException:
            raise ValueError('GPT-SoVITS 合成超时（本地推理较慢，或显存不足导致掉速）')
        except httpx.ConnectError:
            raise   # handled by the self-heal path
        if resp.status_code == 400:
            try:
                detail = resp.json().get('message', '')[:150]
            except Exception:
                detail = resp.text[:150]
            raise ValueError(f'GPT-SoVITS 拒绝请求 (400): {detail or "参考音频路径或文案有问题"}')
        if resp.status_code != 200:
            raise ValueError(f'GPT-SoVITS 错误 ({resp.status_code}): {(resp.text or "")[:150]}')
        if not resp.content:
            raise ValueError('TTS 返回空音频')
        return resp.content

    async def list_voices(self):
        return []
