# -*- coding: utf-8 -*-
"""LLM provider abstraction.
Providers implement `chat(messages, system_prompt)` and may also implement
`chat_stream(messages, system_prompt, on_delta)` for token-by-token streaming
(on_delta(partial_text) is called as content arrives)."""


class LLMProvider:
    name = 'base'

    async def chat(self, messages, system_prompt):
        """messages: [{'role','content'}, ...]; returns raw string content."""
        raise NotImplementedError

    async def chat_stream(self, messages, system_prompt, on_delta=None):
        """Default: no streaming support - fallback to plain chat()."""
        content = await self.chat(messages, system_prompt)
        if on_delta:
            on_delta(content)
        return content

    def health_check(self):
        """Return (ok, message)."""
        return True, 'ok'
