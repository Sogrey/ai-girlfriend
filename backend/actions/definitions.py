# -*- coding: utf-8 -*-
"""Valid action/emotion/costume enums shared between LLM output and renderer."""
import json
import re
import time

VALID_ACTIONS = {
    'idle', 'wave', 'leave', 'return', 'change_costume', 'comfort',
    'head_pat', 'jump', 'dance', 'think', 'nod', 'shake_head', 'blow_kiss',
    'stretch', 'greet', 'spin',
}
VALID_EMOTIONS = {'happy', 'shy', 'angry', 'sad', 'surprised', 'caring', 'neutral'}
VALID_COSTUMES = {'casual', 'school', 'stylish', 'gothic', 'seed'}

# long-term memory extraction caps
MEMORY_MAX_ITEMS = 5
MEMORY_MAX_LEN = 120

# maps some natural words the LLM may emit to canonical actions
ACTION_ALIASES = {
    'pat': 'head_pat', 'headpat': 'head_pat', 'happy': 'wave',
    'goodbye': 'leave', 'sleep': 'leave', 'rest': 'leave',
    'comeback': 'return', 'come_back': 'return', 'costume': 'change_costume',
    'changecostume': 'change_costume', 'cheer': 'jump',
    'kiss': 'blow_kiss', 'blowkiss': 'blow_kiss', 'flying_kiss': 'blow_kiss',
    'yawn': 'stretch', 'lazy': 'stretch',
    'shake': 'shake_head', 'shakehead': 'shake_head', 'headshake': 'shake_head',
    'no': 'shake_head', 'disagree': 'shake_head',
    'hello': 'greet', 'hi': 'greet', 'say_hi': 'greet', 'sayhi': 'greet',
    'greeting': 'greet',
    'twirl': 'spin', 'turn_around': 'spin', 'turnaround': 'spin',
    'circle': 'spin',
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


def normalize_llm_reminder(data, now=None):
    """Normalize the LLM's optional `reminder` key (natural-language-created
    reminder, Phase 33) into a ReminderStore.add() argument dict, or None
    when malformed/absent. LLM schema (see system_prompt):
      {"type": "once|daily|hourly", "time": "...", "text": "...", "emotion": "..."}
    `time` is whatever the LLM resolved "明天早上9点" into:
      once  -> epoch seconds, "YYYY-MM-DD HH:MM[:SS]", "MM-DD HH:MM" or "HH:MM"
               (bare HH:MM in the past rolls to tomorrow)
      daily -> "HH:MM[:SS]"
      hourly -> minute number 0..59 (int / "30" / "30.0" / "每小时的第30分")
    """
    if not isinstance(data, dict):
        return None
    now = time.time() if now is None else now
    rtype = str(data.get('type') or '').strip().lower()
    if rtype not in ('once', 'daily', 'hourly'):
        return None
    text = str(data.get('text') or '').strip()
    if not text:
        return None
    text = text[:120]
    emotion = str(data.get('emotion') or '').lower().strip()
    emotion = EMOTION_ALIASES.get(emotion, emotion)
    if emotion not in VALID_EMOTIONS:
        emotion = 'caring'
    t = data.get('time')
    out = {'type': rtype, 'text': text, 'emotion': emotion}
    if rtype == 'once':
        at = _parse_once_time(t, now)
        if at is None:
            return None
        out['at'] = at
    elif rtype == 'daily':
        hhmm = _parse_hhmm(t)
        if hhmm is None:
            return None
        out['hhmm'] = hhmm
    else:
        m = None
        if isinstance(t, bool):
            m = None
        elif isinstance(t, (int, float)):
            m = int(t)
        elif isinstance(t, str):
            mt = re.search(r'\d+', t.strip())
            m = int(mt.group()) if mt else None
        if m is None or not (0 <= m < 60):
            return None
        out['minute'] = m
    return out


REMINDER_REMOVE_ALL = {'all', '全部', '所有', '全部提醒', '所有提醒',
                        '全部删除', '都删了', '都删掉', '全部都删了', '所有都删'}


def normalize_llm_reminder_remove(data):
    """Normalize the LLM's optional `reminder_remove` key (natural-
    language reminder deletion, Phase 34) into an intent dict, or None
    when absent/malformed. Accepted shapes (see system_prompt):
      {"remove": "all"}              -> {'all': True}          delete everything
      {"remove": "喝水"}              -> {'query': '喝水'}       fuzzy text match
      {"id": "a1b2c3d4e5f6"}         -> {'id': '...'}           exact id (preferred)
      {"id": "...", "remove": "喝水"} -> {'id': '...', 'query': '喝水'}
        both filled: id first, query as fallback when the id misses
        (guards against the LLM miscopying the 12-hex id)
    """
    if not isinstance(data, dict):
        return None
    out = {}
    rid = data.get('id')
    if isinstance(rid, str) and rid.strip():
        out['id'] = rid.strip()[:32]
    q = data.get('remove')
    # the LLM also emits {"all": true} / {"all": "true"} for delete-everything
    # — fold it into remove='all' (silently dropping this shape cost a whole
    # debug hunt: she SAID "全部清掉" while nothing executed)
    all_flag = data.get('all')
    if isinstance(all_flag, str):
        all_flag = all_flag.strip().lower() == 'true'
    if all_flag is True and q is None:
        q = 'all'
    if isinstance(q, str) and q.strip():
        q = q.strip()
        if q.lower() in REMINDER_REMOVE_ALL and 'id' not in out:
            return {'all': True, 'query': q}
        if q.lower() not in REMINDER_REMOVE_ALL:
            out['query'] = q[:60]
    if 'id' not in out and 'query' not in out:
        return None
    return out


def _parse_hhmm(v):
    """'HH:MM[:SS]' (or 'H:MM') -> 'HH:MM', or None."""
    if not isinstance(v, str):
        v = str(v or '')
    try:
        parts = v.strip().split(':')
        hh, mm = int(parts[0]), int(parts[1])
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        return None
    return '%02d:%02d' % (hh, mm)


def _parse_once_time(v, now):
    """Best-effort absolute/rolling time -> epoch seconds (future only)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            t = float(v)
        except (TypeError, ValueError):
            return None
        return t if t > now else None
    s = str(v or '').strip().replace('T', ' ')
    if not s:
        return None
    if re.fullmatch(r'\d{10,14}', s):          # epoch seconds / ms as string
        t = float(s)
        if t > 1e12:
            t /= 1000.0
        return t if t > now else None
    lt_now = time.localtime(now)
    for fmt, has_date in (('%Y-%m-%d %H:%M:%S', True), ('%Y-%m-%d %H:%M', True),
                          ('%Y/%m/%d %H:%M', True),
                          ('%m-%d %H:%M', 'month'), ('%m月%d日 %H:%M', 'month'),
                          ('%H:%M:%S', False), ('%H:%M', False)):
        try:
            st = time.strptime(s, fmt)
        except ValueError:
            continue
        if has_date is True:
            t = time.mktime(st)
        elif has_date == 'month':
            # no year -> assume current year, roll to next year if already past
            t = time.mktime((lt_now.tm_year, st.tm_mon, st.tm_mday, st.tm_hour,
                             st.tm_min, st.tm_sec, 0, 0, -1))
            if t <= now:
                t += 86400 * 366
        else:
            # bare HH:MM[:SS] -> today, or tomorrow when already past
            t = time.mktime((lt_now.tm_year, lt_now.tm_mon, lt_now.tm_mday,
                             st.tm_hour, st.tm_min, st.tm_sec, 0, 0, -1))
            if t <= now:
                t += 86400
        return t if t > now else None
    return None


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
    # natural-language reminder intent (Phase 33): normalized or None
    reminder = normalize_llm_reminder(data.get('reminder'))
    # natural-language reminder deletion intent (Phase 34)
    reminder_remove = normalize_llm_reminder_remove(data.get('reminder_remove'))
    return {'reply': reply, 'emotion': emotion, 'action': action, 'costume': costume,
            'memories': memories, 'reminder': reminder, 'reminder_remove': reminder_remove}
