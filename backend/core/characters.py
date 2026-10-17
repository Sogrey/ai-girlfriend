# -*- coding: utf-8 -*-
"""Character store (Phase 39): multi-persona support.

Each character is a JSON file under config/characters/<id>.json:

    {
      "name": "小雪",                    # displayed name (required)
      "desc": "高冷学霸",                 # short tag shown in the switcher UI
      "model": "assets/characters/xiaoxue.vrm",   # optional VRM; missing =
                                        # the shared default model
      "tint": "school",                  # optional costume tint id applied
                                        # when no dedicated model exists
      "system_prompt": "...",            # optional full prompt override;
                                        # empty = the global persona
      "voice": {                          # optional tts override merged on
        "gptsovits": {"ref_audio": "...", "ref_text": "..."}   # switch
      }                                   # voices per character
    }

The primary character (id "xiaoman") is ALWAYS present and synthesized
from the global config (empty overrides) — its persistence targets are the
legacy files (history.jsonl / memory.json / reminders.json), so all
existing data keeps working with zero migration. Other characters persist
to history-<id>.jsonl etc. in the SAME directory, which keeps the isolated
test-redirect (run_side_backend.py patches those module constants) working
for every character automatically.

The LLM provider is shared (one DeepSeek key serves every character); only
persona, voice and per-character storage switch.
"""
import copy
import json
import logging
import os
import re
import uuid

logger = logging.getLogger('characters')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHARACTERS_DIR = os.path.join(ROOT, 'config', 'characters')

PRIMARY_ID = 'xiaoman'


