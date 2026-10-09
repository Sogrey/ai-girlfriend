"""Long-term memory store: facts the girlfriend remembers across sessions.

Design notes (stage 1, embedding-free):
- Extraction rides the MAIN chat call: the LLM's JSON reply may carry a
  "memories" array (see system_prompt). Zero extra API calls.
- Dedup: identical (normalized) facts bump score+ts; a new fact that contains
  an existing one (or vice versa) is treated as the same topic and skipped.
- Recall: char-bigram overlap with the current user message, blended with
  fact score and recency. Core facts (highest score) ride every turn.
- Storage: config/memory.json (git-ignored), atomic writes via .tmp replace.
"""

import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEMORY_PATH = os.path.join(ROOT, 'config', 'memory.json')

FACTS_MAX = 100      # hard cap on stored facts
FACT_MIN_LEN = 4     # ignore ultra-short extractions like "嗯"
FACT_MAX_LEN = 120   # hard truncation


def _normalize(s):
    """Lowercase, strip whitespace/punctuation variants for comparison."""
    return re.sub(r'[\s，。！？、；：""（）\[\]{},.!?;:\'`~]+', '', str(s)).lower()


def _bigrams(s):
    n = _normalize(s)
    if len(n) < 2:
        return {n} if n else set()
    return {n[i:i + 2] for i in range(len(n) - 1)}


class MemoryStore:
    def __init__(self, config=None):
        self.facts = []  # [{"text": str, "ts": int, "score": int}]
        self._load()

    # ---------- persistence ----------
    def _load(self):
        try:
            with open(MEMORY_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            rows = data.get('facts') if isinstance(data, dict) else data
            if isinstance(rows, list):
                self.facts = [
                    {'text': r['text'], 'ts': int(r.get('ts', 0)), 'score': int(r.get('score', 1))}
                    for r in rows
                    if isinstance(r, dict) and r.get('text')
                ]
                logger.info('memory loaded: %d facts', len(self.facts))
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning('cannot load memory: %s', e)

    def _save(self):
        try:
            tmp = MEMORY_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'facts': self.facts}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, MEMORY_PATH)
        except Exception as e:
            logger.warning('cannot save memory: %s', e)

    # ---------- write path ----------
    def add(self, facts):
        """Add extracted facts (strings). Returns the number actually added."""
        added = 0
        now = int(time.time())
        for raw in facts or []:
            if not isinstance(raw, str):
                continue
            text = raw.strip()[:FACT_MAX_LEN]
            if len(_normalize(text)) < FACT_MIN_LEN:
                continue
            norm = _normalize(text)
            same = None
            for f in self.facts:
                fn = _normalize(f['text'])
                if norm == fn or norm in fn or fn in norm:
                    same = f
                    break
            if same is not None:
                # repeated mention: reinforce instead of duplicating
                same['score'] = int(same.get('score', 1)) + 1
                same['ts'] = now
                continue
            self.facts.append({'text': text, 'ts': now, 'score': 1})
            added += 1
        if added:
            self.compact()
        self._save()
        return added

    def compact(self):
        """Cap the fact count, dropping lowest-score & oldest first."""
        if len(self.facts) <= FACTS_MAX:
            return
        self.facts.sort(key=lambda f: (-f.get('score', 1), -f.get('ts', 0)))
        self.facts = self.facts[:FACTS_MAX]

    # ---------- read path ----------
    def core(self, k=3):
        """Highest-score facts — identity-level memories that ride every turn."""
        if not self.facts:
            return []
        ranked = sorted(self.facts, key=lambda f: (-f.get('score', 1), -f.get('ts', 0)))
        return [f['text'] for f in ranked[:k]]

    def recall(self, query, k=6):
        """Facts relevant to the current message: bigram overlap + score/recency."""
        if not self.facts or not query:
            return []
        qg = _bigrams(query)
        scored = []
        now = time.time()
        for f in self.facts:
            overlap = len(qg & _bigrams(f['text']))
            recency = max(0.0, 1.0 - (now - f.get('ts', 0)) / (86400 * 14))  # 2-week decay
            s = overlap * 3 + f.get('score', 1) + recency
            if overlap > 0:
                scored.append((s, overlap, f))
        scored.sort(key=lambda t: -t[0])
        picked = [t[2]['text'] for t in scored[:k] if t[1] > 0]
        if len(picked) < k:
            # pad with the most recent facts so context stays warm
            seen = {_normalize(p) for p in picked}
            for f in sorted(self.facts, key=lambda x: -x.get('ts', 0)):
                if len(picked) >= k:
                    break
                if _normalize(f['text']) not in seen:
                    picked.append(f['text'])
                    seen.add(_normalize(f['text']))
        return picked[:k]

    def prompt_block(self, query):
        """Build the [长期记忆] injection text for the system prompt."""
        lines = []
        for t in self.core(3):
            lines.append(t)
        for t in self.recall(query, 6):
            if t not in lines:
                lines.append(t)
        if not lines:
            return ''
        body = '\n'.join('- ' + l for l in lines[:8])
        return ('\n\n## 关于用户的长期记忆（跨会话记住的事实，回应时可自然利用，不要生硬背诵）\n'
                + body)

    # ---------- misc ----------
    def clear(self):
        self.facts = []
        try:
            if os.path.exists(MEMORY_PATH):
                os.remove(MEMORY_PATH)
        except Exception as e:
            logger.warning('cannot remove memory file: %s', e)

    def to_list(self):
        return [{'text': f['text'], 'ts': f.get('ts'), 'score': f.get('score', 1)}
                for f in sorted(self.facts, key=lambda x: -x.get('score', 1))]
