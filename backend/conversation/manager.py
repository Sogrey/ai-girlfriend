# -*- coding: utf-8 -*-
"""Conversation manager: unified pipeline for text & voice chat."""
import logging
from actions.definitions import extract_json, validate

logger = logging.getLogger('conv')


class ConversationManager:
    def __init__(self, config, llm_manager, system_prompt):
        self.config = config
        self.llm = llm_manager
        self.system_prompt = system_prompt
        self.history = []

    @property
    def max_history(self):
        return int(self.config.get('llm', {}).get('max_history', 12))

    def reload(self, config, system_prompt):
        self.config = config
        self.system_prompt = system_prompt

    def clear(self):
        self.history = []

    async def chat(self, user_text, source='text'):
        """
        Full pipeline: user text -> LLM -> validated response dict.
        History keeps last `max_history` entries.
        """
        self.history.append({'role': 'user', 'content': user_text})
        # keep memory bounded
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history:]
        raw = await self.llm.chat(self.history, self.system_prompt)
        data = extract_json(raw)
        result = validate(data, raw)
        logger.info('LLM(%s) -> emotion=%s action=%s costume=%s reply=%r',
                    source, result['emotion'], result['action'], result['costume'], result['reply'][:60])
        self.history.append({'role': 'assistant', 'content': result['reply']})
        return result

    async def chat_stream(self, user_text, source='text', on_delta=None):
        """Streaming chat: on_delta(partial_raw) fires as raw chunks arrive.
        The raw text is JSON (system prompt) so the UI shows it typewriter-
        style; the final parse below produces the structured result."""
        self.history.append({'role': 'user', 'content': user_text})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history:]
        raw = await self.llm.chat_stream(self.history, self.system_prompt, on_delta)
        data = extract_json(raw)
        result = validate(data, raw)
        logger.info('LLM-stream(%s) -> emotion=%s action=%s costume=%s reply=%r',
                    source, result['emotion'], result['action'], result['costume'], result['reply'][:60])
        self.history.append({'role': 'assistant', 'content': result['reply']})
        return result
