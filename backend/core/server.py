# -*- coding: utf-8 -*-
"""WebSocket server on 127.0.0.1:8765.

Protocol (all JSON):
Renderer -> Backend:
  {type:'user_message', text}
  {type:'transcribe_audio', data: <base64 webm/opus>, format:'webm'}
  {type:'speak_line', text, emotion}          # local reaction lines (head pat etc.)
  {type:'reload_config'}
  {type:'ping'}            -> {type:'pong'}

Backend -> Renderer:
  {type:'stt_result', text}
  {type:'ai_response', reply, emotion, action, costume}
  {type:'tts_audio', seq, final, data: <base64 mp3>}
  {type:'status', stt_ready, stt_device, stt_error, llm_provider, llm_health, tts_provider}
  {type:'error', code, message}
"""
import asyncio
import base64
import json
import re
import logging

import websockets

from core.settings import load_config, load_prompt
from llm.manager import LLMManager
from stt.whisper_engine import WhisperEngine
from tts.manager import TTSManager
from conversation.manager import ConversationManager

logger = logging.getLogger('server')

MAX_AUDIO_MB = 15


class BackendServer:
    def __init__(self, port=8765):
        self.port = port
        self.config = load_config()
        self.system_prompt = load_prompt(self.config)
        self.llm = LLMManager(self.config)
        self.stt = WhisperEngine(self.config)
        self.tts = TTSManager(self.config)
        self.conv = ConversationManager(self.config, self.llm, self.system_prompt)
        self.clients = set()
        self._stt_started = False

    # ---------------- lifecycle ----------------

    def start_stt_async(self):
        """Load whisper model in background thread so server accepts clients immediately."""
        if self._stt_started:
            return
        self._stt_started = True
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, self.stt.load)

    def reload(self):
        self.config = load_config()
        self.system_prompt = load_prompt(self.config)
        self.llm.reload()
        self.tts.reload()
        self.conv.reload(self.config, self.system_prompt)
        self.stt.reload_config(self.config)
        logger.info('config reloaded: llm=%s tts=%s', self.llm.provider_name, self.tts.provider_name)

    # ---------------- helpers ----------------

    async def send(self, ws, obj):
        try:
            await ws.send(json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass

    def status_payload(self):
        return {
            'type': 'status',
            'stt_ready': self.stt.ready,
            'stt_device': self.stt.device,
            'stt_error': self.stt.error,
            'llm_provider': self.llm.provider_name,
            'tts_provider': self.tts.provider_name,
        }

    @staticmethod
    def split_sentences(text):
        parts = re.split(r'(?<=[。！？!?；;\n])', text)
        out = [p.strip() for p in parts if p and len(p.strip()) > 1]
        if not out and text.strip():
            out = [text.strip()]
        return out[:6]

    # ---------------- message handling ----------------

    async def handler(self, websocket):
        self.clients.add(websocket)
        logger.info('renderer connected (%d clients)', len(self.clients))
        self.start_stt_async()
        await self.send(websocket, self.status_payload())
        try:
            async for message in websocket:
                try:
                    msg = json.loads(message)
                except Exception:
                    continue
                try:
                    await self.dispatch(websocket, msg)
                except Exception as e:
                    logger.exception('message handling failed')
                    await self.send(websocket, {'type': 'error', 'code': 'internal', 'message': str(e)})
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            logger.info('renderer disconnected')

    async def dispatch(self, ws, msg):
        mtype = msg.get('type')
        mid = msg.get('_id')

        if mtype == 'ping':
            await self.send(ws, {'type': 'pong', '_id': mid})
        elif mtype == 'get_status':
            st = self.status_payload()
            st['_id'] = mid
            await self.send(ws, st)
        elif mtype == 'reload_config':
            self.reload()
            st = self.status_payload()
            st['_id'] = mid
            await self.send(ws, st)
        elif mtype == 'clear_history':
            self.conv.clear()
            await self.send(ws, {'type': 'history_cleared', '_id': mid})
        elif mtype == 'user_message':
            await self.handle_chat(ws, msg.get('text', ''), mid)
        elif mtype == 'transcribe_audio':
            await self.handle_audio(ws, msg.get('data', ''), msg.get('format', 'webm'), mid)
        elif mtype == 'speak_line':
            await self.handle_speak_line(ws, msg.get('text', ''), mid)
        else:
            logger.warning('unknown message type: %s', mtype)

    async def handle_chat(self, ws, text, mid):
        if not text.strip():
            return
        try:
            result = await self.conv.chat(text, source='text')
        except Exception as e:
            logger.error('LLM error: %s', e)
            await self.send(ws, {'type': 'error', 'code': 'llm', 'message': str(e), '_id': mid})
            return
        resp = dict(result)
        resp['type'] = 'ai_response'
        resp['_id'] = mid
        await self.send(ws, resp)
        await self.speak_reply(ws, result['reply'])

    async def handle_audio(self, ws, b64, fmt, mid):
        try:
            if not b64:
                raise ValueError('empty audio payload')
            audio = base64.b64decode(b64)
            if len(audio) > MAX_AUDIO_MB * 1024 * 1024:
                raise ValueError('audio too large')
            if not self.stt.ready:
                # model still loading in background thread
                for _ in range(60):
                    await asyncio.sleep(0.5)
                    if self.stt.ready or self.stt.error:
                        break
            text = self.stt.transcribe(audio, fmt)
        except Exception as e:
            logger.error('STT error: %s', e)
            await self.send(ws, {'type': 'error', 'code': 'stt', 'message': '语音识别失败: ' + str(e), '_id': mid})
            return
        await self.send(ws, {'type': 'stt_result', 'text': text, '_id': mid})
        if text.strip():
            try:
                result = await self.conv.chat(text, source='voice')
            except Exception as e:
                logger.error('LLM error: %s', e)
                await self.send(ws, {'type': 'error', 'code': 'llm', 'message': str(e), '_id': mid})
                return
            resp = dict(result)
            resp['type'] = 'ai_response'
            resp['_id'] = mid
            await self.send(ws, resp)
            await self.speak_reply(ws, result['reply'])
        else:
            # nothing said — gentle ignore
            pass

    async def handle_speak_line(self, ws, text, mid):
        """Speak a local (non-LLM) line, e.g. random head-pat reactions."""
        if not text.strip():
            return
        await self.speak_reply(ws, text)

    async def speak_reply(self, ws, reply_text):
        """Sentence-split a reply, synthesize each with TTS, stream mp3 chunks."""
        sentences = self.split_sentences(reply_text)
        total = len(sentences)
        for i, s in enumerate(sentences):
            final = (i == total - 1)
            try:
                audio = await self.tts.synthesize(s)
                b64 = base64.b64encode(audio).decode('ascii')
                await self.send(ws, {
                    'type': 'tts_audio', 'seq': i, 'final': final, 'format': 'mp3', 'data': b64,
                })
            except Exception as e:
                logger.error('TTS error on sentence %d: %s', i, e)
                if final:
                    await self.send(ws, {'type': 'tts_audio', 'seq': i, 'final': True, 'data': ''})
                else:
                    await self.send(ws, {'type': 'error', 'code': 'tts', 'message': '语音合成失败: ' + str(e)})

    # ---------------- entry ----------------

    async def run(self):
        logger.info('backend listening on ws://127.0.0.1:%d', self.port)
        async with websockets.serve(self.handler, '127.0.0.1', self.port,
                                   max_size=MAX_AUDIO_MB * 1024 * 1024,
                                   ping_interval=20, ping_timeout=30):
            await asyncio.Future()
