"""Where the user's attention is (INK-130, decision 0089): live browser state, in memory per document."""

import time

from inkbridge import config


class Attention:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._s: dict[str, list] = {}  # doc -> [pen, last_stroke, view]

    def update(self, doc, pen, view=None):
        # shortcut: scene saves do not count as strokes, upgrade if offers appear mid-write
        self._s[doc] = [bool(pen), self.clock(), view]  # a pen-up is the end of a stroke

    def can_push(self, doc):
        s = self._s.get(doc)
        return bool(s) and not s[0] and self.clock() - s[1] >= config.quiet_s()

    def remaining(self, doc):
        s = self._s.get(doc)
        return None if not s or s[0] else max(0.0, config.quiet_s() - (self.clock() - s[1]))

    def forget(self, doc):
        self._s.pop(doc, None)


attention = Attention()
