# -*- coding: utf-8 -*-
"""First-sentence-early TTS for streaming LLM replies.

While the LLM streams its raw JSON, ReplySentenceTracker progressively
extracts the reply value (the same best-effort logic the renderer's
ChatPanel uses for the typewriter effect) and emits complete sentences
the moment they are provably NOT the reply's last one — more reply text
has already arrived past their boundary. Those sentences go to TTS
immediately, cutting the perceived voice latency from
"full generation + synthesis" to "first sentence + synthesis".

The remainder is flushed once the full JSON is parsed so the reply's
emotion shapes the speaking rate of the final sentence(s); early
sentences are spoken at neutral rate because emotion is only known
after the stream completes. To guarantee the last sentence can always
carry emotion, early emission stops one sentence short of the cap.

Segmentation mirrors the classic post-hoc path exactly (same boundary
set, strip + drop len<=1 fragments, 6-sentence cap) so early-emitted
and flushed sentences always partition the reply the same way
speak_reply() did before.
"""
import re

# Partial-JSON extraction — same as renderer ChatPanel.extractPartialReply:
# the reply value has started arriving but the closing quote may not have.
_REPLY_RE = re.compile(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)')

MAX_SENTENCES = 6               # hard cap, same as the classic path
MAX_EARLY = MAX_SENTENCES - 1   # keep the last sentence for the emotion flush


def split_reply(text):
    """Classic sentence split (was BackendServer.split_sentences).

    Single source of truth: speak_reply(), the tracker and the tests all
    go through here so the segmentation rules can never drift apart.
    """
    parts = re.split(r'(?<=[。！？!?；;\n])', text)
    out = [p.strip() for p in parts if p and len(p.strip()) > 1]
    if not out and text.strip():
        out = [text.strip()]
    return out[:MAX_SENTENCES]


def _unescape(s):
    """Partial-safe progressive JSON unescape — same order as ChatPanel."""
    return (s.replace('\\n', '\n')
             .replace('\\"', '"')
             .replace('\\\\', '\\')
             .replace('\\t', '\t'))


class ReplySentenceTracker:
    """Feed accumulated raw chunks in; collect early sentences; flush once."""

    def __init__(self):
        self.emitted = []   # early-emitted sentences (stripped)
        self._pos = 0       # scan offset into the unescaped reply text

    def feed(self, raw_partial):
        """Feed one accumulated raw chunk. Returns newly confirmed early
        sentences: each ended at a boundary that already has more reply
        text streamed past it, i.e. provably not the reply's last
        sentence (a boundary at the very end of the so-far text might
        still be the tail — wait for the next chunk to be sure)."""
        m = _REPLY_RE.search(raw_partial)
        if not m or not m.group(1):
            return []
        text = _unescape(m.group(1))
        out = []
        while len(self.emitted) < MAX_EARLY:
            # earliest boundary after _pos that has >=1 more char after it
            idx = -1
            for i in range(self._pos, len(text) - 1):
                if text[i] in '。！？!?；;\n':
                    idx = i
                    break
            if idx < 0:
                break
            piece = text[self._pos:idx + 1].strip()
            self._pos = idx + 1
            if len(piece) > 1:
                self.emitted.append(piece)
                out.append(piece)
            # len<=1 fragments are skipped — same rule as split_reply
        return out

    def flush(self, final_reply):
        """Sentences left after the early-emitted prefix.

        Returns (sentences, consistent):
          sentences  — remaining sentences to synthesize (may be empty,
                       e.g. a >=6-sentence reply where the cap ate the
                       tail); when nothing was emitted early this is
                       simply split_reply(final_reply), i.e. the classic
                       full path with emotion on every sentence.
          consistent — False means the early prefix disagrees with the
                       final reply (truncated / malformed stream, or the
                       empty-reply retry produced different text). The
                       caller must drop the remainder: some words were
                       already spoken, better to leave it at that than
                       to replay or skip text.
        """
        parts = split_reply(final_reply)
        if not self.emitted:
            return parts, True
        k = len(self.emitted)
        if parts[:k] == self.emitted:
            return parts[k:], True
        return [], False
