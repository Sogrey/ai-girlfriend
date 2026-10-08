# -*- coding: utf-8 -*-
"""DeepSeek online API client (OpenAI-compatible chat/completions)."""
import httpx
import json
from llm.base import LLMProvider


class DeepSeekClient(LLMProvider):
    name = 'deepseek'

    def __init__(self, cfg):
        self.api_key = (cfg.get('api_key') or '').strip()
        self.base_url = (cfg.get('base_url') or 'https://api.deepseek.com').rstrip('/')
        self.model = cfg.get('model', 'deepseek-flash')
        self.temperature = float(cfg.get('temperature', 0.8))
        # NOTE: deepseek-flash is a hybrid reasoning model — completion tokens
        # are consumed by the reasoning phase FIRST, then the visible content.
        # 512 starved content to nothing on longer thoughts; 2048 leaves room.
        self.max_tokens = int(cfg.get('max_tokens', 2048))
        self.timeout = float(cfg.get('timeout_seconds', 60))

    async def chat(self, messages, system_prompt, use_json_format=True):
        if not self.api_key:
            raise ValueError('DeepSeek API Key 未设置：请点击底部工具栏 ⚙️ 设置 → AI 大模型 → 填写 API Key（在 https://platform.deepseek.com 获取）')
        payload = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            'stream': False,
        }
        # json_object mode occasionally makes the model emit a whitespace-only
        # content (reasoning ok, content = "   ") - disable it on retries.
        if use_json_format:
            payload['response_format'] = {'type': 'json_object'}
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        url = f'{self.base_url}/chat/completions'
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise ValueError(f'DeepSeek 请求超时（{self.timeout}s）')
        except httpx.ConnectError:
            raise ValueError('无法连接 DeepSeek API，请检查网络')
        if resp.status_code == 401:
            raise ValueError('DeepSeek API Key 无效（401），请检查设置面板中的 Key')
        if resp.status_code == 402:
            raise ValueError('DeepSeek 账户余额不足（402），请充值')
        if resp.status_code == 429:
            raise ValueError('DeepSeek 请求过于频繁（429），请稍后再试')
        if resp.status_code != 200:
            try:
                err = resp.json().get('error', {}).get('message', resp.text[:200])
            except Exception:
                err = resp.text[:200]
            raise ValueError(f'DeepSeek API 错误 ({resp.status_code}): {err}')
        data = resp.json()
        try:
            content = data['choices'][0]['message']['content']
        except Exception:
            raise ValueError('DeepSeek 返回格式异常: ' + json.dumps(data)[:300])
        return content

    async def chat_stream(self, messages, system_prompt, on_delta=None, use_json_format=True):
        """Streaming variant: call on_delta(partial_text) as chunks arrive so
        the UI can show a typewriter effect while she is "thinking"."""
        if not self.api_key:
            raise ValueError('DeepSeek API Key 未设置：请点击底部工具栏 ⚙️ 设置 → AI 大模型 → 填写 API Key（在 https://platform.deepseek.com 获取）')
        payload = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            'stream': True,
        }
        if use_json_format:
            payload['response_format'] = {'type': 'json_object'}
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
        }
        url = f'{self.base_url}/chat/completions'
        try:
            collected = ''
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream('POST', url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode('utf-8', 'replace')[:200]
                        if resp.status_code == 401:
                            raise ValueError('DeepSeek API Key 无效（401），请检查设置面板中的 Key')
                        if resp.status_code == 402:
                            raise ValueError('DeepSeek 账户余额不足（402），请充值')
                        if resp.status_code == 429:
                            raise ValueError('DeepSeek 请求过于频繁（429），请稍后再试')
                        raise ValueError(f'DeepSeek API 错误 ({resp.status_code}): {body}')
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith('data:'):
                            continue
                        data_str = line[5:].strip()
                        if data_str == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data_str)
                        except Exception:
                            continue
                        try:
                            delta = chunk['choices'][0]['delta'].get('content', '')
                        except (KeyError, IndexError):
                            delta = ''
                        if delta:
                            collected += delta
                            if on_delta:
                                try:
                                    on_delta(collected)
                                except Exception:
                                    pass
            return collected
        except httpx.TimeoutException:
            raise ValueError(f'DeepSeek 请求超时（{self.timeout}s）')
        except httpx.ConnectError:
            raise ValueError('无法连接 DeepSeek API，请检查网络')

    def health_check(self):
        if not self.api_key:
            return False, '未设置 API Key'
        return True, 'ok'
