# -*- coding: utf-8 -*-
"""TTS manager: provider registry & dispatch.

To add a new provider in the future:
  1. create tts/xxx_provider.py implementing TTSProvider
  2. add a branch in TTSManager.reload()
  3. set "tts.provider" in config
"""
import logging
from tts.edge_provider import EdgeTTSProvider

logger = logging.getLogger('tts')


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

    async def synthesize(self, text, **kwargs):
        return await self.provider.synthesize(text, **kwargs)
