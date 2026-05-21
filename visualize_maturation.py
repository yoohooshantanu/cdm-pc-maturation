"""
Phase 4 — Visualizations

Creates 5 minimal, clean charts based on the Pc Maturation analysis.
Saves them to the artifact directory.
"""

import json
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import scipy.stats as stats

# Import our existing analysis engine to get the exact same numbers
from analyze_maturation import analyze_sequences

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "sequences_clean.json"
# Save directly to the project output directory
# OUT_DIR is removed to avoid hardcoded paths

def set_style():
    """Set a clean, premium, non-default styling for all plots."""
    sns.set_theme(style="white", context="talk")
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.edgecolor"] = "#DDDDDD"
    plt.rcParams["axes.linewidth"] = 1.0
    plt.rcParams["axes.spines.top"] = False
    plt.rcParams["axes.spines.right"] = False
    plt.rcParams["axes.grid"] = True
    plt.rcParams["axes.grid.axis"] = "y"
    plt.rcParams["grid.color"] = "#EEEEEE"
    plt.rcParams["grid.linestyle"] = "--"
    plt.rcParams["axes.titleweight"] = "bold"
    plt.rcParams["axes.labelcolor"] = "#666666"
    plt.rcParams["xtick.color"] = "#666666"
    plt.rcParams["ytick.color"] = "#666666"
    plt.rcParams["text.color"] = "#222222"

def save_plot(filename):
    """Save the plot to both the artifact directory and the project output directory."""
    plt.tight_layout()
    # Save to artifact dir is removed to avoid hardcoded paths
    
    # Save to project workspace output/charts
    project_out = BASE_DIR / "output" / "charts"
    project_out.mkdir(parents=True, exist_ok=True)
    plt.savefig(project_out / filename, dpi=300, bbox_inches='tight')
    plt.close()

def plot_1_trajectories(sequences):
    """Chart 1: Sample Pc trajectories (highlight 3 shapes)."""
    plt.figure(figsize=(10, 6))
    
    samples = [seq for seq in sequences if len(seq["sequence"]) >= 5][:20]
    
    found_mono = False
    found_osc = False
    found_spike = False
    
    for seq in samples:
        raw_pcs = [c["pc"] or 0.0 for c in seq["sequence"]]
        y = np.log10([max(pc, 1e-12) for pc in raw_pcs])
        x = np.arange(1, len(y) + 1)
        
        sign_changes = 0
        current_dir = 0
        last_pc = raw_pcs[0]
        for i in range(1, len(raw_pcs)):
            diff = raw_pcs[i] - last_pc
            if abs(diff) < max(last_pc, 1e-12) * 0.05 or abs(diff) < 1e-8: continue
            step_dir = 1 if diff > 0 else -1
            if current_dir != 0 and step_dir != current_dir: sign_changes += 1
            current_dir = step_dir
            last_pc = raw_pcs[i]
            
        highlight = False
        color = '#BDBDBD'
        alpha = 0.2
        label = None
        zorder = 1
        lw = 1.0
        
        if sign_changes == 0 and not found_mono:
            highlight, found_mono = True, True
            color, alpha, label, zorder, lw = '#2A9D8F', 1.0, "Monotonic", 3, 2.5
        elif sign_changes == 1 and not found_spike:
            highlight, found_spike = True, True
            color, alpha, label, zorder, lw = '#E63946', 1.0, "Spike/Dip", 3, 2.5
        elif sign_changes > 1 and not found_osc:
            highlight, found_osc = True, True
            color, alpha, label, zorder, lw = '#F4A261', 1.0, "Oscillating", 3, 2.5
            
        plt.plot(x, y, marker='o' if highlight else None, markersize=5 if highlight else 0, 
                 color=color, alpha=alpha, linewidth=lw, label=label, zorder=zorder)
        
    plt.suptitle("Sample Pc Trajectories", weight="bold", fontsize=18, y=1.02)
    plt.title("log10(Pc) evolution across CDM updates (N=648 sequences)", pad=15, fontsize=14)
    plt.xlabel("CDM Update Number")
    plt.ylabel("log10(Probability of Collision)")
    plt.xlim(0.5, 20.5) 
    plt.legend(title="Highlighted Archetypes")
    save_plot("chart1_trajectories.png")

