# -*- coding: utf-8 -*-
"""TTS provider abstraction.

Future providers (azure / openai / elevenlabs / local) just implement
`synthesize(text, **kwargs) -> bytes(mp3)` and register in tts/manager.py.
"""


class TTSProvider:
    name = 'base'

    async def synthesize(self, text, **kwargs):
        """Returns raw audio bytes (mp3)."""
        raise NotImplementedError

    async def list_voices(self):
        return []
