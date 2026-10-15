"""Fifty causal, reproducible *research* ranking rules.

Five imported baselines and five families of nine parameter variants are
evaluated separately.  Variants are correlated experiments, not fifty
independent votes or evidence of an increased winning probability.
"""
from __future__ import annotations

import hashlib

import numpy as np

from v9.model import (FAIR_SINGLE, as_matrix, binomial_tail,
                      candidate_scores as baseline_scores, rank)


BASELINES = ("bayes_60", "bayes_240", "ewma_60", "lag_transition", "equal_blend")
FREQUENCY_WINDOWS = (24, 36, 48, 90, 120, 180, 300, 400, 600)
EWMA_HALF_LIVES = (8, 12, 18, 24, 36, 45, 90, 120, 180)
TRANSITION_LAGS = (1, 2, 3, 4, 5, 7, 10, 14, 21)
PAIR_WINDOWS = (60, 90, 120, 180, 240, 360, 480, 600, 800)
BLEND_FREQUENCY_WEIGHTS = tuple(range(1, 10))


def catalog() -> list[dict]:
    rows = [{"name": name, "family": "baseline", "parameter": None}
            for name in BASELINES]
    rows += [{"name": f"frequency_{window}", "family": "frequency_window", "parameter": window}
             for window in FREQUENCY_WINDOWS]
    rows += [{"name": f"ewma_half_{half}", "family": "exponential_recency", "parameter": half}
             for half in EWMA_HALF_LIVES]
    rows += [{"name": f"transition_lag_{lag}", "family": "cross_draw_transition", "parameter": lag}
             for lag in TRANSITION_LAGS]
    rows += [{"name": f"pair_window_{window}", "family": "same_draw_cooccurrence", "parameter": window}
             for window in PAIR_WINDOWS]
    rows += [{"name": f"blend_frequency_{weight}", "family": "fixed_weight_blend", "parameter": weight / 10}
             for weight in BLEND_FREQUENCY_WEIGHTS]
    assert len(rows) == 50 and len({row["name"] for row in rows}) == 50
    return rows


CATALOG = catalog()
MODEL_NAMES = tuple(row["name"] for row in CATALOG)


def _unit(values: np.ndarray) -> np.ndarray:
    scores = np.asarray(values, dtype=np.float64)
    if scores.shape != (49,) or not np.isfinite(scores).all() or (scores < 0).any() or scores.sum() <= 0:
        raise ValueError("Invalid candidate score vector")
    return scores / scores.sum()


def candidate_scores(history: np.ndarray) -> dict[str, np.ndarray]:
    """Use only draws strictly before the target draw."""
    if history.ndim != 2 or history.shape[1] != 49 or len(history) < 240:
        raise ValueError("At least 240 verified 49-ball draws required")
    output = baseline_scores(history)
    for window in FREQUENCY_WINDOWS:
        output[f"frequency_{window}"] = _unit(history[-window:].mean(axis=0))
    for half in EWMA_HALF_LIVES:
        recent = history[-min(len(history), max(240, 8 * half)):]
        ages = np.arange(len(recent) - 1, -1, -1, dtype=np.float64)
        weights = np.exp2(-ages / half)
        output[f"ewma_half_{half}"] = _unit(weights @ recent)
    for lag in TRANSITION_LAGS:
        # For a next-draw forecast, lag=2 conditions on the penultimate draw,
        # not on the latest draw.  Historical examples use the same offset.
        size = min(800, len(history) - lag)
        previous = history[-size-lag:-lag]
        following = history[-size:]
        anchors = np.flatnonzero(history[-lag])
        overlap = previous[:, anchors].sum(axis=1)
        marginal = following.mean(axis=0)
        output[f"transition_lag_{lag}"] = _unit((overlap @ following + 120 * marginal) /
                                                   (overlap.sum() + 120))
    for window in PAIR_WINDOWS:
        recent = history[-window:]
        anchors = np.flatnonzero(history[-1])
        overlap = recent[:, anchors].sum(axis=1)
        marginal = recent.mean(axis=0)
        output[f"pair_window_{window}"] = _unit((overlap @ recent + 120 * marginal) /
                                                 (overlap.sum() + 120))
    for weight in BLEND_FREQUENCY_WEIGHTS:
        fraction = weight / 10
        output[f"blend_frequency_{weight}"] = _unit(
            fraction * output["bayes_240"] + (1 - fraction) / 2 *
            (output["ewma_60"] + output["lag_transition"]))
    if tuple(output) != MODEL_NAMES:
        raise ValueError("Candidate registry and calculated results differ")
    return output


def replay(draws, rounds: int = 520, evaluation: int = 120) -> dict:
    """Choose by 400 development draws; evaluate only on later 120 draws."""
    if len(draws) < rounds + 240 or not 0 < evaluation < rounds:
        raise ValueError("Insufficient verified history for separated replay")
    matrix = as_matrix(draws)
    hits = {name: [] for name in MODEL_NAMES}
    top9 = {name: [] for name in MODEL_NAMES}
    selected_rows = {name: [] for name in MODEL_NAMES}
    for index in range(len(draws) - rounds, len(draws)):
        scores = candidate_scores(matrix[:index])
        actual = set(draws[index].main)
        for name in MODEL_NAMES:
            ordered = rank(scores[name])
            hit = int(ordered[0] in actual)
            nine = len(actual.intersection(ordered[:9]))
            hits[name].append(hit)
            top9[name].append(nine)
            selected_rows[name].append({"period": draws[index].period,
                                        "date": draws[index].draw_date,
                                        "single": ordered[0], "single_hit": hit,
                                        "top9_hits": nine})
    development = rounds - evaluation
    summary = {}
    for row in CATALOG:
        name = row["name"]
        dev_hits = sum(hits[name][:development])
        eval_hits = sum(hits[name][development:])
        summary[name] = {"family": row["family"], "parameter": row["parameter"],
                         "development_hits": dev_hits, "development_rounds": development,
                         "evaluation_hits": eval_hits, "evaluation_rounds": evaluation,
                         "evaluation_top9_hits": sum(top9[name][development:]),
                         "evaluation_one_sided_p": round(binomial_tail(evaluation, eval_hits), 8)}
    selected = max(MODEL_NAMES,
                   key=lambda name: (summary[name]["development_hits"], -MODEL_NAMES.index(name)))
    adjusted = min(1.0, summary[selected]["evaluation_one_sided_p"] * len(MODEL_NAMES))
    final_scores = candidate_scores(matrix)
    for name in MODEL_NAMES:
        ordered = rank(final_scores[name])
        summary[name]["current_first"] = ordered[0]
        summary[name]["rank_sha256"] = hashlib.sha256(bytes(ordered)).hexdigest()
    final_rank = rank(final_scores[selected])
    return {"rule": "50 條固定因果規則；前400期只選模型，後120期評估；選中規則的單尾檢驗乘以50校正",
            "selected_model": selected, "candidate_count": len(MODEL_NAMES),
            "catalog": CATALOG, "models": summary,
            "evaluation_adjusted_p": round(adjusted, 8),
            "statistical_edge_passed": adjusted < 0.05,
            "fair_single_rate": FAIR_SINGLE, "rank": final_rank,
            "top9": final_rank[:9], "single": final_rank[0],
            "score_kind": "僅為相對排序；相關變體不是獨立支持票，也不是中獎機率",
            "selected_replay_rows": selected_rows[selected]}