def plot_2_direction(results):
    """Chart 2: Direction distribution bar chart."""
    plt.figure(figsize=(8, 6))
    
    overall = results["overall"]
    total = overall["total"]
    
    labels = ['Increasing', 'Decreasing', 'Flat (<5% change)']
    values = [
        overall["m1_inc"] / total * 100,
        overall["m1_dec"] / total * 100,
        overall["m1_flat"] / total * 100
    ]
    colors = ['#E63946', '#2A9D8F', '#A8DADC']
    
    bars = plt.bar(labels, values, color=colors, width=0.6)
    
    plt.title("Final Collision Risk Increases in Majority of Events\n(N=648 sequences)", pad=20, weight="bold")
    plt.ylabel("Percentage of Events (%)")
    plt.ylim(0, 70)
    
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, yval + 1, f"{yval:.1f}%", ha='center', va='bottom', weight="bold")
        
    save_plot("chart2_direction.png")

def plot_3_stabilization(results):
    """Chart 3: Stabilization histogram (# updates to stabilize)."""
    plt.figure(figsize=(10, 6))
    
    overall = results["overall"]
    updates = overall["m3_updates_to_stable"]
    pct_never = overall["m3_never_stable"] / overall["total"] * 100
    
    sns.histplot(updates, discrete=True, color="#457B9D", alpha=0.8)
    
    plt.title("Updates Required for Pc to Stabilize (<10% change) (N=648 sequences)", pad=20, weight="bold")
    plt.xlabel("Number of Updates")
    plt.ylabel("Frequency (Count of Events)")
    
    median = np.median(updates) if updates else 0
    plt.axvline(median, color='#E63946', linestyle='--', linewidth=2, label=f'Median: {median:.0f}')
    
    plt.text(10, plt.gca().get_ylim()[1]*0.8, f"Warning: {pct_never:.1f}% never stabilize\nprior to TCA.", 
             fontsize=14, weight="bold", color="#E63946",
             bbox=dict(facecolor='#FFF0F0', edgecolor='#E63946', boxstyle='round,pad=0.5'))
             
    plt.legend(loc='upper right')
    
    save_plot("chart3_stabilization.png")

def plot_4_prediction(results):
    """Chart 4: Prediction accuracy (MAIN CHART)."""
    plt.figure(figsize=(10, 6.5))
    
    overall = results["overall"]
    scored = overall["correct"] + overall["incorrect"]
    m4_tot = overall.get("m4_total", overall["total"])
    
    acc = overall["correct"] / scored * 100 if scored > 0 else 0
    inacc = overall["incorrect"] / scored * 100 if scored > 0 else 0
    flat_rate = overall["flat"] / m4_tot * 100 if m4_tot > 0 else 0.0
    has_signal = 100.0 - flat_rate
    
    labels = [f'Accurate Prediction\n({acc:.0f}% of signal events, n={scored})', 'Incorrectly Predicted', 'Flat Early Signal\n(No prediction made)']
    
    pct_correct = (overall["correct"] / m4_tot) * 100 if m4_tot > 0 else 0.0
    pct_incorrect = (overall["incorrect"] / m4_tot) * 100 if m4_tot > 0 else 0.0
    
    values = [pct_correct, pct_incorrect, flat_rate]
    colors = ['#2A9D8F', '#E63946', '#BDBDBD']
    
    bars = plt.barh(labels[::-1], values[::-1], color=colors[::-1], height=0.6)
    
    plt.suptitle("Early Prediction Power (Using First 3 CDMs)", weight="bold", fontsize=18, y=1.02)
    plt.title(f"Early CDM trends are predictive — but only present in {has_signal:.0f}% of events\n(N=648 sequences)", fontsize=14, pad=15)
    
    plt.xlabel("Percentage of All Events (%)")
    plt.xlim(0, 60)
    
    for bar in bars:
        width = bar.get_width()
        plt.text(width + 1, bar.get_y() + bar.get_height()/2, f"{width:.1f}%", ha='left', va='center', weight="bold")
        
    plt.text(45, 1.0, f"Accuracy = {acc:.1f}%\n(vs Naive Base Rate: 55.6%)", 
             fontsize=14, weight="bold", color="#1D3557",
             ha='center', va='center',
             bbox=dict(facecolor='#F1FAEE', edgecolor='#A8DADC', boxstyle='round,pad=0.5'))
             
    plt.figtext(0.5, -0.05, f"Early signals are absent in ~{flat_rate:.0f}% of events; however, when present, they are predictive ({acc:.0f}% accuracy).", 
                ha="center", fontsize=12, style='italic', color='#457B9D', weight='bold', wrap=True)
                
    save_plot("chart4_prediction.png")

