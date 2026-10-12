# -*- coding: utf-8 -*-
"""ElevenLabs TTS provider (official /v1/text-to-speech endpoint).

Key differences vs the azure/openai providers:
- Auth is the `xi-api-key` header (not Bearer).
- Speed range is narrow (0.7..1.2) — the app-wide '+10%' rate maps to
  speed 1.1 like openai, but clamped to this band.
- Voices are voice_id based (Rachel/...). The free tier ships a preset
  library; zh support requires the multilingual/flash model families.
- No style/instructions parameter on this endpoint; emotion is expressed
  via the shared speed only (happy livelier / sad slower).
- base_url is configurable for relays (DEFAULT_BASE_URL_TAIL is appended
  so a bare relay host also works).

Zero new dependencies: httpx again.
"""
import logging

import httpx

from tts.base import TTSProvider

logger = logging.getLogger('tts.elevenlabs')

DEFAULT_BASE_URL = 'https://api.elevenlabs.io'
DEFAULT_MODEL = 'eleven_multilingual_v2'   # best zh quality
DEFAULT_VOICE_ID = '21m00Tcm4TlvDq8ikWAM'  # Rachel (preset, free tier)

# Preset library voices (free tier) — value = voice_id, label = name.
PRESET_VOICES = [
    ('21m00Tcm4TlvDq8ikWAM', 'Rachel（女·温柔）'),
    ('EXAVITQu4vr4xnSDxMaL', 'Bella（女·柔和）'),
    ('FGY2WhTYpPnrIDTdsKH5', 'Laura（女·年轻）'),
    ('pNInz6obpgDQGcFmaJgB', 'Adam（男·沉稳）'),
    ('ErXwobaYiN019PkySvjV', 'Antoni（男·亲切）'),
    ('TxGEqnHWrfWFTfGW9XjX', 'Josh（男·浑厚）'),
]
PRESET_VOICE_IDS = [v[0] for v in PRESET_VOICES]


def rate_to_speed(rate):
    """'+10%' (edge-style percent) -> float speed, clamped to the API's
    narrow 0.7..1.2 band. Garbage input -> 1.0."""
    s = str(rate or '+0%').strip().replace('%', '')
    try:
        val = float(s)
    except (TypeError, ValueError):
        val = 0.0
    return max(0.7, min(1.2, 1.0 + val / 100.0))


def normalize_base_url(base_url):
    """Accept a bare relay host (append /v1 if no path) or a full base."""
    u = (base_url or '').strip().rstrip('/')
    if not u:
        return DEFAULT_BASE_URL
    # has a path beyond scheme+host (e.g. .../v1 or custom prefix)?
    from urllib.parse import urlparse
    parsed = urlparse(u)
    if not parsed.path or parsed.path == '/':
        u = u + '/v1'
    return u


class ElevenLabsProvider(TTSProvider):
    name = 'elevenlabs'

    def __init__(self, cfg, transport=None):
        self.api_key = (cfg.get('api_key') or '').strip()
        self.base_url = normalize_base_url(cfg.get('base_url'))
        self.model = cfg.get('model') or DEFAULT_MODEL
        self.voice_id = cfg.get('voice_id') or DEFAULT_VOICE_ID
        self.rate = cfg.get('rate', '+0%')
        self._transport = transport  # httpx.MockTransport for unit tests

    async def synthesize(self, text, **kwargs):
        if not self.api_key:
            raise ValueError('ElevenLabs 未配置 API Key：请点击底部工具栏 ⚙️ 设置 → 语音合成 → 服务选 ElevenLabs，'
                             '填入 API Key（elevenlabs.io 注册后 Personal Info 页获取；免费层每月 1 万字符）')
        voice = kwargs.get('voice_id') or self.voice_id
        speed = rate_to_speed(kwargs.get('rate', self.rate))
        url = f'{self.base_url}/text-to-speech/{voice}'
        payload = {
            'text': str(text),
            'model_id': self.model,
            'voice_settings': {
                'stability': 0.5,
                'similarity_boost': 0.75,
                'use_speaker_boost': True,
                'speed': speed,
            },
        }
        headers = {
            'xi-api-key': self.api_key,
            'Content-Type': 'application/json',
            'Accept': 'audio/mpeg',
        }
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise ValueError('ElevenLabs 请求超时，请检查网络或接口地址')
        except httpx.ConnectError:
            raise ValueError('无法连接 ElevenLabs，请检查网络（可配置中转接口地址）')
        if resp.status_code in (401,):
            raise ValueError('ElevenLabs API Key 无效（401），请检查设置面板中的 Key')
        if resp.status_code == 403:
            raise ValueError('ElevenLabs 拒绝访问（403）——Key 可能无此音色权限或字符额度已用尽')
        if resp.status_code != 200:
            try:
                detail = str(resp.json().get('detail', {}).get('message', ''))[:150]
            except Exception:
                detail = resp.text[:150] if resp.text else ''
            raise ValueError(f'ElevenLabs 错误 ({resp.status_code}): {detail}')
        if not resp.content:
            raise ValueError('TTS 返回空音频')
        return resp.content

    async def list_voices(self):
        """Live voice list from the account when possible; preset fallback
        mirrors what the settings panel offers."""
        if not self.api_key:
            return PRESET_VOICE_IDS
        url = f'{self.base_url}/voices'
        headers = {'xi-api-key': self.api_key}
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                ids = [v['voice_id'] for v in resp.json().get('voices', [])]
                return ids or PRESET_VOICE_IDS
        except Exception as e:
            logger.warning('elevenlabs voice list failed (ignored): %s', e)
        return PRESET_VOICE_IDS
