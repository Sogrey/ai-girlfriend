# -*- coding: utf-8 -*-
"""Conversation manager: unified pipeline for text & voice chat.
Chat history persists to config/history.jsonl (append-only) so she remembers
conversations across restarts."""
import json
import logging
import os
import time
from actions.definitions import extract_json, validate
from conversation.memory import MemoryStore

logger = logging.getLogger('conv')

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HISTORY_PATH = os.path.join(ROOT, 'config', 'history.jsonl')


class ConversationManager:
    def __init__(self, config, llm_manager, system_prompt):
        self.config = config
        self.llm = llm_manager
        self.system_prompt = system_prompt
        self.history = []
        self.memory = MemoryStore(config)
        self._restore_history()

    # ---------- persistence ----------

    # history.jsonl is append-only; compact it on boot so the file cannot
    # grow forever (months of chatting would otherwise bloat it endlessly).
    FILE_KEEP = 400  # rows kept when compacting on startup

    def _restore_history(self):
        """Load the tail of history.jsonl so she remembers prior talks.
        Keeps the last `max_history` user+assistant turns for context.
        If the file exceeds FILE_KEEP rows it is compacted in place."""
        try:
            rows = []
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(r, dict) and r.get('role') in ('user', 'assistant') and r.get('content'):
                        rows.append({'role': r['role'], 'content': r['content']})
            if len(rows) > self.FILE_KEEP:
                try:
                    tmp = HISTORY_PATH + '.tmp'
                    with open(tmp, 'w', encoding='utf-8') as f:
                        for r in rows[-self.FILE_KEEP:]:
                            f.write(json.dumps(r, ensure_ascii=False) + '\n')
                    os.replace(tmp, HISTORY_PATH)
                    logger.info('history.jsonl compacted to last %d rows (was %d)', self.FILE_KEEP, len(rows))
                except Exception as e:
                    logger.warning('cannot compact history file: %s', e)
            keep = self.max_history * 2
            self.history = rows[-keep:] if len(rows) > keep else rows
            if self.history:
                logger.info('restored %d history entries from history.jsonl', len(self.history))
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning('cannot restore history: %s', e)

    def _persist(self, role, content):
        try:
            with open(HISTORY_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'ts': int(time.time()), 'role': role, 'content': content}, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.warning('cannot persist history: %s', e)

    def get_recent_history(self, limit=30):
        """Recent turns for the UI to replay on boot (oldest first)."""
        return self.history[-limit:] if self.history else []

    def clear(self):
        self.history = []
        # also wipe the persisted file
        try:
            if os.path.exists(HISTORY_PATH):
                os.remove(HISTORY_PATH)
        except Exception as e:
            logger.warning('cannot remove history file: %s', e)

    @property
    def max_history(self):
        return int(self.config.get('llm', {}).get('max_history', 12))

    def reload(self, config, system_prompt):
        self.config = config
        self.system_prompt = system_prompt

    def clear(self):
        self.history = []

    def _prompt_with_memory(self, user_text):
        """System prompt + long-term memory injection for this turn."""
        try:
            block = self.memory.prompt_block(user_text)
            if block:
                return self.system_prompt + block
        except Exception as e:
            logger.warning('memory recall failed (ignored): %s', e)
        return self.system_prompt

    def _absorb_memories(self, result):
        """Store the memories the LLM extracted alongside its reply."""
        try:
            mems = result.get('memories') or []
            if mems:
                n = self.memory.add(mems)
                if n:
                    logger.info('memory +%d (total %d)', n, len(self.memory.facts))
        except Exception as e:
            logger.warning('memory absorb failed (ignored): %s', e)

    async def chat(self, user_text, source='text'):
        """
        Full pipeline: user text -> LLM -> validated response dict.
        History keeps last `max_history` entries.
        """
        self.history.append({'role': 'user', 'content': user_text})
        self._persist('user', user_text)
        # keep memory bounded
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history:]
        raw = await self.llm.chat(self.history, self._prompt_with_memory(user_text))
        data = extract_json(raw)
        result = validate(data, raw)
        self._absorb_memories(result)
        logger.info('LLM(%s) -> emotion=%s action=%s costume=%s reply=%r',
                    source, result['emotion'], result['action'], result['costume'], result['reply'][:60])
        self.history.append({'role': 'assistant', 'content': result['reply']})
        self._persist('assistant', result['reply'])
        return result

    async def chat_stream(self, user_text, source='text', on_delta=None):
        """Streaming chat: on_delta(partial_raw) fires as raw chunks arrive.
        The raw text is JSON (system prompt) so the UI shows it typewriter-
        style; the final parse below produces the structured result.
        Empty replies (reasoning ate the whole token budget, API hiccup) get
        one silent retry, then a graceful fallback line — never a blank bubble."""
        self.history.append({'role': 'user', 'content': user_text})
        self._persist('user', user_text)
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history:]
        raw = await self.llm.chat_stream(self.history, self._prompt_with_memory(user_text), on_delta)
        data = extract_json(raw)
        result = validate(data, raw)
        self._absorb_memories(result)
        if not result['reply']:
            logger.warning('LLM-stream returned empty reply (raw=%r), retrying (stream, no json mode)', raw[:80])
            try:
                # DeepSeek's json_object mode intermittently returns a
                # whitespace-only content (reasoning fine, content blank).
                # Retrying WITHOUT response_format forces a different path.
                # The retry is STREAMED and reuses the same on_delta chain,
                # so first-sentence-early TTS also covers retry turns (when
                # the model still emits JSON per the system prompt; a
                # plain-text reply just falls back to the classic flush).
                # The tracker is guaranteed empty here: any reply text seen
                # in the first stream would have made validate()'s raw-text
                # fallback non-empty, so no retry would have happened.
                raw = await self.llm.chat_stream(self.history, self._prompt_with_memory(user_text),
                                                 on_delta, use_json_format=False)
                data = extract_json(raw)
                result = validate(data, raw)
                self._absorb_memories(result)
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
        self._persist('assistant', result['reply'])
        return result