def plot_5_archetypes(results):
    """Chart 5: Object type comparison (Volatility Bar Chart)."""
    plt.figure(figsize=(10, 6))
    
    archs = ["CONSTELLATION-DEBRIS", "STANDARD PAYLOAD-DEBRIS", "DEBRIS-DEBRIS"]
    labels = ["Mega-Constellation\nvs Debris", "Standard Payload\nvs Debris", "Debris\nvs Debris"]
    
    means = []
    sems = []
    for a in archs:
        deltas = results["archetypes"].get(a, {}).get("stability_deltas", [])
        means.append(np.mean(deltas) if deltas else 0.0)
        sems.append(stats.sem(deltas) if len(deltas) > 1 else 0.0)
    
    x = np.arange(len(labels))
    colors = ['#E63946', '#2A9D8F', '#A8DADC']
    
    bars = plt.bar(x, means, yerr=sems, capsize=5, width=0.6, color=colors)
    
    plt.suptitle("Active Satellites Introduce Significant Instability", weight="bold", fontsize=16, y=1.02)
    plt.title("Conjunction Volatility by Object Type (N=648 sequences)", pad=15)
    plt.ylabel("Mean Volatility (Delta log10 Pc)")
    plt.xticks(x, labels)
    
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, yval + 0.005, f"{yval:.2f}", 
                 ha='center', va='bottom', weight='bold')
    
    # Overlay p-value
    const_deltas = results["archetypes"].get("CONSTELLATION-DEBRIS", {}).get("stability_deltas", [])
    std_deltas = results["archetypes"].get("STANDARD PAYLOAD-DEBRIS", {}).get("stability_deltas", [])
    
    if const_deltas and std_deltas:
        _, p_val = stats.mannwhitneyu(const_deltas, std_deltas, alternative='greater')
        if p_val < 0.01:
            p_text = "p < 0.01"
        else:
            p_text = f"p = {p_val:.2f}"
            
        plt.text(1.0, max(means) * 0.9, f"Constellation vs Standard:\n{p_text}", 
                 ha='center', va='center', fontsize=12, weight='bold', color='#1D3557',
                 bbox=dict(facecolor='#F1FAEE', edgecolor='#1D3557', boxstyle='round,pad=0.5'))
                 
    plt.ylim(0, max(means) * 1.3)
    save_plot("chart5_archetypes.png")

