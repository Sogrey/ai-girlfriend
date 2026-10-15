# -*- coding: utf-8 -*-
"""Reminder store & trigger engine (schedule/time - the "P2 care" feature).

Three types:
  once   - fires once at an epoch-time `at`, then is deleted
  daily  - fires every day at `hhmm` ("HH:MM")
  hourly - fires every hour at minute `minute` (0..59)

Fire text supports a {time} placeholder, replaced with the wall-clock
time at trigger (e.g. "It's {time} now, time for a drink~").

Persistence: config/reminders.json (atomic write, same pattern as
memory.json). Expired `once` entries are dropped on load. REMINDERS_PATH
is a module-level constant so tests can redirect it (10-11 lesson).
"""
import json
import logging
import os
import time
import uuid

logger = logging.getLogger('reminders')


_DROP_CHARS = set(" \t\r\n，。！？、；：“”‘’（）【】《》[]{}<>.,!?;:'`~·~@#$%^&*+=|\\/"
                  "的个每那条这条些全部提醒一下不想要了去掉删掉别再"
                  "把帮忙撤取消设定还就快也吧呀嗯哦呢说叫会能")


def _norm_key(s):
    """Comparison key for fuzzy matching: drop whitespace, punctuation and
    conversational filler particles so "把喝水的那个提醒删了" can hit
    "{time} 了，喝水吧". Plain char-set pass — no regex escape traps."""
    return ''.join(ch for ch in str(s) if ch not in _DROP_CHARS).lower()


def _char_overlap(key, blob):
    """Share of distinct key chars present in blob (fuzzy fallback when
    substring match fails, e.g. '把睡眠那条删了' vs '早点睡觉哦')."""
    chars = set(key)
    if not chars:
        return 0.0
    return sum(1 for c in chars if c in blob) / len(chars)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
REMINDERS_PATH = os.path.join(ROOT, 'config', 'reminders.json')

VALID_TYPES = ('once', 'daily', 'hourly')


def next_due(rem, now=None):
    """Next epoch time this reminder fires at, or None when it never
    will again (an expired `once`). Pure function over the stored dict."""
    now = time.time() if now is None else now
    t = rem.get('type')
    if t == 'once':
        # the stored moment itself, even if in the past — due() decides
        # whether it is fresh enough to still fire (a `once` that just
        # reached its moment MUST fire on the next 20s scan tick, when
        # now is inevitably PAST `at`; dropping it here made one-shot
        # reminders never fire at all — bug caught by T1 on first run)
        return rem.get('at', 0)
    if t == 'daily':
        hhmm = rem.get('hhmm') or '09:00'
        try:
            hh, mm = [int(x) for x in hhmm.split(':')[:2]]
        except (ValueError, AttributeError):
            return None
        lt = time.localtime(now)
        candidate = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0,
                                 lt.tm_wday, lt.tm_yday, -1))
        # NOTE: advance the period only when MISSED by >60s — with a 20s
        # scan loop, `candidate <= now` would jump straight to the next
        # day the first tick AFTER the minute (the second hand is already
        # past :00), so daily reminders would NEVER fire. A 60s grace keeps
        # the just-reached moment due; due()'s last_fired guard prevents
        # double-firing within the grace window.
        if candidate < now - 60:
            candidate += 86400
        return candidate
    if t == 'hourly':
        minute = int(rem.get('minute', 0) or 0) % 60
        lt = time.localtime(now)
        candidate = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, minute, 0,
                                 lt.tm_wday, lt.tm_yday, -1))
        # same 60s grace as daily (see note above)
        if candidate < now - 60:
            candidate += 3600
        return candidate
    return None


def describe(rem, now=None):
    """Human-readable schedule line for the UI list."""
    t = rem.get('type')
    if t == 'once':
        return time.strftime('%m-%d %H:%M', time.localtime(rem.get('at', 0)))
    if t == 'daily':
        return '每天 ' + (rem.get('hhmm') or '')
    if t == 'hourly':
        return '每小时·第%s分' % (rem.get('minute', 0))
    return t


