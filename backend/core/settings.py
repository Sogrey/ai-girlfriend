# -*- coding: utf-8 -*-
"""Configuration loading (config/config.json + config/user.json merge)."""
import json
import os

# project root = backend/../
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CONFIG_PATH = os.path.join(ROOT, 'config', 'config.json')
USER_CONFIG_PATH = os.path.join(ROOT, 'config', 'user.json')


def deep_merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config():
    base, user = {}, {}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            base = json.load(f)
    except Exception as e:
        print(f'[settings] cannot read config.json: {e}')
    try:
        with open(USER_CONFIG_PATH, 'r', encoding='utf-8') as f:
            user = json.load(f)
    except Exception:
        pass
    return deep_merge(base, user)


def load_prompt(config):
    """Load system prompt file, inject persona/user names."""
    prompt_file = config.get('app', {}).get('prompt_file', 'prompts/system_prompt.txt')
    path = os.path.join(ROOT, prompt_file)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            prompt = f.read()
    except Exception as e:
        print(f'[settings] cannot read prompt file, using minimal prompt: {e}')
        prompt = '你是一个桌面AI女友。输出JSON: {"reply":"...","emotion":"happy","action":"idle","costume":null}'
    persona = config.get('app', {}).get('persona_name', '小满')
    user_name = config.get('app', {}).get('user_name', '')
    prompt = prompt.replace('{persona_name}', persona).replace('{user_name}', user_name)
    if persona:
        prompt = f'你的名字是「{persona}」。' + prompt
    if user_name:
        prompt += f'\n用户希望被称为「{user_name}」。'
    return prompt
