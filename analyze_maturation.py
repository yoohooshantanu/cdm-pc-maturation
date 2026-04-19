"""
Phase 3 — Analysis & Maturation Patterns

Calculates Metric 4 (Early prediction accuracy using log-linear regression)
and Metric 5 (Object type comparison for stability and predictability).

Usage:
    python analyze_maturation.py
"""

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Configuration & Thresholds
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
INPUT_PATH = DATA_DIR / "sequences_clean.json"

# Threshold for classifying slope as 'Flat'
# Since we are regressing log10(Pc) vs time in hours,
# a slope of 0.01 means a 10^0.01 = 2.3% change in Pc per hour.
SLOPE_EPSILON = 0.01

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_dt(s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Could not parse date: {s}")

def get_archetype(t1: str, t2: str) -> str:
    types = {t1.upper(), t2.upper()}
    if "PAYLOAD" in types and "DEBRIS" in types:
        return "PAYLOAD-DEBRIS"
    elif types == {"DEBRIS"}:
        return "DEBRIS-DEBRIS"
    elif types == {"PAYLOAD"}:
        return "PAYLOAD-PAYLOAD"
    return "OTHER"

def safe_log10(val: float) -> float:
    """Return log10 of Pc, clamping at 1e-12 to avoid math domain errors."""
    return math.log10(max(val, 1e-12))

# ---------------------------------------------------------------------------
# Analysis Logic
# ---------------------------------------------------------------------------
def analyze_sequences(sequences: list[dict]) -> dict:
    results = {
        "overall": {
            "total": 0, 
            "flat": 0, 
            "correct": 0, 
            "incorrect": 0, 
            "stability_deltas": [],
            "m1_inc": 0, "m1_dec": 0, "m1_flat": 0,
            "m2_monotonic": 0, "m2_spike": 0, "m2_oscillation": 0,
            "m3_updates_to_stable": [], "m3_never_stable": 0
        },
        "archetypes": {}
    }

    for seq in sequences:
        if len(seq["sequence"]) < 3:
            continue

        arch = get_archetype(seq["sat_1"]["type"], seq["sat_2"]["type"])
        if arch not in results["archetypes"]:
            results["archetypes"][arch] = {
                "total": 0, "flat": 0, "correct": 0, "incorrect": 0, "stability_deltas": [],
                "m1_inc": 0, "m1_dec": 0, "m1_flat": 0,
                "m2_monotonic": 0, "m2_spike": 0, "m2_oscillation": 0,
                "m3_updates_to_stable": [], "m3_never_stable": 0
            }

        cdms = seq["sequence"]
        pcs = [c["pc"] or 0.0 for c in cdms]
        
        # -------------------------------------------------------------------
        # Metric 1: Direction of Change (Final vs Initial)
        # -------------------------------------------------------------------
        p_init = pcs[0]
        p_final = pcs[-1]
        
        if p_final > p_init * 1.05:
            m1_dir = "m1_inc"
        elif p_final < p_init * 0.95:
            m1_dir = "m1_dec"
        else:
            m1_dir = "m1_flat"

        # -------------------------------------------------------------------
        # Metric 2: Evolution Shape
        # -------------------------------------------------------------------
        # Calculate sign changes in consecutive differences
        sign_changes = 0
        current_dir = 0
        
        for i in range(1, len(pcs)):
            diff = pcs[i] - pcs[i-1]
            # Ignore tiny floating point changes (e.g. < 5% relative change)
            if abs(diff) < max(pcs[i-1], 1e-12) * 0.05:
                continue
                
            step_dir = 1 if diff > 0 else -1
            if current_dir != 0 and step_dir != current_dir:
                sign_changes += 1
            current_dir = step_dir

        if sign_changes == 0:
            m2_shape = "m2_monotonic"
        elif sign_changes == 1:
            m2_shape = "m2_spike" # spike or dip
        else:
            m2_shape = "m2_oscillation"

        # -------------------------------------------------------------------
        # Metric 3: Stabilization
        # -------------------------------------------------------------------
        # Stable = all subsequent changes are < 10%
        stable_idx = None
        for i in range(len(pcs)):
            is_stable_from_here = True
            for j in range(i+1, len(pcs)):
                rel_change = abs(pcs[j] - pcs[j-1]) / max(pcs[j-1], 1e-12)
                if rel_change >= 0.10:
                    is_stable_from_here = False
                    break
            
            if is_stable_from_here:
                stable_idx = i
                break
                
        # -------------------------------------------------------------------
        # Metric 4 & 5 (Original)
        # -------------------------------------------------------------------
        deltas = []
        for i in range(1, len(pcs)):
            deltas.append(abs(pcs[i] - pcs[i-1]))
        mean_delta = np.mean(deltas) if deltas else 0.0

        early = cdms[:3]
        early_pcs = pcs[:3]
        
        t0 = parse_dt(early[0]["created"])
        x = []
        y = []
        for c in early:
            dt = parse_dt(c["created"])
            hours = (dt - t0).total_seconds() / 3600.0
            x.append(hours)
            y.append(safe_log10(c["pc"] or 0.0))

        if max(x) - min(x) < 1e-6:
            slope = 0.0
        else:
            slope, _ = np.polyfit(x, y, 1)

        if slope > SLOPE_EPSILON:
            pred_dir = "INCREASING"
        elif slope < -SLOPE_EPSILON:
            pred_dir = "DECREASING"
        else:
            pred_dir = "FLAT"

        early_mean = np.mean(early_pcs)
        if p_final > early_mean * 1.05:
            actual_dir = "INCREASING"
        elif p_final < early_mean * 0.95:
            actual_dir = "DECREASING"
        else:
            actual_dir = "FLAT"

        # -------------------------------------------------------------------
        # Store Results
        # -------------------------------------------------------------------
        for target in [results["overall"], results["archetypes"][arch]]:
            target["total"] += 1
            target["stability_deltas"].append(mean_delta)
            target[m1_dir] += 1
            target[m2_shape] += 1
            
            if stable_idx is not None and stable_idx < len(pcs) - 1:
                target["m3_updates_to_stable"].append(stable_idx)
            else:
                target["m3_never_stable"] += 1

            if pred_dir == "FLAT":
                target["flat"] += 1
            else:
                if pred_dir == actual_dir:
                    target["correct"] += 1
                else:
                    target["incorrect"] += 1

    return results

def print_report(results: dict):
    def format_stats(data: dict, name: str):
        total = data["total"]
        if total == 0:
            return
        
        # M4 & 5
        flat = data["flat"]
        correct = data["correct"]
        incorrect = data["incorrect"]
        scored = correct + incorrect
        
        flat_rate = (flat / total) * 100
        acc = (correct / scored * 100) if scored > 0 else 0.0
        mean_stab = np.mean(data["stability_deltas"]) if data["stability_deltas"] else 0.0

        # M1
        pct_inc = (data["m1_inc"] / total) * 100
        pct_dec = (data["m1_dec"] / total) * 100
        pct_flat = (data["m1_flat"] / total) * 100
        
        # M2
        pct_mono = (data["m2_monotonic"] / total) * 100
        pct_spike = (data["m2_spike"] / total) * 100
        pct_osc = (data["m2_oscillation"] / total) * 100
        
        # M3
        m3_list = data["m3_updates_to_stable"]
        med_stable = np.median(m3_list) if m3_list else 0
        pct_never = (data["m3_never_stable"] / total) * 100

        print(f"--- {name} ---")
        print(f"Total sequences evaluated: {total}")
        
        print(f"\n[Metric 1] Direction of Change (Final vs Initial):")
        print(f"  Increasing: {pct_inc:.1f}%")
        print(f"  Decreasing: {pct_dec:.1f}%")
        print(f"  Flat:       {pct_flat:.1f}%")
        
        print(f"\n[Metric 2] Evolution Shape:")
        print(f"  Monotonic:   {pct_mono:.1f}%")
        print(f"  Spike/Dip:   {pct_spike:.1f}%")
        print(f"  Oscillation: {pct_osc:.1f}%")
        
        print(f"\n[Metric 3] Stabilization (<10% change):")
        if m3_list:
            print(f"  Updates until stable: median={med_stable:.0f}, mean={np.mean(m3_list):.1f}")
        print(f"  Never stabilized:     {pct_never:.1f}%")
        
        print(f"\n[Metric 4] Early Prediction (First 3 CDMs):")
        print(f"  Flat rate (ignored from accuracy): {flat_rate:.1f}% ({flat})")
        print(f"  Prediction Accuracy (on {scored} non-flat): {acc:.1f}%")
        
        print(f"\n[Metric 5] Stability:")
        print(f"  Mean consecutive Pc delta: {mean_stab:.2e}\n")

    print("=" * 60)
    print("PHASE 3: PC MATURATION ANALYSIS")
    print("=" * 60)
    
    format_stats(results["overall"], "OVERALL DATASET")

    for arch, data in results["archetypes"].items():
        if data["total"] > 10:
            format_stats(data, arch)

def main():
    if not INPUT_PATH.exists():
        log.error("Input file not found: %s", INPUT_PATH)
        return

    with open(INPUT_PATH) as f:
        sequences = json.load(f)
    
    log.info("Loaded %d sequences from %s", len(sequences), INPUT_PATH.name)
    results = analyze_sequences(sequences)
    print_report(results)

if __name__ == "__main__":
    main()