def plot_6_flowchart(results):
    """Chart 6: Operator Decision Flow (Flowchart)."""
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.axis('off')
    
    box_style = dict(boxstyle="round,pad=0.5", facecolor="#F1FAEE", edgecolor="#1D3557", lw=2)
    decision_style = dict(boxstyle="round,pad=0.8", facecolor="#A8DADC", edgecolor="#1D3557", lw=2)
    inc_style = dict(boxstyle="round,pad=0.5", facecolor="#FFD6D6", edgecolor="#E63946", lw=2)
    dec_style = dict(boxstyle="round,pad=0.5", facecolor="#D6FFD6", edgecolor="#2A9D8F", lw=2)
    flat_style = dict(boxstyle="round,pad=0.5", facecolor="#E0E0E0", edgecolor="#808080", lw=2)
    
    overall = results["overall"]
    scored = overall["correct"] + overall["incorrect"]
    acc = overall["correct"] / scored * 100 if scored > 0 else 0
    m4_tot = overall.get("m4_total", overall["total"])
    flat_rate = overall["flat"] / m4_tot * 100 if m4_tot > 0 else 0.0

    nodes = {
        'A': {'text': 'Initial CDM Received', 'pos': (0.5, 0.9), 'style': box_style},
        'B': {'text': 'Wait for 3 CDMs', 'pos': (0.5, 0.7), 'style': box_style},
        'C': {'text': 'Does a clear\ntrend exist?', 'pos': (0.5, 0.45), 'style': decision_style},
        'D': {'text': f'Increasing Trend\n↓\nElevated Risk Signal →\nConsider Maneuver\n({acc:.0f}% directional reliability)', 'pos': (0.15, 0.1), 'style': inc_style},
        'E': {'text': f'Decreasing Trend\n↓\nMonitor Closely\n({acc:.0f}% directional reliability)', 'pos': (0.5, 0.1), 'style': dec_style},
        'F': {'text': 'Flat / Oscillating\n↓\nHold Action\n(Wait for 4th Update)', 'pos': (0.85, 0.1), 'style': flat_style},
    }
    
    for k, v in nodes.items():
        ax.text(v['pos'][0], v['pos'][1], v['text'], ha='center', va='center', 
                fontsize=11, weight='bold', color="#1D3557", bbox=v['style'], zorder=3)
                
    arrow_props = dict(facecolor='#1D3557', edgecolor='#1D3557', width=2, headwidth=8, shrink=0.05)
    
    ax.annotate('', xy=(0.5, 0.75), xytext=(0.5, 0.85), arrowprops=arrow_props, zorder=2)
    ax.annotate('', xy=(0.5, 0.55), xytext=(0.5, 0.65), arrowprops=arrow_props, zorder=2)
    
    ax.annotate('', xy=(0.15, 0.25), xytext=(0.4, 0.4), arrowprops=arrow_props, zorder=2)
    ax.annotate('', xy=(0.5, 0.25), xytext=(0.5, 0.35), arrowprops=arrow_props, zorder=2)
    ax.annotate('', xy=(0.85, 0.25), xytext=(0.6, 0.4), arrowprops=arrow_props, zorder=2)
    
    plt.title("Operator Decision Flow (N=648 sequences)", pad=20, weight="bold", fontsize=18)
    
    # Add bottom footer insight
    plt.text(0.5, -0.05, f"Early signals are absent in ~{flat_rate:.0f}% of events — requiring delayed decisions.",
             ha='center', va='center', fontsize=14, style='italic', color='#457B9D', weight='bold')
             
    plt.tight_layout()
    save_plot("chart6_decision_flow.png")


def plot_7_dilution(results):
    """Chart 7: Covariance Dilution (Scatter of Delta Pc vs Delta Miss Distance)."""
    overall = results["overall"]
    points = overall.get("dilution_points", [])
    if not points:
        return
        
    plt.figure(figsize=(10, 6))
    dr = [p[0] for p in points]
    dpc = [p[1] for p in points]
    
    # Filter extreme outliers for better visualization
    valid_dr = []
    valid_dpc = []
    for r, p in zip(dr, dpc):
        if abs(r) < 5.0 and abs(p) < 4.0: # Exclude jumps > 5km or 4 orders of magnitude
            valid_dr.append(r)
            valid_dpc.append(p)
            
    if not valid_dr:
        return
        
    sns.regplot(x=valid_dr, y=valid_dpc, scatter_kws={'alpha':0.3, 'color':'#457B9D'}, line_kws={'color':'#E63946'})
    
    # Calculate statistics on the FULL dataset to match the analytical findings
    r, p_corr = stats.pearsonr(dr, dpc)
    
    plt.suptitle("Exploratory Observation of Dilution Correlation", weight="bold", fontsize=16, y=1.02)
    plt.title("How Miss Distance Changes Affect Collision Risk (N=648 sequences)", pad=15)
    plt.xlabel("Change in Miss Distance (km)")
    plt.ylabel("Change in log10(Probability)")
    
    plt.axhline(0, color='gray', linestyle='--', linewidth=1)
    plt.axvline(0, color='gray', linestyle='--', linewidth=1)
    
    plt.text(min(valid_dr)*0.9, max(valid_dpc)*0.9, f"Pearson r = {r:.2f}\np = {p_corr:.2e}", 
             ha='left', va='top', fontsize=12, weight='bold', color='#1D3557',
             bbox=dict(facecolor='#F1FAEE', edgecolor='#1D3557', boxstyle='round,pad=0.5'))
             
    save_plot("chart7_dilution.png")


