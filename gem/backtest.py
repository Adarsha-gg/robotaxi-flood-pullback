"""G11: Leave-one-storm-out spatial memory backtest (pure Python, no model calls).

Exposes:
    run(n_storms: int = 15) -> dict

CLI:
    .venv/bin/python -m gem.backtest
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CELLS_PATH = REPO_ROOT / "data" / "cells.json"
OUT_PATH = REPO_ROOT / "media" / "backtest.json"

SF_CELLS = 4340  # ~121 km^2 SF land area / ~0.0279 km^2 per cell
AREA_CELLS = 347  # 8.0% of SF_CELLS (int(0.08 * 4340))
AREA_PCT = 0.08
CORRIDOR_NBR_WEIGHT = 0.05
RANDOM_DRAWS = 200
RANDOM_SEED = 42

CAVEAT = (
    "Spatial memory only. Past forecasts are not replayed. "
    "Unit is flooded cells, not reports."
)


def _parse_cell_id(cid: str) -> tuple[int, int]:
    r_part, c_part = cid.split("_")
    return int(r_part[1:]), int(c_part[1:])


def run(n_storms: int = 15) -> dict[str, Any]:
    """Run leave-one-storm-out backtest on the top `n_storms` historical storm days.

    Reads `data/cells.json` (72 storm days strictly pre-2026-11-18).
    For each held-out storm day D:
      - Removes D from every cell's `storm_days` list and recounts remaining storm days.
      - Ranks all cells using ONLY remaining storm days (deterministic tie-break on cell id;
        never uses `n_reports`, which includes reports from D):
          * baseline: top 347 cells by remaining `n_storm_days`
          * corridor: top 347 cells by `rem_n_storm_days + 0.05 * sum(8 grid neighbors)`
      - Scores the fraction of cells flooded on D captured by the 347 picked cells.
      - Computes a random floor as the mean of 200 draws of 347 cells out of SF's 4,340 cells.
    """
    payload = json.loads(CELLS_PATH.read_text(encoding="utf-8"))
    cells: list[dict[str, Any]] = payload["cells"]

    # Pre-index grid coordinates and storm day sets (strictly per-cell storm_days only).
    cell_ids: list[str] = []
    rc_by_id: dict[str, tuple[int, int]] = {}
    id_by_rc: dict[tuple[int, int], str] = {}
    days_by_id: dict[str, set[str]] = {}
    day_counts: Counter[str] = Counter()

    for c in cells:
        cid = c["id"]
        rc = _parse_cell_id(cid)
        sdays = set(c.get("storm_days") or [])
        cell_ids.append(cid)
        rc_by_id[cid] = rc
        id_by_rc[rc] = cid
        days_by_id[cid] = sdays
        for d in sdays:
            day_counts[d] += 1

    # Precompute existing 8-neighbor cell IDs for each cell.
    neighbors_by_id: dict[str, list[str]] = {}
    for cid, (r, col) in rc_by_id.items():
        nbrs: list[str] = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nid = id_by_rc.get((r + dr, col + dc))
                if nid is not None:
                    nbrs.append(nid)
        neighbors_by_id[cid] = nbrs

    # Map active cell IDs into the 4,340-cell San Francisco land universe for random draws.
    id_to_idx = {cid: idx for idx, cid in enumerate(cell_ids)}
    sf_universe = list(range(SF_CELLS))
    rng = random.Random(RANDOM_SEED)

    # Select top `n_storms` storm days with the most flooded cells (tie-break deterministically by date).
    top_storms = sorted(day_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n_storms]

    per_storm: list[dict[str, Any]] = []
    raw_corridor: list[float] = []
    raw_baseline: list[float] = []
    raw_random: list[float] = []

    for storm_date, _ in top_storms:
        flooded = {cid for cid, sdays in days_by_id.items() if storm_date in sdays}
        n_flooded = len(flooded)
        if n_flooded == 0:
            continue

        # Strict leave-one-storm-out remaining storm day counts.
        rem: dict[str, int] = {
            cid: len(sdays) - (1 if storm_date in sdays else 0)
            for cid, sdays in days_by_id.items()
        }

        # Baseline: top 347 cells by remaining n_storm_days (tie-break by cell id).
        baseline_picked = set(
            sorted(cell_ids, key=lambda cid: (-rem[cid], cid))[:AREA_CELLS]
        )
        baseline_rate = len(flooded & baseline_picked) / n_flooded

        # Corridor: top 347 cells by rem + 0.05 * sum(rem of 8 grid neighbors).
        corridor_scores: dict[str, float] = {
            cid: rem[cid] + CORRIDOR_NBR_WEIGHT * sum(rem[nid] for nid in neighbors_by_id[cid])
            for cid in cell_ids
        }
        corridor_picked = set(
            sorted(cell_ids, key=lambda cid: (-corridor_scores[cid], -rem[cid], cid))[:AREA_CELLS]
        )
        corridor_rate = len(flooded & corridor_picked) / n_flooded

        # Random floor: mean of 200 draws of 347 random cells from SF's 4,340 cells.
        flooded_idx = {id_to_idx[cid] for cid in flooded}
        draw_hits = 0
        for _ in range(RANDOM_DRAWS):
            sample = rng.sample(sf_universe, AREA_CELLS)
            draw_hits += len(flooded_idx.intersection(sample))
        random_rate = draw_hits / (RANDOM_DRAWS * n_flooded)

        raw_corridor.append(corridor_rate)
        raw_baseline.append(baseline_rate)
        raw_random.append(random_rate)

        per_storm.append(
            {
                "date": storm_date,
                "flooded_cells": n_flooded,
                "corridor": round(corridor_rate, 4),
                "baseline": round(baseline_rate, 4),
                "random": round(random_rate, 4),
            }
        )

    n_eval = len(per_storm)
    mean_corridor = sum(raw_corridor) / n_eval if n_eval else 0.0
    mean_baseline = sum(raw_baseline) / n_eval if n_eval else 0.0
    mean_random = sum(raw_random) / n_eval if n_eval else 0.0

    worst = min(per_storm, key=lambda row: (row["corridor"], row["date"])) if per_storm else {"date": "", "corridor": 0.0}
    best = max(per_storm, key=lambda row: (row["corridor"], row["date"])) if per_storm else {"date": "", "corridor": 0.0}

    one_liner = (
        f"Across {n_eval} past storms, flood memory chosen before each storm "
        f"caught {mean_corridor * 100:.1f}% of flooded blocks at {int(round(AREA_PCT * 100))}% "
        f"of the city (random: {mean_random * 100:.1f}%)."
    )

    return {
        "n_storms": n_eval,
        "area_cells": AREA_CELLS,
        "area_pct": AREA_PCT,
        "mean_caught": {
            "corridor": round(mean_corridor, 4),
            "baseline": round(mean_baseline, 4),
            "random": round(mean_random, 4),
        },
        "per_storm": per_storm,
        "worst_storm": {"date": worst["date"], "corridor": worst["corridor"]},
        "best_storm": {"date": best["date"], "corridor": best["corridor"]},
        "caveat": CAVEAT,
        "one_liner": one_liner,
    }


def _print_report(result: dict[str, Any], elapsed_s: float) -> None:
    print(f"{'Date':<12} {'Flooded':>8} {'Corridor':>10} {'Baseline':>10} {'Random':>10}")
    print("-" * 54)
    for row in result["per_storm"]:
        print(
            f"{row['date']:<12} {row['flooded_cells']:>8d} "
            f"{row['corridor'] * 100:>9.1f}% "
            f"{row['baseline'] * 100:>9.1f}% "
            f"{row['random'] * 100:>9.1f}%"
        )
    print("-" * 54)
    mc = result["mean_caught"]
    print(
        f"{'MEAN':<12} {'':>8} "
        f"{mc['corridor'] * 100:>9.1f}% "
        f"{mc['baseline'] * 100:>9.1f}% "
        f"{mc['random'] * 100:>9.1f}%"
    )
    print()
    print(result["one_liner"])
    print(f"Best storm:  {result['best_storm']['date']} ({result['best_storm']['corridor'] * 100:.1f}%)")
    print(f"Worst storm: {result['worst_storm']['date']} ({result['worst_storm']['corridor'] * 100:.1f}%)")
    print(f"Caveat: {result['caveat']}")
    print(f"Wrote {OUT_PATH} in {elapsed_s:.2f}s")


def main() -> None:
    n_storms = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    t0 = time.perf_counter()
    result = run(n_storms=n_storms)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    elapsed_s = time.perf_counter() - t0
    _print_report(result, elapsed_s)


if __name__ == "__main__":
    main()