def _deep_merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class CharacterStore:
    def __init__(self, config, characters_dir=None):
        self.config = config or {}
        self.dir = characters_dir or CHARACTERS_DIR
        self.characters = {}
        self._scan()
        self._ensure_primary()

    # ---------- scanning ----------

    def _scan(self):
        # FULL rebuild (Phase 40 fix): the dict is reset first so a rescan
        # after a profile deletion drops the stale in-memory entry — the
        # old add-only scan left deleted characters alive until reboot.
        self.characters = {}
        if not os.path.isdir(self.dir):
            return
        for fn in os.listdir(self.dir):
            if not fn.endswith('.json'):
                continue
            cid = fn[:-5]
            try:
                with open(os.path.join(self.dir, fn), 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                if not isinstance(data, dict) or not str(data.get('name') or '').strip():
                    logger.warning('character file %s has no name - skipped', fn)
                    continue
                self.characters[cid] = data
            except Exception as e:
                logger.warning('cannot load character %s: %s', fn, e)

    def _ensure_primary(self):
        """The primary character must always exist; a file override wins
        (lets users restyle 小满 without editing the prompt UI), otherwise
        a default entry is synthesized from the global config so switching
        back equals today's behavior exactly."""
        if PRIMARY_ID not in self.characters:
            self.characters[PRIMARY_ID] = {
                'name': (self.config.get('app', {}) or {}).get('persona_name') or '小满',
                'desc': '默认',
                'primary': True,
            }
        else:
            self.characters[PRIMARY_ID].setdefault('primary', True)
        # a config persona_name rename wins for the primary unless the
        # user's character file pins its own name
        cfg_name = (self.config.get('app', {}) or {}).get('persona_name')
        if cfg_name and not self.characters[PRIMARY_ID].get('name_pinned'):
            self.characters[PRIMARY_ID]['name'] = cfg_name

    # ---------- listing / lookup ----------

    def summary(self):
        """UI-facing list (order: primary first, then file order)."""
        items = []
        for cid in ([PRIMARY_ID] + [k for k in self.characters if k != PRIMARY_ID]):
            ch = self.characters[cid]
            items.append({
                'id': cid,
                'name': ch.get('name', cid),
                'desc': ch.get('desc', ''),
                'model': ch.get('model') or '',
                'primary': bool(ch.get('primary')),
            })
        return items

    def get(self, cid):
        return self.characters.get(cid)

    def exists(self, cid):
        return cid in self.characters

    # ---------- profile management (Phase 40: the character-manager UI) ----------

    ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')

    def save(self, cid, data):
        """Create or update one character profile file (full replace: the
        manager form's fields ARE the file). Returns (True, id) on success
        or (False, error-message). The primary character is refused here —
        its persona lives in the global config / settings panel.
        Field sanitizing keeps files small and path-safe; empty optional
        fields simply drop out of the profile (= inherit the global)."""
        if (cid or '').strip() == PRIMARY_ID:
            return False, '默认角色不用建档案：直接在设置面板修改她的名字和人设'
        name = str((data or {}).get('name') or '').strip()
        if not name:
            return False, '角色名字不能为空'
        cid = str(cid or '').strip()
        if not cid:
            for _ in range(8):
                cand = 'c-' + uuid.uuid4().hex[:6]
                if not os.path.exists(os.path.join(self.dir, cand + '.json')):
                    cid = cand
                    break
            else:
                return False, '自动生成档案 ID 失败，请手动填写'
        if not self.ID_RE.match(cid):
            return False, '档案 ID 只能包含字母、数字、-、_（1~32 位）'
        profile = {'name': name[:24]}
        desc = str(data.get('desc') or '').strip()
        if desc:
            profile['desc'] = desc[:60]
        prompt = str(data.get('system_prompt') or '').strip()
        if prompt:
            profile['system_prompt'] = prompt[:12000]
        model = str(data.get('model') or '').strip()
        if model:
            profile['model'] = model[:300]
        tint = str(data.get('tint') or '').strip()
        if tint:
            profile['tint'] = tint[:20]
        voice = data.get('voice') or {}
        if isinstance(voice, dict):
            gs = {}
            for k in ('ref_audio', 'ref_text'):
                v = str(voice.get(k) or '').strip()
                if v:
                    gs[k] = v[:1000]
            if gs:
                profile['voice'] = {'gptsovits': gs}
        try:
            os.makedirs(self.dir, exist_ok=True)
            path = os.path.join(self.dir, cid + '.json')
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:   # NO BOM (project lesson)
                json.dump(profile, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            return False, '写档案失败：%s' % e
        self._scan()
        self._ensure_primary()
        logger.info('character profile saved: %s (%s)', cid, profile['name'])
        return True, cid

    def can_delete(self, cid):
        """Pre-check without touching disk; returns an error string or None."""
        if (cid or '').strip() == PRIMARY_ID:
            return '默认角色不能删除'
        if not self.exists(cid):
            return '未知的角色: %s' % cid
        return None

    def delete(self, cid):
        """Remove one profile FILE. The character's own persistence files
        (history-<id>.jsonl / memory-<id>.json / reminders-<id>.json) are
        deliberately KEPT — recreating a same-id character restores its
        memory, and a manual cleanup is a one-line delete if truly wanted.
        Returns True on success."""
        err = self.can_delete(cid)
        if err:
            logger.warning('character delete refused: %s', err)
            return False
        try:
            os.remove(os.path.join(self.dir, cid.strip() + '.json'))
        except Exception as e:
            logger.warning('cannot delete character file: %s', e)
            return False
        self._scan()
        self._ensure_primary()
        logger.info('character profile deleted: %s (history files kept)', cid)
        return True

    def brief(self, current_id):
        """Runtime block for the LLM: who is live + who the user may summon
        (powers the natural-language switch intent)."""
        try:
            cur = self.characters.get(current_id) or {}
            lines = ['## 当前角色（切换角色时输出 action=switch_character 并在 character 字段填对方 id）',
                     '现在陪伴用户的角色：{name}（id={cid}）'.format(
                         name=cur.get('name', current_id), cid=current_id),
                     '可切换的角色：' + '、'.join(
                         '{}({})'.format(c['name'], c['id']) for c in self.summary())]
            return '\n'.join(lines)
        except Exception as e:
            logger.warning('character brief failed: %s', e)
            return None

    # ---------- switching ----------

    def persistence_paths(self, cid):
        """(history, memory, reminders) file paths for a character.

        The primary character maps 1:1 onto the legacy files; everyone else
        gets a sibling file in the SAME directory — derived from the
        module-level path constants so the isolated side-backend redirect
        (E2E) covers every character automatically."""
        import conversation.manager as CM
        import conversation.memory as MEM
        import core.reminders as R
        if cid == PRIMARY_ID or cid not in self.characters:
            return CM.HISTORY_PATH, MEM.MEMORY_PATH, R.REMINDERS_PATH
        d = os.path.dirname(CM.HISTORY_PATH)
        md = os.path.dirname(MEM.MEMORY_PATH)
        rd = os.path.dirname(R.REMINDERS_PATH)
        safe = ''.join(c for c in cid if c.isalnum() or c in '-_')
        return (os.path.join(d, 'history-%s.jsonl' % safe),
                os.path.join(md, 'memory-%s.json' % safe),
                os.path.join(rd, 'reminders-%s.json' % safe))

    def build_config(self, cid, base_config=None):
        """Role-specific config = global config + the character's overrides
        (persona name, full prompt, tts voice). Returns (merged, meta) where
        meta is the switchable UI payload. Empty/absent override fields are
        OMITTED (deep-merge would otherwise blank the shared persona)."""
        base = copy.deepcopy(base_config if base_config is not None else self.config)
        ch = self.characters.get(cid)
        if ch is None:
            return base, {'id': cid, 'name': cid, 'model': ''}
        merged = copy.deepcopy(base)
        name = str(ch.get('name') or '').strip()
        prompt = str(ch.get('system_prompt') or '').strip()
        voice = ch.get('voice') or {}
        if name:
            merged.setdefault('app', {})['persona_name'] = name
        if prompt:
            merged.setdefault('prompt', {})['system_prompt'] = prompt
        if isinstance(voice, dict) and voice:
            merged.setdefault('tts', {})
            _deep_merge(merged['tts'], voice)
        meta = {
            'id': cid,
            'name': name or merged.get('app', {}).get('persona_name', cid),
            'desc': ch.get('desc', ''),
            'model': ch.get('model') or '',
            'tint': ch.get('tint') or '',
            'primary': bool(ch.get('primary')),
        }
        return merged, meta


def remember_character(cid):
    """Persist the selected character in user.json (app.character_id) so a
    restart brings the same persona back. Written as a surgical read-modify-
    write of the existing file to preserve every other key byte-for-key."""
    path = os.path.join(ROOT, 'config', 'user.json')
    try:
        cfg = {}
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8-sig') as f:
                cfg = json.load(f)
        app = cfg.setdefault('app', {})
        app['character_id'] = cid
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning('cannot remember character selection: %s', e)
