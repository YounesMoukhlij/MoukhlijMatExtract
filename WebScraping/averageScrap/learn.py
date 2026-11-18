# WebScraping/averageScrap/learn.py
"""Screening that learns from a person's decisions — to review thousands of papers in the order that teaches most.

The papers decided by hand (a yes or no given in the window, or changed from the proposal in the review list:
`decided_by` "hand") train a small model of the person's judgement: the words of the title and abstract, one or two
at a time, weighed by a logistic regression. It gives each paper still waiting for a decision its chance of a yes
(`model_yes`), and the review list puts the most uncertain first: deciding those teaches the model most (uncertainty
sampling, the usual active-learning order for screening the literature).

The model decides nothing. The rules of the job file propose, the person decides; the model only orders the list
and shows its guess, with its accuracy measured on the person's own decisions (5-fold cross-validation).

    MIN_LABELS decisions by hand at least, MIN_EACH yes and MIN_EACH no, before any model is trained."""

from __future__ import annotations

import logging
import re
import zlib
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np

from .ledger import SCREENED, Candidate, Ledger

MIN_LABELS, MIN_EACH = 10, 3
DIMENSIONS = 2 ** 15     # the words hashed into this many features
L2 = 1.0                 # how strongly the weights are held small (a few hundred decisions: overfitting is the risk)
STEPS, RATE = 300, 0.5
FOLDS = 5
_WORD = re.compile(r"[a-z0-9][a-z0-9\-]+")
_STOP = frozenset("the a an of and in on for with by to from at as is are was were be this that its their we our "
                  "using based via into than which".split())


@dataclass
class Report:
    trained: bool
    labels: int = 0
    yes: int = 0
    scored: int = 0
    accuracy: float = 0.0    # 5-fold cross-validated, on the decisions by hand
    text: str = ""


def _features(candidate: Candidate) -> np.ndarray:
    """The hashed words and word pairs of the title (counted twice) and the abstract, as column indices."""
    words = [w for w in _WORD.findall(f"{candidate.title} {candidate.title} {candidate.abstract}".lower())
             if w not in _STOP]
    grams = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
    return np.unique(np.array([zlib.crc32(g.encode()) % DIMENSIONS for g in grams], dtype=np.int64))


def _matrix(rows: Sequence[np.ndarray]) -> np.ndarray:
    x = np.zeros((len(rows), DIMENSIONS), dtype=np.float32)
    for i, columns in enumerate(rows):
        if len(columns):
            x[i, columns] = 1.0 / np.sqrt(len(columns))  # long abstracts do not outweigh short ones
    return x


def _fit(x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
    """A logistic regression, L2-regularised, by gradient descent; the classes weighed equally."""
    w, b = np.zeros(x.shape[1], dtype=np.float32), 0.0
    weight = np.where(y == 1, 0.5 / max(y.mean(), 1e-9), 0.5 / max(1 - y.mean(), 1e-9)).astype(np.float32)
    n = len(y)
    for _ in range(STEPS):
        p = 1.0 / (1.0 + np.exp(-(x @ w + b)))
        error = (p - y) * weight
        w -= RATE * (x.T @ error / n + L2 * w / n)
        b -= RATE * float(error.mean())
    return w, b


def _predict(x: np.ndarray, model: Tuple[np.ndarray, float]) -> np.ndarray:
    w, b = model
    return 1.0 / (1.0 + np.exp(-(x @ w + b)))


def _cross_validated(x: np.ndarray, y: np.ndarray) -> float:
    """The share of the decisions by hand a model trained on the other folds gets right."""
    order = np.random.default_rng(20261117).permutation(len(y))
    right = 0
    for fold in range(FOLDS):
        test = order[fold::FOLDS]
        train = np.setdiff1d(order, test)
        if len(np.unique(y[train])) < 2 or not len(test):
            continue
        right += int(((_predict(x[test], _fit(x[train], y[train])) >= 0.5) == (y[test] == 1)).sum())
    return right / len(y)


def refresh(ledger: Ledger) -> Report:
    """Trains on the decisions by hand and writes the guess of every paper still waiting (model_yes); without enough
    decisions, clears the guesses. Returns what was done."""
    everything = ledger.all()
    labelled = [c for c in everything if c.decided_by == "hand" and c.decision in ("yes", "no")]
    waiting = [c for c in everything if c.status == SCREENED and c.decided_by != "hand"]
    y = np.array([1.0 if c.decision == "yes" else 0.0 for c in labelled], dtype=np.float32)
    yes = int(y.sum())
    if len(labelled) < MIN_LABELS or yes < MIN_EACH or len(labelled) - yes < MIN_EACH:
        stale = [(c.key, {"model_yes": -1.0}) for c in everything if c.model_yes >= 0]
        ledger._set_many(stale)
        return Report(False, len(labelled), yes, text=(
            f"Learning from your decisions: {len(labelled)} decision(s) by hand ({yes} yes) — it starts at "
            f"{MIN_LABELS} decisions by hand, {MIN_EACH} yes and {MIN_EACH} no at least."))
    x = _matrix([_features(c) for c in labelled])
    accuracy = _cross_validated(x, y)
    model = _fit(x, y)
    changes = []
    for start in range(0, len(waiting), 256):  # in blocks of 256 papers: about 33 MB at a time
        block = waiting[start:start + 256]
        guesses = _predict(_matrix([_features(c) for c in block]), model)
        changes += [(c.key, {"model_yes": round(float(p), 3)}) for c, p in zip(block, guesses)]
    changes += [(c.key, {"model_yes": -1.0}) for c in labelled if c.model_yes >= 0]
    ledger._set_many(changes)
    report = Report(True, len(labelled), yes, len(waiting), accuracy, text=(
        f"Learning from your decisions: trained on {len(labelled)} decisions by hand ({yes} yes), right on "
        f"{100 * accuracy:.0f} % of them in 5-fold cross-validation; {len(waiting):,} paper(s) waiting got its "
        "guess, the most uncertain first in the review list. It decides nothing."))
    logging.info(report.text)
    return report


__all__: List[str] = ["Report", "refresh", "MIN_LABELS", "MIN_EACH"]
