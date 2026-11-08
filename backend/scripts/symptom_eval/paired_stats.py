"""
Paired statistics for comparing two eval legs on the same vignettes. Pure
stdlib (no scipy/numpy — neither is a project dependency) and no I/O.

Both functions raise ValueError on input that cannot support an estimate
(empty, unequal lengths, fewer than two pairs) rather than return a
confident-looking number.
"""
import random
from collections.abc import Sequence
from dataclasses import dataclass
from math import comb

BOOTSTRAP_RESAMPLES = 10_000
_LOW_QUANTILE, _HIGH_QUANTILE = 0.025, 0.975


@dataclass(frozen=True)
class McNemarResult:
    only_a: int  # a True, b False
    only_b: int  # b True, a False
    p_value: float


@dataclass(frozen=True)
class BootstrapResult:
    diff: float  # mean(a) - mean(b)
    low: float
    high: float
    resamples: int
    seed: int


def _require_pairs(a: Sequence, b: Sequence) -> None:
    if len(a) != len(b):
        raise ValueError(f"paired inputs differ in length: {len(a)} vs {len(b)}")
    if len(a) < 2:
        raise ValueError(f"need at least 2 pairs, got {len(a)}")


def mcnemar_exact(a: Sequence[bool], b: Sequence[bool]) -> McNemarResult:
    _require_pairs(a, b)
    only_a = sum(1 for x, y in zip(a, b) if x and not y)
    only_b = sum(1 for x, y in zip(a, b) if y and not x)
    discordant = only_a + only_b
    if discordant == 0:
        return McNemarResult(only_a, only_b, 1.0)
    tail = sum(comb(discordant, k) for k in range(min(only_a, only_b) + 1)) / 2**discordant
    return McNemarResult(only_a, only_b, min(1.0, 2 * tail))


def paired_bootstrap_diff(
    a: Sequence[float], b: Sequence[float], seed: int, resamples: int = BOOTSTRAP_RESAMPLES
) -> BootstrapResult:
    _require_pairs(a, b)
    differences = [x - y for x, y in zip(a, b)]
    count = len(differences)
    rng = random.Random(seed)
    means = sorted(
        sum(differences[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(resamples)
    )
    return BootstrapResult(
        diff=sum(differences) / count,
        low=means[int(_LOW_QUANTILE * resamples)],
        high=means[int(_HIGH_QUANTILE * resamples) - 1],
        resamples=resamples,
        seed=seed,
    )
