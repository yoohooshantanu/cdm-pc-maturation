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
import sqlite3
import numpy as np
import scipy.stats as stats
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration & Thresholds
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
INPUT_PATH = DATA_DIR / "sequences_clean.json"

# Threshold for classifying total change along the line of best fit as 'Flat'
# A change of 0.02 in log10(Pc) is roughly a 4.7% relative change.
TOTAL_CHANGE_EPSILON = 0.02

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

def get_archetype(sat1: dict, sat2: dict) -> str:
    t1 = (sat1.get("type") or "UNKNOWN").upper()
    t2 = (sat2.get("type") or "UNKNOWN").upper()
    n1 = (sat1.get("name") or "").upper()
    n2 = (sat2.get("name") or "").upper()
    
    types = {t1, t2}
    names = {n1, n2}
    
    is_mega = any(brand in name for name in names for brand in ["STARLINK", "ONEWEB", "IRIDIUM"])
    
    if "PAYLOAD" in types and "DEBRIS" in types:
        return "CONSTELLATION-DEBRIS" if is_mega else "STANDARD PAYLOAD-DEBRIS"
    elif types == {"DEBRIS"}:
        return "DEBRIS-DEBRIS"
    elif types == {"PAYLOAD"}:
        return "CONSTELLATION-CONSTELLATION" if is_mega else "STANDARD PAYLOAD-PAYLOAD"
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
            "m3_updates_to_stable": [], "m3_never_stable": 0, "m3_hours_to_stable": [],
            "m4_total": 0,
            "dilution_points": [] # (delta_min_rng, delta_log_pc)
        },
        "archetypes": {},
        "space_weather": {
            "high_solar": {"stability_deltas": []},
            "low_solar": {"stability_deltas": []}
        }
    }
    
    # Load Space Weather Dict
    db_path = Path(__file__).resolve().parent / "data" / "cache.db"
    f107_map = {}
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date_str, f107 FROM space_weather")
            for row in cursor.fetchall():
                f107_map[row[0]] = float(row[1])
    except Exception as e:
        log.warning("Could not load space weather data: %s", e)

    for seq in sequences:
        if len(seq["sequence"]) < 3:
            continue

        arch = get_archetype(seq["sat_1"], seq["sat_2"])
        if arch not in results["archetypes"]:
            results["archetypes"][arch] = {
                "total": 0, "flat": 0, "correct": 0, "incorrect": 0, "stability_deltas": [],
                "m1_inc": 0, "m1_dec": 0, "m1_flat": 0,
                "m2_monotonic": 0, "m2_spike": 0, "m2_oscillation": 0,
                "m3_updates_to_stable": [], "m3_never_stable": 0, "m3_hours_to_stable": [],
                "m4_total": 0,
                "dilution_points": []
            }

        cdms = seq["sequence"]
        pcs = [c["pc"] or 0.0 for c in cdms]
        rngs = [c.get("miss_distance") for c in cdms]
        
        # Calculate Average F10.7 during this sequence
        f107_vals = []
        for c in cdms:
            dt = parse_dt(c["created"])
            date_str = dt.strftime("%Y-%m-%d")
            if date_str in f107_map:
                f107_vals.append(f107_map[date_str])
        
        avg_f107 = np.mean(f107_vals) if f107_vals else 0.0
        
        # -------------------------------------------------------------------
        # Metric 1: Direction of Change (Final vs Initial)
        # -------------------------------------------------------------------
        p_init = pcs[0]
        p_final = pcs[-1]
        
        diff_1 = p_final - p_init
        if p_final > p_init * 1.05 and diff_1 > 1e-8:
            m1_dir = "m1_inc"
        elif p_final < p_init * 0.95 and diff_1 < -1e-8:
            m1_dir = "m1_dec"
        else:
            m1_dir = "m1_flat"

        # -------------------------------------------------------------------
        # Metric 2: Evolution Shape
        # -------------------------------------------------------------------
        sign_changes = 0
        current_dir = 0
        last_pc = pcs[0]
        
        for i in range(1, len(pcs)):
            diff = pcs[i] - last_pc
            if abs(diff) < max(last_pc, 1e-12) * 0.05 or abs(diff) < 1e-8:
                continue
                
            step_dir = 1 if diff > 0 else -1
            if current_dir != 0 and step_dir != current_dir:
                sign_changes += 1
            current_dir = step_dir
            last_pc = pcs[i]

        if sign_changes == 0:
            m2_shape = "m2_monotonic"
        elif sign_changes == 1:
            m2_shape = "m2_spike"
        else:
            m2_shape = "m2_oscillation"

        # -------------------------------------------------------------------
        # Metric 3: Stabilization
        # -------------------------------------------------------------------
        stable_idx = None
        for i in range(len(pcs)):
            is_stable_from_here = True
            for j in range(i+1, len(pcs)):
                diff_3 = abs(pcs[j] - pcs[i])
                rel_change = diff_3 / max(pcs[i], 1e-12)
                if rel_change >= 0.10 and diff_3 > 1e-8:
                    is_stable_from_here = False
                    break
            
            if is_stable_from_here:
                stable_idx = i
                break
                
        # -------------------------------------------------------------------
        # Metric 6: Covariance Dilution (Pc vs Miss Distance)
        # -------------------------------------------------------------------
        for i in range(1, len(pcs)):
            if rngs[i] is not None and rngs[i-1] is not None:
                d_rng = rngs[i] - rngs[i-1]
                d_pc = safe_log10(pcs[i]) - safe_log10(pcs[i-1])
                for target in [results["overall"], results["archetypes"][arch]]:
                    target["dilution_points"].append((d_rng, d_pc))

        # -------------------------------------------------------------------
        # Metric 4 & 5 (Original)
        # -------------------------------------------------------------------
        deltas = []
        for i in range(1, len(pcs)):
            rel = abs(safe_log10(pcs[i]) - safe_log10(pcs[i-1]))
            deltas.append(rel)
        mean_delta = np.mean(deltas) if deltas else 0.0

        if deltas:
            if avg_f107 >= 120.0:
                results["space_weather"]["high_solar"]["stability_deltas"].extend(deltas)
            elif avg_f107 > 0:
                results["space_weather"]["low_solar"]["stability_deltas"].extend(deltas)
                
        early = cdms[:3]
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
            total_change = 0.0
        else:
            slope, _ = np.polyfit(x, y, 1)
            total_change = slope * (max(x) - min(x))

        if total_change > TOTAL_CHANGE_EPSILON:
            pred_dir = "INCREASING"
        elif total_change < -TOTAL_CHANGE_EPSILON:
            pred_dir = "DECREASING"
        else:
            pred_dir = "FLAT"

        diff_act = p_final - p_init
        if p_final > p_init * 1.05 and diff_act > 1e-8:
            actual_dir = "INCREASING"
        elif p_final < p_init * 0.95 and diff_act < -1e-8:
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
                target["m3_updates_to_stable"].append(stable_idx + 1)
                
                tca_dt = parse_dt(cdms[stable_idx]["tca"])
                created_dt = parse_dt(cdms[stable_idx]["created"])
                hours = (tca_dt - created_dt).total_seconds() / 3600.0
                if hours > 0:
                    target["m3_hours_to_stable"].append(hours)
            else:
                target["m3_never_stable"] += 1

            if len(pcs) > 3:
                target["m4_total"] += 1
                if pred_dir == "FLAT":
                    target["flat"] += 1
                else:
                    if pred_dir == actual_dir:
                        target["correct"] += 1
                    else:
                        target["incorrect"] += 1

    return results