class ReminderStore:
    def __init__(self, path=None):
        self.path = path or REMINDERS_PATH
        self.items = {}   # id -> reminder dict
        self.load()

    # ---------------- persistence ----------------

    def load(self):
        self.items = {}
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except Exception as e:
            logger.warning('cannot read reminders file: %s', e)
            return
        now = time.time()
        dropped = 0
        for rem in data.get('reminders', []):
            if not isinstance(rem, dict):
                continue
            if rem.get('type') == 'once' and (rem.get('at', 0) or 0) <= now:
                dropped += 1
                continue
            self.items[rem.get('id') or uuid.uuid4().hex] = rem
        if dropped:
            logger.info('dropped %d expired one-shot reminder(s) on load', dropped)
            self.save()

    def save(self):
        tmp = self.path + '.tmp'
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'reminders': list(self.items.values())}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.error('cannot save reminders: %s', e)

    # ---------------- CRUD ----------------

    def add(self, rtype, text, at=None, hhmm=None, minute=None, emotion=None):
        """Validate & add; returns (reminder|None, error_message)."""
        rtype = str(rtype or '').strip()
        text = str(text or '').strip()
        if rtype not in VALID_TYPES:
            return None, f'未知提醒类型: {rtype}（支持 once/daily/hourly）'
        if not text:
            return None, '提醒内容不能为空'
        if len(text) > 120:
            return None, '提醒内容太长（≤120 字）'
        rem = {'id': uuid.uuid4().hex[:12], 'type': rtype, 'text': text,
               'emotion': emotion or None, 'created_at': time.time()}
        if rtype == 'once':
            try:
                rem['at'] = float(at)
            except (TypeError, ValueError):
                return None, '一次性提醒需要有效的触发时间'
            if rem['at'] <= time.time() + 5:
                return None, '触发时间至少要在 5 秒之后'
        elif rtype == 'daily':
            hhmm = str(hhmm or '').strip()
            try:
                hh, mm = [int(x) for x in hhmm.split(':')[:2]]
                assert 0 <= hh < 24 and 0 <= mm < 60
            except Exception:
                return None, '每天提醒需要 HH:MM 格式的时间'
            rem['hhmm'] = '%02d:%02d' % (hh, mm)
        elif rtype == 'hourly':
            try:
                m = int(minute)
                assert 0 <= m < 60
            except Exception:
                return None, '每小时提醒需要 0~59 的分钟数'
            rem['minute'] = m
        self.items[rem['id']] = rem
        self.save()
        logger.info('reminder added: %s %s %r', rem['id'], rtype, text[:30])
        return rem, None

    def delete(self, rid):
        if rid in self.items:
            del self.items[rid]
            self.save()
            return True
        return False

    def clear_all(self):
        """Delete every reminder; returns how many were removed."""
        n = len(self.items)
        self.items.clear()
        if n:
            self.save()
        return n

    def find(self, query):
        """Fuzzy-match reminders for natural-language deletion (Phase 34).
        Substring match over normalized text+schedule first, char-overlap
        >=0.7 as fallback. Returns the matched reminder list (may be 0/1/many).
        """
        key = _norm_key(query)
        if not key:
            return []
        exact, fuzzy = [], []
        for rem in self.items.values():
            blob = _norm_key('%s %s %s' % (rem.get('text', ''),
                                           describe(rem), rem.get('type', '')))
            if key in blob:
                exact.append(rem)
            elif _char_overlap(key, blob) >= 0.7:
                fuzzy.append(rem)
        return exact or fuzzy

    # ---------------- triggering ----------------

    def due(self, now=None):
        """Return (reminder, resolved_text) pairs whose moment has come.
        A `once` fires (and is dropped); recurring ones record last_fired
        so a single period never double-fires across scan ticks."""
        now = time.time() if now is None else now
        fired = []
        for rid in list(self.items.keys()):
            rem = self.items[rid]
            due_at = next_due(rem, now)
            if due_at is None:
                if rem['type'] == 'once':
                    del self.items[rid]        # unreachable type value / corrupt
                continue
            if now >= due_at:
                if rem['type'] == 'once':
                    # missed by a long offline gap -> drop silently
                    # (fire window: fresh if within 5 min of the moment;
                    # load() already drops older ones at startup)
                    if now - due_at > 300:
                        del self.items[rid]
                        continue
                # guard: only fire once per period (scan loop granularity)
                last = rem.get('last_fired', 0)
                if last >= due_at - 60:
                    continue
                text = (rem['text'] or '').replace(
                    '{time}', time.strftime('%H:%M', time.localtime(now)))
                fired.append((rem, text))
                rem['last_fired'] = now
                if rem['type'] == 'once':
                    del self.items[rid]
        if fired:
            self.save()
        return fired

    def to_list(self):
        now = time.time()
        out = []
        for rem in self.items.values():
            nd = next_due(rem, now)
            out.append({
                'id': rem['id'], 'type': rem['type'], 'text': rem['text'],
                'emotion': rem.get('emotion'), 'schedule': describe(rem, now),
                'next_due': int(nd) if nd else None,
            })
        out.sort(key=lambda r: (r['next_due'] is None, r['next_due'] or 0))
        return out
