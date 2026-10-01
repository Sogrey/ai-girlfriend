# -*- coding: utf-8 -*-
"""Local Ollama client (optional offline provider)."""
import httpx
from llm.base import LLMProvider


class OllamaClient(LLMProvider):
    name = 'ollama'

    def __init__(self, cfg):
        self.base_url = (cfg.get('base_url') or 'http://127.0.0.1:11434').rstrip('/')
        self.model = cfg.get('model', 'qwen3:4b')
        self.temperature = float(cfg.get('temperature', 0.8))
        self.num_ctx = int(cfg.get('num_ctx', 8192))
        self.timeout = float(cfg.get('timeout_seconds', 180))

    async def chat(self, messages, system_prompt):
        payload = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
            'stream': False,
            'format': 'json',
            'options': {
                'temperature': self.temperature,
                'num_ctx': self.num_ctx,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f'{self.base_url}/api/chat', json=payload)
        except httpx.TimeoutException:
            raise ValueError(f'Ollama 请求超时（{self.timeout}s），模型可能太大')
        except httpx.ConnectError:
            raise ValueError('无法连接 Ollama（127.0.0.1:11434），请确认 Ollama 已启动')
        if resp.status_code == 404:
            raise ValueError(f'Ollama 模型不存在：{self.model}，请执行 ollama pull {self.model}')
        if resp.status_code != 200:
            raise ValueError(f'Ollama API 错误 ({resp.status_code}): {resp.text[:200]}')
        data = resp.json()
        return data.get('message', {}).get('content', '')

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f'{self.base_url}/api/tags')
                models = [m['name'] for m in r.json().get('models', [])]
                if not any(m.startswith(self.model) for m in models):
                    return False, f'模型未安装: {self.model}（可用: {", ".join(models[:5])}）'
                return True, 'ok'
        except Exception:
            return False, 'Ollama 未运行'
