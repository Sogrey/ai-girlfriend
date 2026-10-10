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
  {type:'tts_audio', seq, final, data: <base64 mp3>}   # may arrive BEFORE
      ai_response: non-last sentences are synthesized while the LLM is
      still streaming (first-sentence-early TTS, see core/stream_tts.py)
  {type:'status', stt_ready, stt_device, stt_error, llm_provider, llm_health, tts_provider}
  {type:'error', code, message}
"""
import asyncio
import base64
import json
import logging

import websockets

from core.settings import load_config, load_prompt
from core.stream_tts import ReplySentenceTracker, split_reply
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
        elif mtype == 'get_history':
            await self.send(ws, {'type': 'history', 'items': self.conv.get_recent_history(30), '_id': mid})
        elif mtype == 'get_memory':
            await self.send(ws, {'type': 'memory', 'items': self.conv.memory.to_list(), '_id': mid})
        elif mtype == 'clear_memory':
            self.conv.memory.clear()
            await self.send(ws, {'type': 'memory_cleared', '_id': mid})
        elif mtype == 'user_message':
            await self.handle_chat(ws, msg.get('text', ''), mid)
        elif mtype == 'transcribe_audio':
            await self.handle_audio(ws, msg.get('data', ''), msg.get('format', 'webm'), mid)
        elif mtype == 'speak_line':
            await self.handle_speak_line(ws, msg.get('text', ''), msg.get('emotion'), mid)
        else:
            logger.warning('unknown message type: %s', mtype)

    async def handle_chat(self, ws, text, mid):
        if not text.strip():
            return
        tracker = ReplySentenceTracker()
        queue = asyncio.Queue()
        worker = asyncio.ensure_future(self._tts_worker(ws, queue))
        try:
            on_delta = self._stream_sink(ws, tracker, queue)
            result = await self.conv.chat_stream(text, source='text', on_delta=on_delta)
        except Exception as e:
            logger.error('LLM error: %s', e)
            queue.put_nowait(None)
            await worker
            await self.send(ws, {'type': 'error', 'code': 'llm', 'message': str(e), '_id': mid})
            return
        resp = dict(result)
        resp['type'] = 'ai_response'
        resp['_id'] = mid
        await self.send(ws, resp)
        await self._flush_tts(queue, tracker, result)
        await worker

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
            tracker = ReplySentenceTracker()
            queue = asyncio.Queue()
            worker = asyncio.ensure_future(self._tts_worker(ws, queue))
            try:
                on_delta = self._stream_sink(ws, tracker, queue)
                result = await self.conv.chat_stream(text, source='voice', on_delta=on_delta)
            except Exception as e:
                logger.error('LLM error: %s', e)
                queue.put_nowait(None)
                await worker
                await self.send(ws, {'type': 'error', 'code': 'llm', 'message': str(e), '_id': mid})
                return
            resp = dict(result)
            resp['type'] = 'ai_response'
            resp['_id'] = mid
            await self.send(ws, resp)
            await self._flush_tts(queue, tracker, result)
            await worker
        else:
            # nothing said — gentle ignore
            pass

    async def handle_speak_line(self, ws, text, emotion=None, mid=None):
        """Speak a local (non-LLM) line, e.g. random head-pat reactions."""
        if not text.strip():
            return
        await self.speak_reply(ws, text, emotion)

    async def speak_reply(self, ws, reply_text, emotion=None):
        """Sentence-split a reply, synthesize each with TTS, stream mp3 chunks.
        `emotion` nudges the speaking rate (see tts.manager.EMOTION_RATE_DELTA)."""
        sentences = split_reply(reply_text)
        total = len(sentences)
        for i, s in enumerate(sentences):
            final = (i == total - 1)
            try:
                audio = await self.tts.synthesize(s, emotion=emotion)
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

    # ---------------- streaming TTS (first-sentence-early) ----------------

    def _stream_sink(self, ws, tracker, queue):
        """on_delta callback for chat_stream: typewriter push to the UI +
        early-TTS queueing for sentences that are provably not the last
        one. Early sentences are neutral-rate: emotion is only known
        after the whole JSON is parsed (the flush shapes the remainder)."""
        async def push_partial(partial):
            await self.send(ws, {'type': 'llm_partial', 'text': partial})
        def on_delta(partial):
            asyncio.ensure_future(push_partial(partial))
            for sentence in tracker.feed(partial):
                logger.info('early-tts: sentence %d queued while streaming: %r',
                            len(tracker.emitted), sentence[:30])
                queue.put_nowait((sentence, None, False))
        return on_delta

    async def _flush_tts(self, queue, tracker, result):
        """Queue the remaining sentences once the full reply is known
        (emotion-shaped rate), then end the worker sequence."""
        remainder, consistent = tracker.flush(result['reply'])
        emotion = result.get('emotion')
        if consistent:
            logger.info('early-tts: %d early / %d remainder (emotion=%s)',
                        len(tracker.emitted), len(remainder), emotion)
            for i, s in enumerate(remainder):
                queue.put_nowait((s, emotion, i == len(remainder) - 1))
        else:
            # malformed/truncated stream (or empty-reply retry rewrote it):
            # early sentences were spoken from best-effort text that
            # disagrees with the final reply — drop the remainder rather
            # than replay or skip words.
            logger.warning('early-tts: prefix inconsistent with final reply, remainder dropped')
        queue.put_nowait(None)

    async def _tts_worker(self, ws, queue):
        """Sequential TTS synth+send per request: queue order == seq order.
        The final flag comes from the enqueuer (_flush_tts knows the
        total); if the stream aborts mid-way (LLM error / dropped
        remainder) the worker closes the sequence with an empty final
        chunk so the renderer is never left waiting for audio."""
        seq = 0
        sent_any = False
        sent_final = False
        while True:
            item = await queue.get()
            if item is None:
                break
            sentence, emotion, final = item
            try:
                audio = await self.tts.synthesize(sentence, emotion=emotion)
                b64 = base64.b64encode(audio).decode('ascii')
                await self.send(ws, {
                    'type': 'tts_audio', 'seq': seq, 'final': final, 'format': 'mp3', 'data': b64,
                })
                sent_any = True
                if final:
                    sent_final = True
            except Exception as e:
                logger.error('TTS error on sentence %d: %s', seq, e)
                if final:
                    await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': True, 'data': ''})
                    sent_any = True
                    sent_final = True
                else:
                    await self.send(ws, {'type': 'error', 'code': 'tts', 'message': '语音合成失败: ' + str(e)})
            seq += 1
        if sent_any and not sent_final:
            # aborted before a final chunk went out — close the sequence
            await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': True, 'data': ''})

    # ---------------- entry ----------------

    async def run(self):
        logger.info('backend listening on ws://127.0.0.1:%d', self.port)
        async with websockets.serve(self.handler, '127.0.0.1', self.port,
                                   max_size=MAX_AUDIO_MB * 1024 * 1024,
                                   ping_interval=20, ping_timeout=30):
            await asyncio.Future()