def print_report(results: dict):
    def format_stats(data: dict, name: str, constellation_deltas=None, standard_deltas=None, debris_deltas=None):
        if data["total"] == 0:
            return
        
        # M4 & 5
        flat = data["flat"]
        correct = data["correct"]
        incorrect = data["incorrect"]
        scored = correct + incorrect
        m4_tot = data.get("m4_total", data["total"])
        
        flat_rate = (flat / m4_tot) * 100 if m4_tot > 0 else 0.0
        acc = (correct / scored * 100) if scored > 0 else 0.0
        mean_stab = np.mean(data["stability_deltas"]) if data["stability_deltas"] else 0.0

        # M1
        pct_inc = (data["m1_inc"] / data["total"]) * 100
        pct_dec = (data["m1_dec"] / data["total"]) * 100
        pct_flat = (data["m1_flat"] / data["total"]) * 100
        
        # M2
        pct_mono = (data["m2_monotonic"] / data["total"]) * 100
        pct_spike = (data["m2_spike"] / data["total"]) * 100
        pct_osc = (data["m2_oscillation"] / data["total"]) * 100
        
        # M3
        m3_list = data["m3_updates_to_stable"]

        print(f"--- {name} ---")
        print(f"Total sequences evaluated: {data['total']}")
        
        print(f"\n[Metric 1] Direction of Change (Final vs Initial):")
        print(f"  Increasing: {pct_inc:.1f}%")
        print(f"  Decreasing: {pct_dec:.1f}%")
        print(f"  Flat:       {pct_flat:.1f}%")
        
        print(f"\n[Metric 2] Evolution Shape:")
        print(f"  Monotonic:   {pct_mono:.1f}%")
        print(f"  Spike/Dip:   {pct_spike:.1f}%")
        print(f"  Oscillation: {pct_osc:.1f}%")
        
        print(f"\n[Metric 3] Stabilization (<10% change):")
        if data["m3_updates_to_stable"]:
            med = np.median(data["m3_updates_to_stable"])
            mn = np.mean(data["m3_updates_to_stable"])
            med_hrs = np.median(data["m3_hours_to_stable"]) if data["m3_hours_to_stable"] else 0.0
            print(f"  Updates until stable: median={med:.0f}, mean={mn:.1f}")
            print(f"  T-Minus time at stable: median {med_hrs:.1f} hours to TCA")
        print(f"  Never stabilized:     {data['m3_never_stable'] / data['total'] * 100:.1f}%")
        
        print(f"\n[Metric 4] Early Prediction (First 3 CDMs):")
        print(f"  Flat rate (ignored from accuracy): {flat_rate:.1f}% ({flat})")
        print(f"  Prediction Accuracy (on {scored} non-flat): {acc:.1f}%")
        
        print(f"\n[Metric 5] Stability:")
        print(f"  Mean consecutive volatility (Delta log10 Pc): {mean_stab:.2f}")
        
        if name == "CONSTELLATION-DEBRIS" and constellation_deltas and standard_deltas:
            _, p_val = stats.mannwhitneyu(constellation_deltas, standard_deltas, alternative='greater')
            print(f"  * Statistical Significance vs Standard Payloads: p-value = {p_val:.4e} (Mann-Whitney U)")
            if debris_deltas:
                _, p_val2 = stats.mannwhitneyu(constellation_deltas, debris_deltas, alternative='greater')
                print(f"  * Statistical Significance vs Debris: p-value = {p_val2:.4e} (Mann-Whitney U)")
            
        print("")
        
        # Format Dilution Correlation
        if data["dilution_points"]:
            dr = [p[0] for p in data["dilution_points"]]
            dpc = [p[1] for p in data["dilution_points"]]
            if len(dr) > 2:
                r, p_corr = stats.pearsonr(dr, dpc)
                print(f"[Metric 6] Dilution Region Effect:")
                print(f"  Pearson Correlation (Delta min_rng vs Delta log10 Pc): {r:.3f} (p={p_corr:.3e})\n")

    print("=" * 60)
    print("PHASE 3: PC MATURATION ANALYSIS")
    print("============================================================")
    
    constellation_deltas = results["archetypes"].get("CONSTELLATION-DEBRIS", {}).get("stability_deltas", [])
    standard_deltas = results["archetypes"].get("STANDARD PAYLOAD-DEBRIS", {}).get("stability_deltas", [])
    debris_deltas = results["archetypes"].get("DEBRIS-DEBRIS", {}).get("stability_deltas", [])
    
    format_stats(results["overall"], "OVERALL DATASET", constellation_deltas, standard_deltas, debris_deltas)

    for arch, data in results["archetypes"].items():
        format_stats(data, arch, constellation_deltas, standard_deltas, debris_deltas)
        
    print("============================================================")
    print("PHASE 4: SPACE WEATHER CORRELATION")
    print("============================================================")
    high = results["space_weather"]["high_solar"]["stability_deltas"]
    low = results["space_weather"]["low_solar"]["stability_deltas"]
    
    mean_high = np.mean(high) if high else 0.0
    mean_low = np.mean(low) if low else 0.0
    
    print(f"High Solar Activity (F10.7 >= 120) Volatility : {mean_high:.3f}")
    print(f"Low Solar Activity  (F10.7 < 120)  Volatility : {mean_low:.3f}")
    
    if high and low:
        _, p_val = stats.mannwhitneyu(high, low, alternative='greater')
        print(f"Statistical Significance (High > Low): p-value = {p_val:.4e} (Mann-Whitney U)")
    print("============================================================\n")

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
