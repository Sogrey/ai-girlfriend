# -*- coding: utf-8 -*-
"""WebSocket server on 127.0.0.1:8765.

Protocol (all JSON):
Renderer -> Backend:
  {type:'user_message', text}            # may create a reminder when the LLM
                                         # emits a `reminder` intent (Phase 33)
  {type:'transcribe_partial', data: <base64 webm/opus>, format:'webm'}   # live partial while speaking
  {type:'transcribe_audio', data: <base64 webm/opus>, format:'webm'}    # final utterance -> STT -> LLM
  {type:'speak_line', text, emotion}          # local reaction lines (head pat etc.)
  {type:'get_reminders'}                      # -> {type:'reminders', items}
  {type:'add_reminder', rtype:'once|daily|hourly', text, at|hhmm|minute, emotion}
  {type:'delete_reminder', id}
  {type:'reload_config'}
  {type:'ping'}            -> {type:'pong'}

Backend -> Renderer:
  {type:'stt_partial', text}                  # live transcription preview (may arrive BEFORE stt_result)
  {type:'reminder_due', text, emotion, schedule}   # a scheduled reminder fired (text bubble + speech)
  {type:'reminder_added', reminder, items}    # a reminder was created via natural-language chat: toast + panel refresh
  {type:'reminder_removed', removed, items}   # reminder(s) deleted via natural-language chat (Phase 34)
  {type:'stt_partial', text}                  # live transcription preview (may arrive BEFORE stt_result)
  {type:'stt_result', text}
  {type:'ai_response', reply, emotion, action, costume}
  {type:'tts_audio', seq, final, data: <base64 mp3/wav per provider>}   # may arrive BEFORE
      ai_response: non-last sentences are synthesized while the LLM is
      still streaming (first-sentence-early TTS, see core/stream_tts.py)
  {type:'status', stt_ready, stt_device, stt_error, llm_provider, llm_health, tts_provider}
  {type:'error', code, message}
"""
import asyncio
import base64
import json
import logging
import struct

import websockets

