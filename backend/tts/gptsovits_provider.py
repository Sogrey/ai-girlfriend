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
- A dedicated launcher script (scripts\\启动GPT-SoVITS.bat) starts the
  api_v2 service; this provider guides the user to it on connect errors.
- ref_audio paths are resolved against the PROJECT root so both absolute
  and repo-relative values work in config.
"""
import logging
import os

import httpx

from tts.base import TTSProvider

logger = logging.getLogger('tts.gptsovits')

DEFAULT_BASE_URL = 'http://127.0.0.1:9880'
DEFAULT_REF_AUDIO = 'assets/voices/ref_default.wav'
# must match the transcript of the shipped reference audio exactly —
# zero-shot cloning quality depends on this pairing
DEFAULT_REF_TEXT = '今天过得怎么样呀？我一直在这里等你呢。要是累了的话，就休息一会儿，我陪你聊聊天吧。'

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


class GPTSoVITSProvider(TTSProvider):
    name = 'gptsovits'
    media_type = 'wav'

    def __init__(self, cfg, transport=None):
        self.base_url = (cfg.get('base_url') or '').strip().rstrip('/') or DEFAULT_BASE_URL
        self.ref_audio = resolve_ref_audio(cfg.get('ref_audio') or DEFAULT_REF_AUDIO)
        self.ref_text = (cfg.get('ref_text') or '').strip() or DEFAULT_REF_TEXT
        self.rate = cfg.get('rate', '+0%')
        self._transport = transport  # httpx.MockTransport for unit tests

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
            async with httpx.AsyncClient(timeout=120.0, transport=self._transport) as client:
                resp = await client.get(url, params=params)
        except httpx.TimeoutException:
            raise ValueError('GPT-SoVITS 合成超时（本地推理较慢，或显存不足导致掉速）')
        except httpx.ConnectError:
            raise ValueError('本地 GPT-SoVITS 服务未启动：请先运行 scripts\\启动GPT-SoVITS.bat，'
                             '等命令行出现 9880 端口监听后再试')
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
