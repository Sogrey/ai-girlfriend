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

    async def chat(self, messages, system_prompt):
        return await self.provider.chat(messages, system_prompt)

    async def health_check(self):
        try:
            return await self.provider.health_check()
        except TypeError:
            return self.provider.health_check()
        except Exception as e:
            return False, str(e)
