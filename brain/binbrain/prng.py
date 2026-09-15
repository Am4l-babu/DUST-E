"""
prng.py - a bit-exact port of firmware/TrashBotWeb/src/core/prng.h.

The personality engine is deterministic on purpose: same seed plus the same
inputs gives the same sequence of wrong answers, which is what lets a demo be
rehearsed and a complaint be reproduced. The brain keeps that property by
using the same xorshift32 stream as the firmware, never `random`.

`uniform()` is the one addition; the firmware has no floating-point caller.
"""

from __future__ import annotations

_MASK = 0xFFFFFFFF
_ZERO_SEED = 0x2A2A2A2A   # xorshift32 locks up on zero and never recovers


class Prng:
    def __init__(self, seed: int = _ZERO_SEED) -> None:
        self._state = _ZERO_SEED
        self._initial = _ZERO_SEED
        self.seed(seed)

    def seed(self, s: int) -> None:
        s &= _MASK
        self._state = s if s else _ZERO_SEED
        self._initial = self._state

    @property
    def initial_seed(self) -> int:
        return self._initial

    def next(self) -> int:
        x = self._state
        x ^= (x << 13) & _MASK
        x ^= x >> 17
        x ^= (x << 5) & _MASK
        self._state = x
        return x

    def pick(self, n: int) -> int:
        """0 .. n-1"""
        return self.next() % n if n > 0 else 0

    def range(self, lo: int, hi: int) -> int:
        """lo .. hi inclusive"""
        if hi <= lo:
            return lo
        return lo + self.next() % (hi - lo + 1)

    def chance(self, percent: int) -> bool:
        if percent <= 0:
            return False
        if percent >= 100:
            return True
        return self.next() % 100 < percent

    def uniform(self, lo: float = 0.0, hi: float = 1.0) -> float:
        return lo + (hi - lo) * (self.next() / 4294967296.0)
