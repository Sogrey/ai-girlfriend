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

    def reload(self):
        tts_cfg = self.config.get('tts', {})
        name = tts_cfg.get('provider', 'edge')
        if name == 'edge':
            self.provider = EdgeTTSProvider(tts_cfg.get('edge', {}))
        # elif name == 'azure':   AzureTTSProvider(tts_cfg.get('azure', {}))
        # elif name == 'openai':  OpenAITTSProvider(tts_cfg.get('openai', {}))
        # elif name == 'elevenlabs': ElevenLabsProvider(tts_cfg.get('elevenlabs', {}))
        else:
            raise ValueError(f'未知的 TTS provider: {name}')
        self.provider_name = name
        logger.info('TTS provider = %s (%s)', name, getattr(self.provider, 'voice', ''))

    def rate_for_emotion(self, emotion):
        """Config base rate plus the emotion delta, clamped to ±50%."""
        base = parse_rate(self.config.get('tts', {}).get('edge', {}).get('rate', '+0%'))
        delta = EMOTION_RATE_DELTA.get(str(emotion or '').lower().strip(), 0)
        return f'{max(-50, min(50, base + delta)):+d}%'

    async def synthesize(self, text, emotion=None, **kwargs):
        # emotion-linked speaking rate (happy livelier, sad/caring softer);
        # providers that don't consume `rate` simply ignore the kwarg
        if emotion and EMOTION_RATE_DELTA.get(str(emotion).lower().strip(), 0):
            kwargs.setdefault('rate', self.rate_for_emotion(emotion))
        return await self.provider.synthesize(text, **kwargs)
