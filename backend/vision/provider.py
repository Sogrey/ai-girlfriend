# -*- coding: utf-8 -*-
"""Vision provider (Phase 38): screen awareness for the AI girlfriend.

One OpenAI-compatible chat-completions call with an attached JPEG that
describes what is currently on the user's screen; the description is then
injected into that turn's LLM context so she can talk about what she "saw".

Default and recommended endpoint: Zhipu's GLM-4V-Flash
(https://open.bigmodel.cn — fully free image-understanding model, the v4
API is OpenAI-compatible), but ANY OpenAI-compatible vision endpoint works
(aggregators, proxies, self-hosted vLLM/sglang).

Config (config/user.json):
    "vision": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "",
        "model": "glm-4v-flash",
        "timeout_seconds": 60
    }

Privacy by design: screen images are ONLY captured on explicit user actions
(the toolbar eye button, or a user phrase that matches the screen-cue
regex in server.py) and go straight to the configured endpoint — never
written to disk, never stored in chat history (only the description text
rides the current turn's system prompt, the history keeps the user's words).
"""
import json
import logging

import httpx

logger = logging.getLogger('vision')

DEFAULT_DESCRIBE_PROMPT = (
    '你看到的是用户当前电脑屏幕的截图。请用中文简洁描述画面内容：'
    '如果有报错弹窗、日志、代码或文档，提取其中最关键的文字（报错码/文件名/一段代码等）；'
    '如果要描述长文本不要逐字抄，抓重点。控制在 150 字以内，直接输出描述正文。'
)


class VisionProvider:
    """OpenAI-compatible vision endpoint wrapper (glm-4v-flash / qwen-vl /
    any compatible relay). Screen perception = describe(image) -> text."""

    def __init__(self, cfg=None, transport=None):
        self.cfg = {}
        self._transport = transport   # httpx transport injection for tests
        self.reload(cfg or {})

    def reload(self, cfg=None):
        if cfg is not None:
            self.cfg = cfg or {}
        self.base_url = str(self.cfg.get('base_url') or 'https://open.bigmodel.cn/api/paas/v4').rstrip('/')
        self.api_key = str(self.cfg.get('api_key') or '').strip()
        self.model = str(self.cfg.get('model') or 'glm-4v-flash').strip()
        self.timeout = float(self.cfg.get('timeout_seconds') or 60)
        self.describe_prompt = str(self.cfg.get('describe_prompt') or DEFAULT_DESCRIBE_PROMPT)

    # ---------- readiness ----------

    @property
    def ready(self):
        """True when an api_key is configured (model/base_url have sane
        defaults). Missing key => the screen flow returns a guidance
        bubble instead of a raw error."""
        return bool(self.api_key)

    def guidance(self):
        return ('屏幕感知还没有配置视觉模型：打开设置 → 视觉模型（屏幕感知），'
                '填入 API Key 即可启用。推荐智谱 GLM-4V-Flash，'
                'open.bigmodel.cn 注册即完全免费。')

    # ---------- core ----------

    async def describe(self, image_b64, question=None):
        """Send one JPEG (base64, no data: prefix) to the vision model and
        return its textual description of the screen."""
        if not self.ready:
            raise RuntimeError(self.guidance())
        if not image_b64:
            raise ValueError('empty screenshot payload')
        prompt = (question or '').strip() or self.describe_prompt
        body = {
            'model': self.model,
            'messages': [{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url',
                     'image_url': {'url': 'data:image/jpeg;base64,' + image_b64}},
                ],
            }],
            'max_tokens': 400,
            'temperature': 0.2,
        }
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            r = await client.post(self.base_url + '/chat/completions',
                                  json=body,
                                  headers={'Authorization': 'Bearer ' + self.api_key})
        if r.status_code != 200:
            raise ValueError('视觉模型返回 %s: %s' % (r.status_code, r.text[:200]))
        try:
            data = r.json()
        except Exception:
            raise ValueError('视觉模型响应不是 JSON: ' + r.text[:200])
        try:
            content = data['choices'][0]['message']['content']
        except Exception:
            raise ValueError('视觉模型响应缺少文本内容: ' + json.dumps(data, ensure_ascii=False)[:200])
        # glm-4v may answer with a thinking field + content; content is text
        text = content or ''
        if isinstance(text, list):  # some endpoints emit content parts
            text = ''.join(str(p.get('text', '') if isinstance(p, dict) else p) for p in text)
        if hasattr(text, 'strip'):
            text = text.strip()
        text = str(text or '').strip()
        if not text:
            raise ValueError('视觉模型返回了空描述')
        logger.info('vision described screen (%d chars)', len(text))
        return text
