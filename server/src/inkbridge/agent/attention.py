"""Where the user's attention is (INK-130, decision 0089): live browser state, in memory per document."""

import time

from inkbridge import config


class Attention:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._s: dict[str, list] = {}  # doc -> [pen, last_stroke, view]

    def update(self, doc, pen, view=None):
        # shortcut: scene saves do not count as strokes, upgrade if offers appear mid-write
        old = self._s.get(doc)
        # a pen-down or the pen-up that follows it is a stroke moment; a view tick while up is not
        last = old[1] if old and not old[0] and not pen else self.clock()
        self._s[doc] = [bool(pen), last, view]

    def can_push(self, doc):
        s = self._s.get(doc)
        return bool(s) and not s[0] and self.clock() - s[1] >= config.quiet_s()

    def remaining(self, doc):
        s = self._s.get(doc)
        return None if not s or s[0] else max(0.0, config.quiet_s() - (self.clock() - s[1]))

    def forget(self, doc):
        self._s.pop(doc, None)


attention = Attention()
