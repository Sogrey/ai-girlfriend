# -*- coding: utf-8 -*-
"""TTS manager: provider registry & dispatch.

To add a new provider in the future:
  1. create tts/xxx_provider.py implementing TTSProvider
  2. add a branch in TTSManager.reload()
  3. set "tts.provider" in config
"""
import logging
import re
import time

from tts.edge_provider import EdgeTTSProvider
from tts.azure_provider import AzureTTSProvider
from tts.openai_provider import OpenAITTSProvider

logger = logging.getLogger('tts')


class TTSSilentError(RuntimeError):
    """Raised by the circuit breaker when fast-failing: the provider is
    known-bad in the current window, so no real attempt was made. The
    server never surfaces these as error bubbles — the one-per-streak
    alert was already shown when the breaker tripped (or the streak is a
    leftover from a previous turn; recovery probing happens naturally
    once the window expires)."""

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
    # circuit breaker: after FAIL_STREAK_TRIP consecutive failures the
    # breaker opens for TRIP_SECONDS — synth calls fail fast (no per-
    # sentence network handshake delay) and are silent. The window expiry
    # lets the next call probe for recovery; a success resets everything.
    # Motivation: Edge-TTS 403 outage (10-12) made every sentence of every
    # turn pop an error bubble and waste ~3s each on doomed handshakes.
    FAIL_STREAK_TRIP = 2
    TRIP_SECONDS = 60

    def __init__(self, config):
        self.config = config
        self.provider = None
        self.provider_name = ''
        self._fail_streak = 0
        self._trip_until = 0.0
        self.reload()

    def _reset_breaker(self):
        self._fail_streak = 0
        self._trip_until = 0.0

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
        elif name == 'openai':
            oi = dict(tts_cfg.get('openai', {}))
            # openai has its OWN voice set (alloy/nova/...), NOT the shared
            # zh-CN neural voices — never adopt the promoted tts.voice;
            # only the speaking rate carries over ('+10%' -> 1.1 speed)
            oi.setdefault('rate', rate)
            self.provider = OpenAITTSProvider(oi)
        # elif name == 'elevenlabs': ElevenLabsProvider(tts_cfg.get('elevenlabs', {}))
        else:
            raise ValueError(f'未知的 TTS provider: {name}')
        self.provider_name = name
        self._reset_breaker()   # fresh provider: give it a clean slate
        logger.info('TTS provider = %s (%s)', name, getattr(self.provider, 'voice', ''))

    def rate_for_emotion(self, emotion):
        """Config base rate plus the emotion delta, clamped to ±50%."""
        base = parse_rate(self._rate())
        delta = EMOTION_RATE_DELTA.get(str(emotion or '').lower().strip(), 0)
        return f'{max(-50, min(50, base + delta)):+d}%'

    @property
    def error_alert_allowed(self):
        """One user-facing alert per failure streak: only the FIRST failure
        of a fresh streak (count resets on any success) bubbles to the UI;
        every later failure of the same streak stays silent until the
        service actually recovers."""
        return self._fail_streak == 1

    async def synthesize(self, text, emotion=None, **kwargs):
        # circuit breaker open: fail fast, no attempt, no latency
        if time.monotonic() < self._trip_until:
            raise TTSSilentError('语音服务暂时不可用（自动重试中，稍后自动恢复）')
        # emotion-linked speaking rate (happy livelier, sad/caring softer);
        # `emotion` itself is forwarded for providers that use it (azure
        # maps it to an express-as style), others simply ignore the kwarg
        if emotion:
            kwargs.setdefault('emotion', emotion)
            if EMOTION_RATE_DELTA.get(str(emotion).lower().strip(), 0):
                kwargs.setdefault('rate', self.rate_for_emotion(emotion))
        try:
            data = await self.provider.synthesize(text, **kwargs)
        except Exception:
            self._fail_streak += 1
            if self._fail_streak >= self.FAIL_STREAK_TRIP:
                self._trip_until = time.monotonic() + self.TRIP_SECONDS
                logger.warning('TTS breaker OPEN after %d consecutive failures '
                               '(fast-fail %.0fs, one-time alert already shown)',
                               self._fail_streak, self.TRIP_SECONDS)
            raise
        self._fail_streak = 0
        self._trip_until = 0.0
        return data
