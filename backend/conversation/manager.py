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
        style; the final parse below produces the structured result.
        Empty replies (reasoning ate the whole token budget, API hiccup) get
        one silent retry, then a graceful fallback line — never a blank bubble."""
        self.history.append({'role': 'user', 'content': user_text})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history:]
        raw = await self.llm.chat_stream(self.history, self.system_prompt, on_delta)
        data = extract_json(raw)
        result = validate(data, raw)
        if not result['reply']:
            logger.warning('LLM-stream returned empty reply (raw=%r), retrying without json mode', raw[:80])
            try:
                # DeepSeek's json_object mode intermittently returns a
                # whitespace-only content (reasoning fine, content blank).
                # Retrying WITHOUT response_format forces a different path.
                raw = await self.llm.chat(self.history, self.system_prompt, use_json_format=False)
                data = extract_json(raw)
                result = validate(data, raw)
            except Exception as e:
                logger.error('empty-reply retry failed: %s', e)
        if not result['reply']:
            # still empty after retry — graceful fallback so the UI never
            # shows a blank bubble
            logger.warning('LLM reply still empty after retry, using fallback line')
            result = dict(result)
            result['reply'] = '呀……我刚才走神了，再说一次好不好？'
            if result['emotion'] == 'neutral':
                result['emotion'] = 'shy'
        logger.info('LLM-stream(%s) -> emotion=%s action=%s costume=%s reply=%r',
                    source, result['emotion'], result['action'], result['costume'], result['reply'][:60])
        self.history.append({'role': 'assistant', 'content': result['reply']})
        return result
