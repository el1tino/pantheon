"""Pull the "content" string out of a JSON reply while it is still streaming.

Seats answer in JSON, but the Chamber should only type out what they say. This parser
finds the "content" key and decodes its string value incrementally, escapes included.
"""

import json
import re

_KEY = re.compile(r'"content"\s*:\s*"')
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class ContentStreamer:
    def __init__(self) -> None:
        self.buf = ""
        self.pos: int | None = None  # index in buf of the next undecoded content char
        self.done = False

    def feed(self, chunk: str) -> str:
        """Add raw model output; return any newly decoded content text."""
        self.buf += chunk
        if self.done:
            return ""
        if self.pos is None:
            m = _KEY.search(self.buf)
            if not m:
                return ""
            self.pos = m.end()
        out: list[str] = []
        i, buf = self.pos, self.buf
        while i < len(buf):
            ch = buf[i]
            if ch == '"':
                self.done = True
                i += 1
                break
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            if i + 1 >= len(buf):
                break  # escape split across chunks: wait for more
            esc = buf[i + 1]
            if esc == "u":
                if i + 6 > len(buf):
                    break
                try:
                    out.append(json.loads(f'"{buf[i:i + 6]}"'))
                except json.JSONDecodeError:
                    pass
                i += 6
                continue
            out.append(_ESCAPES.get(esc, esc))
            i += 2
        self.pos = i
        return "".join(out)
