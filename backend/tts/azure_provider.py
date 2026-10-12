# -*- coding: utf-8 -*-
"""Azure Speech TTS provider (official REST endpoint).

Why REST instead of the Speech SDK: the project already ships httpx
(async), the v1 endpoint is a single POST that returns mp3 straight away,
and the SDK is a heavyweight wheel (~100MB with native libs) we don't
want inside the venv. Voices are the SAME zh-CN neural voices as edge-tts
(XiaoxiaoNeural & friends), so the user's voice choice carries over.

Endpoint: POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1
Auth: Ocp-Apim-Subscription-Key (Speech resource key from Azure portal)
Body: SSML with prosody rate/volume (same '+10%' format as edge-tts) and
optional mstts:express-as emotion style on voices that support it.
"""
import logging

import httpx

from tts.base import TTSProvider

logger = logging.getLogger('tts.azure')

DEFAULT_VOICE = 'zh-CN-XiaoxiaoNeural'
DEFAULT_REGION = 'eastasia'

# Emotion -> mstts:express-as style. Only a subset of voices supports
# styles (Xiaoxiao does); a 400 with a style falls back to plain prosody.
EMOTION_STYLE = {
    'happy': 'cheerful',
    'surprised': 'excited',
    'sad': 'sad',
    'angry': 'angry',
    'caring': 'affectionate',
    'shy': 'gentle',
}


def build_ssml(text, voice, rate, volume, style=None):
    """SSML for the v1 endpoint. Escapes text; style only when given."""
    esc = (str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
    inner = esc
    if style:
        inner = f'<mstts:express-as style="{style}">{esc}</mstts:express-as>'
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="zh-CN">'
        f'<voice name="{voice}">'
        f'<prosody rate="{rate}" volume="{volume}">{inner}</prosody>'
        '</voice></speak>'
    )


class AzureTTSProvider(TTSProvider):
    name = 'azure'

    def __init__(self, cfg, transport=None):
        self.subscription_key = (cfg.get('subscription_key') or '').strip()
        self.region = (cfg.get('region') or DEFAULT_REGION).strip()
        self.voice = cfg.get('voice', DEFAULT_VOICE)
        self.rate = cfg.get('rate', '+0%')
        self.volume = cfg.get('volume', '+0%')
        self._transport = transport  # httpx.MockTransport for unit tests

    async def _request(self, ssml):
        """POST SSML -> (status_code, audio_bytes_or_error_text)."""
        if not self.subscription_key:
            raise ValueError('Azure TTS 未配置订阅密钥：请点击底部工具栏 ⚙️ 设置 → 语音合成 → 服务选 Azure，'
                             '填入语音服务的密钥（Azure 门户创建"语音服务"资源后获取 Key）')
        url = f'https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1'
        headers = {
            'Ocp-Apim-Subscription-Key': self.subscription_key,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-24khz-48kbitrate-mono-mp3',
            'User-Agent': 'desktop-ai-girlfriend',
        }
        try:
            async with httpx.AsyncClient(timeout=20.0, transport=self._transport) as client:
                resp = await client.post(url, content=ssml, headers=headers)
        except httpx.TimeoutException:
            raise ValueError('Azure TTS 请求超时，请检查网络或区域设置')
        except httpx.ConnectError:
            raise ValueError('无法连接 Azure TTS，请检查网络')
        if resp.status_code in (401, 403):
            raise ValueError(f'Azure TTS 密钥无效（{resp.status_code}），请检查设置面板中的订阅密钥与区域')
        return resp.status_code, resp.content

    async def synthesize(self, text, **kwargs):
        voice = kwargs.get('voice', self.voice)
        rate = kwargs.get('rate', self.rate)
        volume = kwargs.get('volume', self.volume)
        style = EMOTION_STYLE.get(str(kwargs.get('emotion') or '').lower().strip())
        if style:
            # styles are voice-dependent: try styled first, fall back to
            # plain prosody when the voice doesn't support the style
            code, content = await self._request(build_ssml(text, voice, rate, volume, style))
            if code == 400:
                logger.info('azure style %r rejected on %s, retrying without style', style, voice)
                code, content = await self._request(build_ssml(text, voice, rate, volume, None))
        else:
            code, content = await self._request(build_ssml(text, voice, rate, volume, None))
        if code != 200:
            try:
                detail = content.decode('utf-8', 'replace')[:150]
            except Exception:
                detail = ''
            raise ValueError(f'Azure TTS 错误 ({code}): {detail}')
        if not content:
            raise ValueError('TTS 返回空音频')
        return content

    async def list_voices(self):
        """Voice list from the same Speech resource; static zh-CN fallback
        mirrors what the settings panel offers (both providers share them)."""
        if not self.subscription_key:
            return [DEFAULT_VOICE]
        url = f'https://{self.region}.tts.speech.microsoft.com/cognitiveservices/voices/list'
        headers = {'Ocp-Apim-Subscription-Key': self.subscription_key}
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                names = [v['ShortName'] for v in resp.json() if str(v.get('ShortName', '')).startswith('zh-')]
                return names or [DEFAULT_VOICE]
        except Exception as e:
            logger.warning('azure voice list failed (ignored): %s', e)
        return [DEFAULT_VOICE]