from core.settings import load_config, load_prompt, load_default_prompt_template
from core.reminders import ReminderStore
from core.stream_tts import ReplySentenceTracker, split_reply
from llm.manager import LLMManager
from stt.whisper_engine import WhisperEngine
from tts.manager import TTSManager, TTSSilentError
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
        # streaming STT: one transcription at a time (model is not thread-safe,
        # GPU is a single lane), latest-partial-wins coalescing, epoch drops
        # partials superseded by a final transcription
        self._stt_lock = asyncio.Lock()
        self._pending_partial = None
        self._partial_task = None
        self._stt_epoch = 0
        # scheduled reminders (hourly/daily/once): fires as speech + a
        # text bubble so the feature also works while TTS is degraded
        self.reminders = ReminderStore()
        # let her list/delete reminders in natural language (Phase 34):
        # each turn's runtime block rides the current reminder summary
        self.conv.reminder_brief = self._reminder_prompt_brief

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
        # NOTE: LLMManager/TTSManager.reload() are parameterless and read
        # the dict captured at construction — refresh their reference first
        # or hot-reload silently keeps serving the OLD config (bug caught
        # 10-13 by the OpenAI provider-switch CDP test: tts stayed `edge`
        # after saving `openai`; masked until now because every earlier
        # reload verification ran after a restart, and conv.reload()
        # already took the new config as a parameter).
        self.llm.config = self.config
        self.llm.reload()
        self.tts.config = self.config
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
        logger.debug('WS-HANDLER enter: client=%s', id(websocket))
        logger.info('renderer connected (%d clients)', len(self.clients))
        self.start_stt_async()
        await self.send(websocket, self.status_payload())
        try:
            async for message in websocket:
                logger.debug('WS-FRAME in: %s', str(message)[:120])
                try:
                    msg = json.loads(message)
                except Exception:
                    continue
                try:
                    await self.dispatch(websocket, msg)
                    logger.debug('WS-FRAME dispatched: %s', msg.get('type'))
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
        elif mtype == 'get_prompt':
            # settings UI persona editor: stored custom override + built-in
            # default template (raw, placeholders NOT injected)
            await self.send(ws, {
                'type': 'prompt',
                'custom': (self.config.get('prompt', {}) or {}).get('system_prompt') or '',
                'default': load_default_prompt_template(self.config),
                '_id': mid,
            })
        elif mtype == 'get_reminders':
            await self.send(ws, {'type': 'reminders', 'items': self.reminders.to_list(), '_id': mid})
        elif mtype == 'add_reminder':
            rem, err = self.reminders.add(
                msg.get('rtype') or msg.get('reminder_type'), msg.get('text'),
                at=msg.get('at'), hhmm=msg.get('hhmm'), minute=msg.get('minute'),
                emotion=msg.get('emotion'))
            if err:
                await self.send(ws, {'type': 'error', 'code': 'reminder', 'message': err, '_id': mid})
            else:
                await self.send(ws, {'type': 'reminders', 'items': self.reminders.to_list(), '_id': mid})
        elif mtype == 'delete_reminder':
            ok = self.reminders.delete(msg.get('id'))
            await self.send(ws, {'type': 'reminder_deleted', 'ok': ok, 'id': msg.get('id'), '_id': mid})
        elif mtype == 'get_memory':
            await self.send(ws, {'type': 'memory', 'items': self.conv.memory.to_list(), '_id': mid})
        elif mtype == 'clear_memory':
            self.conv.memory.clear()
            await self.send(ws, {'type': 'memory_cleared', '_id': mid})
        elif mtype == 'user_message':
            await self.handle_chat(ws, msg.get('text', ''), mid)
        elif mtype == 'transcribe_partial':
            await self.handle_partial(ws, msg.get('data', ''), msg.get('format', 'webm'), mid)
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
        await self._apply_chat_reminder(ws, result)
        await self._apply_chat_reminder_remove(ws, result)
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
            # final utterance: bump the epoch so in-flight/queued partial
            # transcriptions are dropped instead of arriving stale, and take
            # the lock (a partial currently transcribing delays us only by
            # its own short run). Transcribe in an executor so llm_partial /
            # tts_audio pushes keep flowing while whisper runs.
            self._stt_epoch += 1
            self._pending_partial = None
            loop = asyncio.get_event_loop()
            async with self._stt_lock:
                text = await loop.run_in_executor(None, lambda a=audio, f=fmt: self.stt.transcribe(a, f))
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
            await self._apply_chat_reminder(ws, result)
            await self._apply_chat_reminder_remove(ws, result)
            resp = dict(result)
            resp['type'] = 'ai_response'
            resp['_id'] = mid
            await self.send(ws, resp)
            await self._flush_tts(queue, tracker, result)
            await worker
        else:
            # nothing said — gentle ignore
            pass

    # ---------------- streaming STT (live partials) ----------------

    async def handle_partial(self, ws, b64, fmt, mid):
        """Live partial transcription while the user is still speaking.
        Best-effort: latest-partial-wins (a slow transcription never makes
        whisper fall behind — newer buffers just overwrite the slot)."""
        if not b64 or not self.stt.ready:
            return
        self._pending_partial = (ws, b64, fmt)
        if self._partial_task is None or self._partial_task.done():
            self._partial_task = asyncio.ensure_future(self._partial_worker())

    async def _partial_worker(self):
        """Sequentially transcribe the LATEST pending partial buffer.
        Epoch checks drop partials superseded by a final transcription
        (both before taking the lock and before sending). VAD is off for
        partials: silero would trim mid-sentence pauses and the still-open
        tail, making the previewed text jump backwards."""
        loop = asyncio.get_event_loop()
        while self._pending_partial:
            job = self._pending_partial
            self._pending_partial = None
            ws, b64, fmt = job
            epoch = self._stt_epoch
            try:
                audio = base64.b64decode(b64)
                if len(audio) > MAX_AUDIO_MB * 1024 * 1024:
                    continue
                async with self._stt_lock:
                    if epoch != self._stt_epoch:
                        continue   # a final took over while we waited
                    text = await loop.run_in_executor(
                        None, lambda a=audio, f=fmt: self.stt.transcribe(a, f, vad=False))
                if epoch == self._stt_epoch and text:
                    await self.send(ws, {'type': 'stt_partial', 'text': text})
            except Exception as e:
                logger.warning('partial transcribe failed (ignored): %s', e)

    async def handle_speak_line(self, ws, text, emotion=None, mid=None):
        """Speak a local (non-LLM) line, e.g. random head-pat reactions."""
        if not text.strip():
            return
        await self.speak_reply(ws, text, emotion)

    async def speak_reply(self, ws, reply_text, emotion=None):
        """Sentence-split a reply, synthesize each with TTS, stream chunks.
        `emotion` nudges the speaking rate (see tts.manager.EMOTION_RATE_DELTA).
        Streaming providers (gptsovits, Phase 37): each sentence becomes
        multiple self-contained wav frames — the first frame goes out as
        soon as the first chunk arrives (~4s into synthesis) and the NEXT
        sentence is prefetched onto the GPU queue at that same moment
        (api_v2 serializes requests, which turns the sentence chain into
        one tight pipeline: measured inter-sentence gap ~0.9s). Classic
        whole-sentence path is kept for the mp3 providers."""
        sentences = split_reply(reply_text)
        total = len(sentences)
        if self.tts.streamable and not self.tts.fast_failing:
            await self._speak_reply_streamed(ws, sentences, emotion)
            return
        for i, s in enumerate(sentences):
            final = (i == total - 1)
            try:
                audio = await self.tts.synthesize(s, emotion=emotion)
                b64 = base64.b64encode(audio).decode('ascii')
                await self.send(ws, {
                    'type': 'tts_audio', 'seq': i, 'final': final, 'format': self.tts.media_type, 'data': b64,
                })
            except TTSSilentError:
                # breaker fast-fail: already alerted once for this streak —
                # stay silent, player sequence still closes on the final
                logger.warning('TTS breaker fast-fail on sentence %d', i)
                if final:
                    await self.send(ws, {'type': 'tts_audio', 'seq': i, 'final': True, 'data': ''})
            except Exception as e:
                logger.error('TTS error on sentence %d: %s', i, e)
                if final:
                    await self.send(ws, {'type': 'tts_audio', 'seq': i, 'final': True, 'data': ''})
                if self.tts.error_alert_allowed:
                    await self.send(ws, {'type': 'error', 'code': 'tts',
                                         'message': '语音合成失败（恢复前不再重复提示，文字对话不受影响）：' + str(e)})

    # ---------------- streaming TTS: wav re-framing (Phase 37) ----------------

    WAV_HEADER_LEN = 44          # api_v2 emits a standard minimal wav header
    STREAM_FRAME_MIN = 192000    # ~3s of 32k/16bit/mono PCM per mid-stream frame

    async def _speak_reply_streamed(self, ws, sentences, emotion):
        """Streaming speak_reply: per-sentence stream -> re-framed wav
        tts_audio pushes + next-sentence prefetch after each first frame."""
        seq = 0
        sent_any = False
        next_q = None
        for i, s in enumerate(sentences):
            final = (i == len(sentences) - 1)
            if next_q is not None:
                q = next_q
                next_q = None
            else:
                q, _ = self._tts_stream_task(s, emotion)

            def prefetch_hook(next_sentence=s, emotion=emotion):
                nonlocal next_q
                if next_sentence is not None and next_q is None:
                    nq, _ = self._tts_stream_task(next_sentence, emotion)
                    next_q = nq

            hook = prefetch_hook if i + 1 < len(sentences) else None
            try:
                seq, sent = await self._consume_stream(ws, q, seq, final, on_first=hook)
                sent_any = sent_any or sent
                if sent:
                    self.tts.note_success()
            except Exception as e:
                logger.error('TTS stream error on sentence %d: %s', i, e)
                self.tts.note_failure()
                if final:
                    await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': True, 'data': ''})
                    seq += 1
                    sent_any = True
                if self.tts.error_alert_allowed:
                    await self.send(ws, {'type': 'error', 'code': 'tts',
                                         'message': '语音合成失败（恢复前不再重复提示，文字对话不受影响）：' + str(e)})
        if sentences and not sent_any:
            # everything failed silently: still close the sequence
            await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': True, 'data': ''})

    def _tts_stream_task(self, sentence, emotion):
        """Start ONE sentence's streaming synthesis in the background,
        feeding raw http chunks into a queue. Items: bytes | Exception |
        None(EOF). Returns (queue, task)."""
        q = asyncio.Queue()

        async def runner():
            try:
                kwargs = self.tts.stream_kwargs(emotion)
                async for part in self.tts.provider.synthesize_stream(sentence, **kwargs):
                    q.put_nowait(part)
            except Exception as e:   # surfaced to the consumer via the queue
                q.put_nowait(e)
            else:
                q.put_nowait(None)
        return q, asyncio.ensure_future(runner())

    async def _consume_stream(self, ws, q, seq, final, on_first=None, format_name=None):
        """Drink one sentence's stream queue and emit re-framed tts_audio:
        the accumulated PCM is sent as a self-contained wav frame the
        moment the first chunk lands (then on_first fires — the prefetch
        hook), further frames every STREAM_FRAME_MIN bytes, the tail frame
        carries `final`. Empty tail closes with the classic empty-final
        frame. Returns (next_seq, sent_any)."""
        fmt = format_name or self.tts.media_type
        header = None
        buf = b''
        first_sent = False
        sent_any = False
        while True:
            item = await q.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            buf += item
            if header is None:
                if len(buf) < self.WAV_HEADER_LEN:
                    continue
                header, buf = buf[:self.WAV_HEADER_LEN], buf[self.WAV_HEADER_LEN:]
            if not first_sent:
                if buf:
                    await self._send_wav_frame(ws, header, buf, seq, final=False, fmt=fmt)
                    seq += 1
                    buf = b''
                    first_sent = True
                    sent_any = True
                    if on_first:
                        on_first()
            elif len(buf) >= self.STREAM_FRAME_MIN:
                await self._send_wav_frame(ws, header, buf, seq, final=False, fmt=fmt)
                seq += 1
                buf = b''
                sent_any = True
        # tail frame closes this sentence's audio
        if buf:
            await self._send_wav_frame(ws, header, buf, seq, final=final, fmt=fmt)
            seq += 1
            sent_any = True
        else:
            await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': final, 'data': ''})
            seq += 1
        return seq, sent_any

    async def _send_wav_frame(self, ws, header, pcm, seq, final, fmt='wav'):
        """header(44B)+pcm re-stamped into a valid standalone wav (RIFF/data
        size fields rewritten) — the renderer's decodeAudioData plays each
        frame like any normal chunk, so the pipeline needs zero frontend
        changes."""
        h = bytearray(header[:self.WAV_HEADER_LEN])
        h[4:8] = struct.pack('<I', 36 + len(pcm))
        h[40:44] = struct.pack('<I', len(pcm))
        b64 = base64.b64encode(bytes(h) + pcm).decode('ascii')
        await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': final, 'format': fmt, 'data': b64})

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
        chunk so the renderer is never left waiting for audio.
        Streaming providers (Phase 37): each sentence is re-framed into
        multiple wav frames (`_consume_stream`), and the NEXT queued
        sentence is prefetched onto the GPU right after a sentence's first
        frame — the api_v2 request queue turns the sentence chain into a
        tight pipeline."""
        seq = 0
        sent_any = False
        sent_final = False
        _EMPTY = object()
        prefetched = _EMPTY
        use_stream = self.tts.streamable
        while True:
            if prefetched is not _EMPTY:
                item, prefetched = prefetched, _EMPTY
            else:
                item = await queue.get()
            if item is None:
                break
            sentence, emotion, final = item
            if not use_stream:
                # classic whole-sentence path (mp3 providers)
                try:
                    audio = await self.tts.synthesize(sentence, emotion=emotion)
                    b64 = base64.b64encode(audio).decode('ascii')
                    await self.send(ws, {
                        'type': 'tts_audio', 'seq': seq, 'final': final, 'format': self.tts.media_type, 'data': b64,
                    })
                    sent_any = True
                    if final:
                        sent_final = True
                except TTSSilentError:
                    logger.warning('TTS breaker fast-fail on sentence %d', seq)
                    if final:
                        await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': True, 'data': ''})
                        sent_any = True
                        sent_final = True
                except Exception as e:
                    logger.error('TTS error on sentence %d: %s', seq, e)
                    if final:
                        await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': True, 'data': ''})
                        sent_any = True
                        sent_final = True
                    if self.tts.error_alert_allowed:
                        await self.send(ws, {'type': 'error', 'code': 'tts',
                                             'message': '语音合成失败（恢复前不再重复提示，文字对话不受影响）：' + str(e)})
                seq += 1
                continue
            # streaming provider path
            if self.tts.fast_failing:
                logger.warning('TTS breaker fast-fail (stream) on sentence %d', seq)
                if final:
                    await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': True, 'data': ''})
                    sent_any = True
                    sent_final = True
                seq += 1
                continue
            q, _ = self._tts_stream_task(sentence, emotion)

            def prefetch_hook(queue=queue):
                nonlocal prefetched
                if prefetched is _EMPTY and not queue.empty():
                    prefetched = queue.get_nowait()

            try:
                seq, sent = await self._consume_stream(ws, q, seq, final, on_first=prefetch_hook)
                sent_any = sent_any or sent
                if final and sent:
                    sent_final = True
                if sent:
                    self.tts.note_success()
            except Exception as e:
                logger.error('TTS stream error on sentence %d: %s', seq, e)
                if not isinstance(e, TTSSilentError):
                    self.tts.note_failure()
                if final:
                    await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': True, 'data': ''})
                    sent_any = True
                    sent_final = True
                    seq += 1
                if self.tts.error_alert_allowed:
                    await self.send(ws, {'type': 'error', 'code': 'tts',
                                         'message': '语音合成失败（恢复前不再重复提示，文字对话不受影响）：' + str(e)})
        if sent_any and not sent_final:
            # aborted before a final chunk went out — close the sequence
            await self.send(ws, {'type': 'tts_audio', 'seq': seq, 'final': True, 'data': ''})

    # ---------------- scheduled reminders ----------------

    def _reminder_prompt_brief(self):
        """Current reminder list for the per-turn runtime block (Phase 34):
        lets the LLM answer "我设了哪些提醒" naturally and pick the id of
        the entry to delete. Returns None when empty (no noise)."""
        items = self.reminders.to_list()
        if not items:
            return None
        lines = ['## 你当前已登记的提醒（回答列表/删除问题只以本清单为准，历史对话里说过的删除、清空都不算数）']
        for it in items:
            lines.append('- id=%s | %s | %s' % (it['id'], it['schedule'], it['text']))
        return '\n'.join(lines)

    async def _apply_chat_reminder(self, ws, result):
        """Natural-language reminder creation (Phase 33): when the LLM's
        reply carried a validated `reminder` intent, run it through the
        store. On success broadcast reminder_added (toast + panel refresh)
        to every client; on rejection notify just the requester — her
        streamed reply may have claimed success, so the error bubble is
        the correction channel."""
        intent = (result or {}).get('reminder')
        if not intent:
            return
        rem, err = self.reminders.add(
            intent['type'], intent['text'],
            at=intent.get('at'), hhmm=intent.get('hhmm'),
            minute=intent.get('minute'), emotion=intent.get('emotion'))
        if err:
            logger.warning('chat reminder rejected: %s intent=%r', err, intent)
            await self.send(ws, {'type': 'error', 'code': 'reminder',
                                 'message': '提醒没设成功：' + err})
            return
        logger.info('chat reminder added: %s %s %r', rem['id'], rem['type'], rem['text'][:30])
        payload = {'type': 'reminder_added', 'reminder': rem,
                   'items': self.reminders.to_list()}
        for c in list(self.clients):
            await self.send(c, payload)

    async def _apply_chat_reminder_remove(self, ws, result):
        """Natural-language reminder deletion (Phase 34): execute the LLM's
        validated `reminder_remove` intent (id exact / query fuzzy / all).
        On success broadcast reminder_removed (chat:sys bubble + panel
        refresh) to every client; on ambiguity/miss reply an error bubble
        to the requester so she can correct herself next turn."""
        intent = (result or {}).get('reminder_remove')
        if not intent:
            return
        removed = []
        if intent.get('all'):
            if not self.reminders.items:
                return
            removed = list(self.reminders.items.values())
            self.reminders.clear_all()
        elif intent.get('id'):
            rem = self.reminders.items.get(intent['id'])
            if rem is not None and self.reminders.delete(intent['id']):
                removed = [rem]
            if not removed and intent.get('query'):
                # LLM miscopied the id — fall back to the keyword it gave
                # alongside (dual-channel intent, see system_prompt)
                matches = self.reminders.find(intent['query'])
                if len(matches) == 1:
                    self.reminders.delete(matches[0]['id'])
                    removed = matches
                    logger.warning('chat reminder: id %s missed, query fallback hit',
                                   intent['id'])
            if not removed:
                await self.send(ws, {'type': 'error', 'code': 'reminder',
                                     'message': '提醒没删成：没找到对应的提醒，可以说得具体些或先让我列一遍'})
                return
        elif intent.get('query'):
            matches = self.reminders.find(intent['query'])
            if len(matches) == 1:
                self.reminders.delete(matches[0]['id'])
                removed = matches
            elif len(matches) > 1:
                await self.send(ws, {'type': 'error', 'code': 'reminder',
                                     'message': '有多条提醒都像「%s」，说得更具体些或直接报内容' % intent['query']})
                return
            else:
                await self.send(ws, {'type': 'error', 'code': 'reminder',
                                     'message': '没找到叫「%s」的提醒，可以问我先列一遍现有的' % intent['query']})
                return
        if removed:
            logger.info('chat reminder removed: %s', ','.join(r['id'] for r in removed))
            payload = {'type': 'reminder_removed',
                       'removed': [{'id': r['id'], 'type': r['type'],
                                    'text': r.get('text', '')} for r in removed],
                       'items': self.reminders.to_list()}
            for c in list(self.clients):
                await self.send(c, payload)


    async def _reminder_loop(self):
        """Scan reminders every 20s; when one fires, broadcast a text
        bubble (reminder_due) + spoken line (speak_reply) to every client.
        The bubble matters most: with TTS degraded (e.g. edge 403) the
        reminder still reaches the user as text."""
        while True:
            try:
                await asyncio.sleep(20)
                fired = self.reminders.due()
                for rem, text in fired:
                    logger.info('reminder fired: %s %r', rem['id'], text[:30])
                    payload = {'type': 'reminder_due', 'text': text,
                               'emotion': rem.get('emotion'), 'schedule': rem.get('type')}
                    for ws in list(self.clients):
                        await self.send(ws, payload)
                        try:
                            await self.speak_reply(ws, text, rem.get('emotion'))
                        except Exception as e:
                            logger.warning('reminder speech failed (ignored): %s', e)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error('reminder loop error (continuing): %s', e)

    # ---------------- entry ----------------

    async def run(self):
        logger.info('backend listening on ws://127.0.0.1:%d', self.port)
        asyncio.ensure_future(self._reminder_loop())
        async with websockets.serve(self.handler, '127.0.0.1', self.port,
                                   max_size=MAX_AUDIO_MB * 1024 * 1024,
                                   ping_interval=20, ping_timeout=30):
            await asyncio.Future()
