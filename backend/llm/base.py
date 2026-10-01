# -*- coding: utf-8 -*-
"""LLM provider abstraction. All providers implement `chat(messages, system_prompt)`."""


class LLMProvider:
    name = 'base'

    async def chat(self, messages, system_prompt):
        """messages: [{'role','content'}, ...]; returns raw string content."""
        raise NotImplementedError

    def health_check(self):
        """Return (ok, message)."""
        return True, 'ok'
