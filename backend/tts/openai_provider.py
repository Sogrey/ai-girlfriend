# -*- coding: utf-8 -*-
"""OpenAI TTS provider (official /v1/audio/speech endpoint).

Key differences vs the azure/edge providers:
- Voice set is OpenAI's own (alloy/echo/fable/onyx/nova/shimmer), NOT the
  shared zh-CN neural voices — the provider never adopts the promoted
  tts.voice; it has its own config key (tts.openai.voice).
- Speaking rate is a float `speed` (0.25..4.0), not SSML percent — the
  app-wide '+10%' rate is converted to a 1.1 multiplier.
- Only the gpt-4o-mini-tts model accepts `instructions` (style control);
  the classic tts-1 / tts-1-hd ignore emotion and rely on speed alone.
- base_url is configurable so reverse proxies / relays work out of the
  box (direct api.openai.com is not reliably reachable from some regions).

Zero new dependencies: httpx again.
"""
import logging

import httpx

from tts.base import TTSProvider

logger = logging.getLogger('tts.openai')

DEFAULT_MODEL = 'tts-1'
DEFAULT_VOICE = 'nova'
DEFAULT_BASE_URL = 'https://api.openai.com/v1'

# Emotion -> style instruction for gpt-4o-mini-tts (English instructions
# are followed best). Classic tts-1/tts-1-hd have no such parameter and
# simply skip this.
EMOTION_INSTRUCTIONS = {
    'happy': 'Speak in a cheerful, upbeat and lively tone.',
    'surprised': 'Speak in an excited, amazed tone.',
    'sad': 'Speak gently with a soft, sorrowful tone.',
    'angry': 'Speak with an irritated, firm tone.',
    'caring': 'Speak warmly with an affectionate, caring tone.',
    'shy': 'Speak softly with a timid, bashful tone.',
}


def rate_to_speed(rate):
    """'+10%' / '-8%' (edge-style percent) -> float speed multiplier,
    clamped to the API's 0.25..4.0 range. Garbage input -> 1.0."""
    s = str(rate or '+0%').strip().replace('%', '')
    try:
        val = float(s)
    except (TypeError, ValueError):
        val = 0.0
    return max(0.25, min(4.0, 1.0 + val / 100.0))


class OpenAITTSProvider(TTSProvider):
    name = 'openai'

    def __init__(self, cfg, transport=None):
        self.api_key = (cfg.get('api_key') or '').strip()
        self.base_url = (cfg.get('base_url') or '').strip().rstrip('/') or DEFAULT_BASE_URL
        self.model = cfg.get('model') or DEFAULT_MODEL
        self.voice = cfg.get('voice') or DEFAULT_VOICE
        self.rate = cfg.get('rate', '+0%')
        self._transport = transport  # httpx.MockTransport for unit tests

    async def synthesize(self, text, **kwargs):
        if not self.api_key:
            raise ValueError('OpenAI TTS 未配置 API Key：请点击底部工具栏 ⚙️ 设置 → 语音合成 → 服务选 OpenAI，'
                             '填入 API Key（platform.openai.com 获取）；国内网络需在接口地址填中转服务地址')
        voice = kwargs.get('voice') or self.voice
        speed = rate_to_speed(kwargs.get('rate', self.rate))
        payload = {
            'model': self.model,
            'input': str(text),
            'voice': voice,
            'response_format': 'mp3',
            'speed': speed,
        }
        if self.model == 'gpt-4o-mini-tts':
            instruction = EMOTION_INSTRUCTIONS.get(str(kwargs.get('emotion') or '').lower().strip())
            if instruction:
                payload['instructions'] = instruction
        url = f'{self.base_url}/audio/speech'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise ValueError('OpenAI TTS 请求超时，请检查网络或中转接口地址')
        except httpx.ConnectError:
            raise ValueError('无法连接 OpenAI TTS，请检查网络（国内需配置中转接口地址）')
        if resp.status_code in (401, 403):
            raise ValueError(f'OpenAI API Key 无效（{resp.status_code}），请检查设置面板中的 Key 与接口地址')
        if resp.status_code != 200:
            try:
                detail = resp.json().get('error', {}).get('message', '')[:150]
            except Exception:
                detail = resp.text[:150] if resp.text else ''
            raise ValueError(f'OpenAI TTS 错误 ({resp.status_code}): {detail}')
        if not resp.content:
            raise ValueError('TTS 返回空音频')
        return resp.content

    async def list_voices(self):
        """The six classic voices — available on every TTS model (the newer
        coral/ballad/... only work on gpt-4o-mini-tts, so we stick to the
        safe six to keep any model/voice combination valid)."""
        return ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer']
