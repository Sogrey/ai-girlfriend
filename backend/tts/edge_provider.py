# -*- coding: utf-8 -*-
"""Edge-TTS provider (Microsoft Edge online TTS, free)."""
import io
import logging
import edge_tts
from tts.base import TTSProvider

logger = logging.getLogger('tts.edge')

DEFAULT_VOICE = 'zh-CN-XiaoxiaoNeural'


class EdgeTTSProvider(TTSProvider):
    name = 'edge'

    def __init__(self, cfg):
        self.voice = cfg.get('voice', DEFAULT_VOICE)
        self.rate = cfg.get('rate', '+0%')
        self.volume = cfg.get('volume', '+0%')

    async def synthesize(self, text, **kwargs):
        voice = kwargs.get('voice', self.voice)
        rate = kwargs.get('rate', self.rate)
        volume = kwargs.get('volume', self.volume)
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk['type'] == 'audio':
                    buf.write(chunk['data'])
            data = buf.getvalue()
            if not data:
                raise ValueError('TTS 返回空音频')
            return data
        except Exception as e:
            msg = str(e)
            if '401' in msg or 'Unauthorized' in msg or '403' in msg:
                raise ValueError(f'Edge-TTS 鉴权失败，可稍后重试或更换音色: {msg[:120]}')
            logger.warning('edge-tts primary voice failed (%s), retry with default voice', msg[:80])
            if voice != DEFAULT_VOICE:
                communicate = edge_tts.Communicate(text, DEFAULT_VOICE, rate=rate, volume=volume)
                buf = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk['type'] == 'audio':
                        buf.write(chunk['data'])
                return buf.getvalue()
            raise

    async def list_voices(self):
        try:
            voices = await edge_tts.list_voices()
            return [v['ShortName'] for v in voices if v['ShortName'].startswith('zh-')]
        except Exception:
            return []
