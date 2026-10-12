# -*- coding: utf-8 -*-
"""TTS manager: provider registry & dispatch.

To add a new provider in the future:
  1. create tts/xxx_provider.py implementing TTSProvider
  2. add a branch in TTSManager.reload()
  3. set "tts.provider" in config
"""
import logging
import re

from tts.edge_provider import EdgeTTSProvider
from tts.azure_provider import AzureTTSProvider

logger = logging.getLogger('tts')

# Emotion-linked speaking rate (percent). Positive = livelier/faster,
# negative = softer/slower. The user's configured volume is never touched.
EMOTION_RATE_DELTA = {
    'happy': 10, 'surprised': 8,
    'sad': -12, 'caring': -8, 'angry': -5, 'shy': -5,
    'neutral': 0,
}


def parse_rate(rate):
    """'+10%' / '-8%' / '+0%' -> int percent (0 on garbage)."""
    m = re.match(r'^([+-]?\d+)%?$', str(rate or '+0%').strip())
    return int(m.group(1)) if m else 0


class TTSManager:
    def __init__(self, config):
        self.config = config
        self.provider = None
        self.provider_name = ''
        self.reload()

    def _voice(self):
        """Voice promoted to provider-agnostic (edge & azure share the same
        zh-CN neural voices); old configs keep tts.edge.voice as fallback."""
        t = self.config.get('tts', {})
        return t.get('voice') or t.get('edge', {}).get('voice', 'zh-CN-XiaoxiaoNeural')

    def _rate(self):
        t = self.config.get('tts', {})
        return t.get('rate') or t.get('edge', {}).get('rate', '+0%')

    def reload(self):
        tts_cfg = self.config.get('tts', {})
        name = tts_cfg.get('provider', 'edge')
        voice, rate = self._voice(), self._rate()
        if name == 'edge':
            ed = dict(tts_cfg.get('edge', {}))
            ed.setdefault('voice', voice)
            ed.setdefault('rate', rate)
            self.provider = EdgeTTSProvider(ed)
        elif name == 'azure':
            az = dict(tts_cfg.get('azure', {}))
            az.setdefault('voice', voice)
            az.setdefault('rate', rate)
            self.provider = AzureTTSProvider(az)
        # elif name == 'openai':  OpenAITTSProvider(tts_cfg.get('openai', {}))
        # elif name == 'elevenlabs': ElevenLabsProvider(tts_cfg.get('elevenlabs', {}))
        else:
            raise ValueError(f'未知的 TTS provider: {name}')
        self.provider_name = name
        logger.info('TTS provider = %s (%s)', name, getattr(self.provider, 'voice', ''))

    def rate_for_emotion(self, emotion):
        """Config base rate plus the emotion delta, clamped to ±50%."""
        base = parse_rate(self._rate())
        delta = EMOTION_RATE_DELTA.get(str(emotion or '').lower().strip(), 0)
        return f'{max(-50, min(50, base + delta)):+d}%'

    async def synthesize(self, text, emotion=None, **kwargs):
        # emotion-linked speaking rate (happy livelier, sad/caring softer);
        # `emotion` itself is forwarded for providers that use it (azure
        # maps it to an express-as style), others simply ignore the kwarg
        if emotion:
            kwargs.setdefault('emotion', emotion)
            if EMOTION_RATE_DELTA.get(str(emotion).lower().strip(), 0):
                kwargs.setdefault('rate', self.rate_for_emotion(emotion))
        return await self.provider.synthesize(text, **kwargs)
