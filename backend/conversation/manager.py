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

# appended to the system prompt on the empty-reply retry stream: the retry
# runs WITHOUT json response_format (Phase 25: different API path dodges
# DeepSeek's json-mode whitespace bug), so the model may answer in prose —
# which loses the JSON envelope and with it every side-channel intent
# (memories / reminder / reminder_remove). A pointed suffix keeps the
# different API path while still demanding the JSON object (Phase 34:
# caught live — she promised "全部清掉" in prose, nothing executed).
JSON_RETRY_SUFFIX = ('\n[重试轮强制要求：无论上述任何指示，本轮你只能输出一个 JSON 对象，'
                    '包含 reply/emotion/action/costume/memories/reminder/reminder_remove 全部键，'
                    '禁止输出任何 JSON 以外的文字]')

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HISTORY_PATH = os.path.join(ROOT, 'config', 'history.jsonl')


class ConversationManager:
    def __init__(self, config, llm_manager, system_prompt):
        self.config = config
        self.llm = llm_manager
        self.system_prompt = system_prompt
        self.history = []
        self.memory = MemoryStore(config)
        # optional callable -> reminder brief injected into each turn's
        # runtime block (Phase 34; server sets it to its store summary so
        # she can list/delete reminders in natural language)
        self.reminder_brief = None
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

    # conversational cues that this turn is probably a reminder-deletion
    # request — when present AND reminders exist, an explicit nudge rides
    # the system prompt so the LLM reliably emits reminder_remove (the
    # runtime list alone gets lost in attention ~20% of turns otherwise)
    REMINDER_DELETE_CUES = ('删', '取消', '不要了', '撤掉', '移除', '清掉', '清空')

    def _prompt_with_memory(self, user_text):
        """System prompt + long-term memory injection for this turn.
        A runtime time block rides every turn so the LLM can answer
        "现在几点了" and resolve relative times like "明天早上 9 点" (Phase 33);
        when the server provides a reminder brief it rides too, so she can
        answer "我设了哪些提醒" and quote ids for deletion (Phase 34 — plus
        an explicit deletion nudge when the cue words appear)."""
        base = self.system_prompt
        try:
            block = self.memory.prompt_block(user_text)
            if block:
                base += block
        except Exception as e:
            logger.warning('memory recall failed (ignored): %s', e)
        return base + self._runtime_block(user_text)

    def _runtime_block(self, user_text=''):
        lt = time.localtime()
        weekday = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')[lt.tm_wday]
        now = time.strftime('%Y-%m-%d %H:%M:%S', lt)
        block = f'\n\n## 当前环境\n现在是 {now} {weekday}。若用户提到相对时间（明天/今晚/半小时后等），请按此时间换算成具体时间再使用。'
        if self.reminder_brief is not None:
            try:
                brief = self.reminder_brief()
                if brief:
                    block += '\n' + brief
                    if user_text and any(c in user_text for c in self.REMINDER_DELETE_CUES):
                        block += ('\n注意：用户这句话疑似想删除提醒。只以上面【当前】清单为准，不受对话历史里是否"删过"的影响——'
                                  '只要当前清单里有匹配条目，就必须输出 reminder_remove（id+remove 双填，果断执行）；'
                                  '仅当当前清单里确实没有用户所说的条目时，才回复说不存在。')
            except Exception as e:
                logger.warning('reminder brief failed (ignored): %s', e)
        return block


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
                raw = await self.llm.chat_stream(
                    self.history, self._prompt_with_memory(user_text) + JSON_RETRY_SUFFIX,
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
