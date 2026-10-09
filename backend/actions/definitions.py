# -*- coding: utf-8 -*-
"""Valid action/emotion/costume enums shared between LLM output and renderer."""
import json
import re

VALID_ACTIONS = {
    'idle', 'wave', 'leave', 'return', 'change_costume', 'comfort',
    'head_pat', 'jump', 'dance', 'think',
}
VALID_EMOTIONS = {'happy', 'shy', 'angry', 'sad', 'surprised', 'caring', 'neutral'}
VALID_COSTUMES = {'casual', 'school', 'stylish', 'gothic', 'seed'}

# long-term memory extraction caps
MEMORY_MAX_ITEMS = 5
MEMORY_MAX_LEN = 120

# maps some natural words the LLM may emit to canonical actions
ACTION_ALIASES = {
    'pat': 'head_pat', 'headpat': 'head_pat', 'happy': 'wave',
    'greet': 'wave', 'goodbye': 'leave', 'sleep': 'leave', 'rest': 'leave',
    'comeback': 'return', 'come_back': 'return', 'costume': 'change_costume',
    'changecostume': 'change_costume', 'cheer': 'jump',
}
EMOTION_ALIASES = {
    'joy': 'happy', 'excited': 'happy', 'love': 'happy', 'embarrassed': 'shy',
    'blush': 'shy', 'mad': 'angry', 'upset': 'sad', 'worry': 'sad',
    'shock': 'surprised', 'amazed': 'surprised', 'gentle': 'caring', 'care': 'caring',
}


def extract_json(raw):
    """Best-effort JSON extraction from an LLM response."""
    if not raw:
        return {}
    raw = raw.strip()
    # strip code fences
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if m:
        raw = m.group(1)
    else:
        # find first {...} balanced-ish span
        s = raw.find('{')
        e = raw.rfind('}')
        if s >= 0 and e > s:
            raw = raw[s:e + 1]
    try:
        return json.loads(raw)
    except Exception:
        return {}


def validate(data, raw_text=''):
    """Normalize LLM JSON into a safe ai_response dict."""
    if not isinstance(data, dict):
        data = {}
    reply = str(data.get('reply') or '').strip()
    if not reply:
        # LLM answered plain text instead of JSON — use it as the reply.
        reply = str(raw_text or '').strip()
        reply = re.sub(r'^```[a-z]*|```$', '', reply, flags=re.MULTILINE).strip()
        reply = re.sub(r'^\{.*"reply"\s*:\s*"(.*)".*\}$', r'\1', reply, flags=re.DOTALL)
    emotion = str(data.get('emotion') or 'neutral').lower().strip()
    emotion = EMOTION_ALIASES.get(emotion, emotion)
    if emotion not in VALID_EMOTIONS:
        emotion = 'neutral'
    action = str(data.get('action') or 'idle').lower().strip()
    action = ACTION_ALIASES.get(action, action)
    if action not in VALID_ACTIONS:
        action = 'idle'
    costume = data.get('costume')
    if isinstance(costume, str):
        costume = costume.lower().strip()
    else:
        costume = None
    if action == 'change_costume' and costume not in VALID_COSTUMES:
        # try to guess costume from the reply text
        guess = None
        hints = {
            'school': ('水手服', '学生', '校服', 'jk'),
            'stylish': ('时尚', '时髦', '都市'),
            'gothic': ('洋装', '哥特', 'lolita', '洛丽塔'),
            'seed': ('科技', '未来', '赛博', '种子'),
            'casual': ('日常', '休闲', '便装'),
        }
        for cid, words in hints.items():
            if any(w in reply for w in words):
                guess = cid
                break
        if guess:
            costume = guess
        else:
            action = 'idle'
            costume = None
    elif action != 'change_costume':
        costume = None
    # long-term memory: the LLM may emit "memories" alongside the reply
    # (see system_prompt). Normalize to a short list of clean strings.
    memories = []
    raw_mem = data.get('memories')
    if isinstance(raw_mem, str):
        raw_mem = [raw_mem]
    if isinstance(raw_mem, list):
        for it in raw_mem:
            if isinstance(it, dict) and isinstance(it.get('text'), str):
                it = it['text']
            if not isinstance(it, str):
                continue
            t = it.strip()[:MEMORY_MAX_LEN]
            if t:
                memories.append(t)
            if len(memories) >= MEMORY_MAX_ITEMS:
                break
    return {'reply': reply, 'emotion': emotion, 'action': action, 'costume': costume,
            'memories': memories}
