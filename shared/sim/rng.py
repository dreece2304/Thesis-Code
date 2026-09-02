"""Seeded random number generation.

``mulberry32`` reproduces the JavaScript PRNG used in the original JSX
simulators bit for bit, so ported models can be checked against the JS
output. ``SeededRNG`` wraps ``numpy.random.Generator`` for everything else.
"""
from __future__ import annotations

from typing import Iterator, Sequence

import numpy as np

_M32 = 0xFFFFFFFF


def mulberry32(seed: int) -> Iterator[float]:
    """Yield floats in [0, 1) identical to JS ``mulberry32(seed)()``."""
    a = int(seed) & _M32
    while True:
        a = (a + 0x6D2B79F5) & _M32
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & _M32
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & _M32)) & _M32
        t &= _M32
        yield ((t ^ (t >> 14)) & _M32) / 4294967296.0


class SeededRNG:
    """Thin wrapper over ``numpy.random.default_rng`` with child spawning.

    Every simulation should take one of these rather than calling
    ``np.random`` so results are reproducible from a single integer seed.
    """

    def __init__(self, seed: int | None = 0):
        self.seed = seed
        self._ss = np.random.SeedSequence(seed)
        self.gen = np.random.default_rng(self._ss)

    def spawn(self, n: int) -> list["SeededRNG"]:
        """Independent child generators (for parallel paths or workers)."""
        children = []
        for child_ss in self._ss.spawn(n):
            c = SeededRNG.__new__(SeededRNG)
            c.seed = child_ss.entropy
            c._ss = child_ss
            c.gen = np.random.default_rng(child_ss)
            children.append(c)
        return children

    # Common draws, forwarded so callers do not touch .gen directly.
    def uniform(self, low=0.0, high=1.0, size=None):
        return self.gen.uniform(low, high, size)

    def normal(self, loc=0.0, scale=1.0, size=None):
        return self.gen.normal(loc, scale, size)

    def integers(self, low, high=None, size=None):
        return self.gen.integers(low, high, size)

    def choice(self, a, size=None, replace=True, p=None):
        return self.gen.choice(a, size=size, replace=replace, p=p)

    def bernoulli(self, p, size=None) -> np.ndarray:
        return (self.gen.uniform(size=size) < p).astype(int)

    def bootstrap_indices(self, n: int, size: int | None = None) -> np.ndarray:
        return self.gen.integers(0, n, size or n)

    def block_bootstrap(self, x: Sequence[float], block: int, length: int | None = None) -> np.ndarray:
        """Stationary-ish block bootstrap of a 1-D series (fixed block length)."""
        x = np.asarray(x)
        n = len(x)
        length = length or n
        if block < 1 or n == 0:
            raise ValueError("block >= 1 and non-empty x required")
        starts = self.gen.integers(0, n, int(np.ceil(length / block)))
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % n
        return x[idx[:length]]