def plot_8_spaceweather(results):
    """Chart 8: Solar Activity Impact on Volatility."""
    sw = results.get("space_weather", {})
    if not sw:
        return
        
    high = sw.get("high_solar", {}).get("stability_deltas", [])
    low = sw.get("low_solar", {}).get("stability_deltas", [])
    
    if not high and not low:
        return
        
    mean_high = np.mean(high) if high else 0.0
    mean_low = np.mean(low) if low else 0.0
    
    sem_high = stats.sem(high) if len(high) > 1 else 0.0
    sem_low = stats.sem(low) if len(low) > 1 else 0.0
    
    plt.figure(figsize=(8, 6))
    
    labels = ["Low Solar Activity\n(F10.7 < 120)", "High Solar Activity\n(F10.7 >= 120)"]
    means = [mean_low, mean_high]
    sems = [sem_low, sem_high]
    colors = ['#A8DADC', '#E63946']
    
    bars = plt.bar([0, 1], means, yerr=sems, capsize=5, color=colors, width=0.6)
    
    plt.suptitle("Solar Activity Shows No Significant Effect on Conjunction Volatility", weight="bold", fontsize=14, y=1.02)
    plt.title("Mean Conjunction Volatility by Space Weather Condition (N=648 sequences)", pad=15)
    plt.ylabel("Mean Volatility (Delta log10 Pc)")
    plt.xticks([0, 1], labels)
    
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, yval + 0.002, f"{yval:.3f}", 
                 ha='center', va='bottom', weight='bold')
                 
    if high and low:
        _, p_val = stats.mannwhitneyu(high, low, alternative='greater')
        if p_val < 0.01:
            p_text = "p < 0.01"
        else:
            p_text = f"p = {p_val:.2f}"
            
        plt.text(0.5, max(means) * 1.15, f"Statistical Significance:\n{p_text}", 
                 ha='center', va='center', fontsize=12, weight='bold', color='#1D3557',
                 bbox=dict(facecolor='#F1FAEE', edgecolor='#1D3557', boxstyle='round,pad=0.5'))
                 
    plt.ylim(0, max(means) * 1.3)
    save_plot("chart8_spaceweather.png")

def main():
    if not INPUT_PATH.exists():
        log.error("Missing %s", INPUT_PATH)
        return
        
    with open(INPUT_PATH) as f:
        sequences = json.load(f)
        
    log.info("Loaded %d sequences. Calculating stats…", len(sequences))
    results = analyze_sequences(sequences)
    
    set_style()
    
    log.info("Generating Chart 1: Trajectories…")
    plot_1_trajectories(sequences)
    
    log.info("Generating Chart 2: Direction…")
    plot_2_direction(results)
    
    log.info("Generating Chart 3: Stabilization…")
    plot_3_stabilization(results)
    
    log.info("Generating Chart 4: Prediction…")
    plot_4_prediction(results)
    
    log.info("Generating Chart 5: Archetypes…")
    plot_5_archetypes(results)
    
    log.info("Generating Chart 6: Decision Flow…")
    plot_6_flowchart(results)
    
    log.info("Generating Chart 7: Dilution Effect…")
    plot_7_dilution(results)
    
    log.info("Generating Chart 8: Space Weather Effect…")
    plot_8_spaceweather(results)
    
    log.info("All visualizations saved to output/charts")

if __name__ == "__main__":
    main()
