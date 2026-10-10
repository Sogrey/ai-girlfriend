# -*- coding: utf-8 -*-
"""LLM manager: picks provider from config, supports hot reload."""
from llm.deepseek_client import DeepSeekClient
from llm.ollama_client import OllamaClient


class LLMManager:
    def __init__(self, config):
        self.config = config
        self.provider = None
        self.provider_name = ''
        self.reload()

    def reload(self):
        llm_cfg = self.config.get('llm', {})
        name = llm_cfg.get('provider', 'deepseek')
        if name == 'deepseek':
            self.provider = DeepSeekClient(llm_cfg.get('deepseek', {}))
        elif name == 'ollama':
            self.provider = OllamaClient(llm_cfg.get('ollama', {}))
        else:
            raise ValueError(f'未知的 LLM provider: {name}（支持 deepseek / ollama）')
        self.provider_name = name

    async def chat(self, messages, system_prompt, use_json_format=True):
        try:
            return await self.provider.chat(messages, system_prompt, use_json_format=use_json_format)
        except TypeError:
            # provider doesn't support the flag (e.g. ollama) - plain call
            return await self.provider.chat(messages, system_prompt)

    async def chat_stream(self, messages, system_prompt, on_delta=None, use_json_format=True):
        """Streamed chat; providers without streaming fall back to chat().
        use_json_format is passed through when the provider supports it
        (deepseek); older 3-arg providers (ollama/base) fall back via
        TypeError, same pattern as chat()."""
        try:
            return await self.provider.chat_stream(messages, system_prompt, on_delta,
                                                    use_json_format=use_json_format)
        except TypeError:
            # provider doesn't support the flag (e.g. ollama) - plain call
            return await self.provider.chat_stream(messages, system_prompt, on_delta)

    async def health_check(self):
        try:
            return await self.provider.health_check()
        except TypeError:
            return self.provider.health_check()
        except Exception as e:
            return False, str(e)
