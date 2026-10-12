"""Small, reproducible ranking experiment over verified 49-ball-era draws.

These scores are NOT winning probabilities. Backtests are separated from
prospectively sealed forecasts and cannot justify a guaranteed pick.
"""
from __future__ import annotations

import math

import numpy as np

from .official_source import OfficialDraw

N = 49
FAIR_SINGLE = 6 / N
MODEL_NAMES = ("bayes_60", "bayes_240", "ewma_60", "lag_transition", "equal_blend")


def as_matrix(draws: list[OfficialDraw]) -> np.ndarray:
    matrix = np.zeros((len(draws), N), dtype=np.float64)
    for index, draw in enumerate(draws):
        matrix[index, np.asarray(draw.main) - 1] = 1.0
    return matrix


def _unit(score: np.ndarray) -> np.ndarray:
    score = np.maximum(np.asarray(score, dtype=float), 1e-9)
    return score / score.sum()


def candidate_scores(history: np.ndarray) -> dict[str, np.ndarray]:
    if len(history) < 240:
        raise ValueError("At least 240 verified past draws required")
    prior = FAIR_SINGLE
    output = {}
    for window, strength in ((60, 120), (240, 240)):
        recent = history[-window:]
        output[f"bayes_{window}"] = _unit((recent.sum(axis=0) + prior * strength) / (len(recent) + strength))
    recent = history[-600:]
    ages = np.arange(len(recent) - 1, -1, -1, dtype=float)
    weights = np.exp2(-ages / 60)
    output["ewma_60"] = _unit((recent * weights[:, None]).sum(axis=0) / weights.sum())
    recent = history[-800:]
    previous, following = recent[:-1], recent[1:]
    marginal = following.mean(axis=0)
    anchors = np.flatnonzero(history[-1])
    transitions = []
    for anchor in anchors:
        occurrences = previous[:, anchor]
        count = occurrences.sum()
        transitions.append((occurrences @ following + 120 * marginal) / (count + 120))
    output["lag_transition"] = _unit(np.mean(transitions, axis=0))
    output["equal_blend"] = _unit((output["bayes_240"] + output["ewma_60"] + output["lag_transition"]) / 3)
    return output


def rank(score: np.ndarray) -> list[int]:
    return (np.lexsort((np.arange(1, N + 1), -score)) + 1).tolist()


def binomial_tail(n: int, hits: int, probability: float = FAIR_SINGLE) -> float:
    if hits <= 0:
        return 1.0
    return min(1.0, sum(math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                                 + k * math.log(probability) + (n - k) * math.log1p(-probability))
                        for k in range(hits, n + 1)))


def replay(draws: list[OfficialDraw], rounds: int = 520, evaluation: int = 120) -> dict:
    if len(draws) < rounds + 240 or not 0 < evaluation < rounds:
        raise ValueError("Insufficient verified history for separated replay")
    matrix = as_matrix(draws)
    results = {name: [] for name in MODEL_NAMES}
    first_index = len(draws) - rounds
    for index in range(first_index, len(draws)):
        scores = candidate_scores(matrix[:index])
        actual = set(draws[index].main)
        for name in MODEL_NAMES:
            ordered = rank(scores[name])
            results[name].append({"period": draws[index].period, "date": draws[index].draw_date,
                                  "single": ordered[0], "single_hit": int(ordered[0] in actual),
                                  "top9_hits": len(actual.intersection(ordered[:9]))})
    development = rounds - evaluation
    summary = {}
    for name, rows in results.items():
        dev_hits = sum(row["single_hit"] for row in rows[:development])
        eval_hits = sum(row["single_hit"] for row in rows[development:])
        summary[name] = {"development_hits": dev_hits, "development_rounds": development,
                         "evaluation_hits": eval_hits, "evaluation_rounds": evaluation,
                         "evaluation_top9_hits": sum(row["top9_hits"] for row in rows[development:]),
                         "total_hits": dev_hits + eval_hits,
                         "evaluation_one_sided_p": round(binomial_tail(evaluation, eval_hits), 8)}
    selected = max(MODEL_NAMES, key=lambda name: (summary[name]["development_hits"], -MODEL_NAMES.index(name)))
    selected_test = summary[selected]
    multiple_test_p = min(1.0, selected_test["evaluation_one_sided_p"] * len(MODEL_NAMES))
    final_scores = candidate_scores(matrix)[selected]
    final_rank = rank(final_scores)
    return {
        "rule": "每期僅用開獎前官方資料；前400期選固定模型，後120期只評估；五模型多重比較校正",
        "selection_basis": "development_single_hits",
        "selected_model": selected,
        "models": summary,
        "evaluation_adjusted_p": round(multiple_test_p, 8),
        "statistical_edge_passed": multiple_test_p < 0.05,
        "fair_single_rate": FAIR_SINGLE,
        "rank": final_rank,
        "top9": final_rank[:9],
        "single": final_rank[0],
        "score_kind": "相對排序分數，不是中獎機率",
        "selected_replay_rows": results[selected],
    }
