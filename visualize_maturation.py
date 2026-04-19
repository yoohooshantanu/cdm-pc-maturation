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

# Import our existing analysis engine to get the exact same numbers
from analyze_maturation import analyze_sequences

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "sequences_clean.json"
# Save directly to the brain directory so artifacts can embed them easily
OUT_DIR = Path(r"C:\Users\satyajit\.gemini\antigravity\brain\b6b7abe2-97d9-4ead-88a1-5472ad92d5fb")

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
    # Save to artifact dir for the walkthrough
    plt.savefig(OUT_DIR / filename, dpi=300, bbox_inches='tight')
    
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
        pcs = [max(c["pc"] or 1e-12, 1e-12) for c in seq["sequence"]]
        y = np.log10(pcs)
        x = np.arange(1, len(y) + 1)
        
        sign_changes = 0
        current_dir = 0
        for i in range(1, len(pcs)):
            diff = pcs[i] - pcs[i-1]
            if abs(diff) < max(pcs[i-1], 1e-12) * 0.05: continue
            step_dir = 1 if diff > 0 else -1
            if current_dir != 0 and step_dir != current_dir: sign_changes += 1
            current_dir = step_dir
            
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
    plt.title("log10(Pc) evolution across CDM updates", pad=15, fontsize=14)
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
    
    plt.title("Final Collision Risk Increases in Majority of Events", pad=20, weight="bold")
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
    
    plt.title("Updates Required for Pc to Stabilize (<10% change)", pad=20, weight="bold")
    plt.xlabel("Number of Updates")
    plt.ylabel("Frequency (Count of Events)")
    
    median = np.median(updates)
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
    acc = overall["correct"] / scored * 100 if scored > 0 else 0
    inacc = overall["incorrect"] / scored * 100 if scored > 0 else 0
    flat_rate = overall["flat"] / overall["total"] * 100
    has_signal = 100.0 - flat_rate
    
    labels = [f'Accurate Prediction\n(77% of signal events, n={scored})', 'Incorrectly Predicted', 'Flat Early Signal\n(No prediction made)']
    
    pct_correct = (overall["correct"] / overall["total"]) * 100
    pct_incorrect = (overall["incorrect"] / overall["total"]) * 100
    
    values = [pct_correct, pct_incorrect, flat_rate]
    colors = ['#2A9D8F', '#E63946', '#BDBDBD']
    
    bars = plt.barh(labels[::-1], values[::-1], color=colors[::-1], height=0.6)
    
    plt.suptitle("Early Prediction Power (Using First 3 CDMs)", weight="bold", fontsize=18, y=1.02)
    plt.title(f"Early CDM trends are predictive — but only present in {has_signal:.0f}% of events", fontsize=14, pad=15)
    
    plt.xlabel("Percentage of All Events (%)")
    plt.xlim(0, 60)
    
    for bar in bars:
        width = bar.get_width()
        plt.text(width + 1, bar.get_y() + bar.get_height()/2, f"{width:.1f}%", ha='left', va='center', weight="bold")
        
    plt.text(35, 1.8, f"Accuracy = {acc:.1f}%", 
             fontsize=16, weight="bold", color="#1D3557",
             bbox=dict(facecolor='#F1FAEE', edgecolor='#A8DADC', boxstyle='round,pad=0.5'))
             
    plt.figtext(0.5, -0.05, "Early signals are absent in ~44% of events; however, when present, they are highly predictive (77% accuracy).", 
                ha="center", fontsize=12, style='italic', color='#457B9D', weight='bold', wrap=True)
                
    save_plot("chart4_prediction.png")

def plot_5_archetypes(results):
    """Chart 5: Object type comparison (Grouped bars)."""
    plt.figure(figsize=(10, 6))
    
    archs = ["PAYLOAD-DEBRIS", "DEBRIS-DEBRIS"]
    labels = ["Payload - Debris\n(Active vs Dead)", "Debris - Debris\n(Dead vs Dead)"]
    
    mono_rates = [
        results["archetypes"][a]["m2_monotonic"] / results["archetypes"][a]["total"] * 100
        for a in archs
    ]
    
    osc_rates = [
        results["archetypes"][a]["m2_oscillation"] / results["archetypes"][a]["total"] * 100
        for a in archs
    ]
    
    x = np.arange(len(labels))
    width = 0.35
    
    plt.bar(x - width/2, mono_rates, width, label='Monotonic Trend', color='#2A9D8F')
    plt.bar(x + width/2, osc_rates, width, label='Oscillatory Behavior', color='#E63946')
    
    plt.suptitle("Active Satellites Introduce Significant Instability", weight="bold", fontsize=16, y=1.02)
    plt.title("Conjunction Volatility by Object Type", pad=15)
    plt.ylabel("Percentage of Events (%)")
    plt.xticks(x, labels)
    plt.ylim(0, 80)
    plt.legend(loc='upper right')
    
    save_plot("chart5_archetypes.png")

def plot_6_flowchart():
    """Chart 6: Operator Decision Flow (Flowchart)."""
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.axis('off')
    
    box_style = dict(boxstyle="round,pad=0.5", facecolor="#F1FAEE", edgecolor="#1D3557", lw=2)
    decision_style = dict(boxstyle="round,pad=0.8", facecolor="#A8DADC", edgecolor="#1D3557", lw=2)
    inc_style = dict(boxstyle="round,pad=0.5", facecolor="#FFD6D6", edgecolor="#E63946", lw=2)
    dec_style = dict(boxstyle="round,pad=0.5", facecolor="#D6FFD6", edgecolor="#2A9D8F", lw=2)
    flat_style = dict(boxstyle="round,pad=0.5", facecolor="#E0E0E0", edgecolor="#808080", lw=2)
    
    nodes = {
        'A': {'text': 'Initial CDM Received', 'pos': (0.5, 0.9), 'style': box_style},
        'B': {'text': 'Wait for 3 CDMs', 'pos': (0.5, 0.7), 'style': box_style},
        'C': {'text': 'Does a clear\ntrend exist?', 'pos': (0.5, 0.45), 'style': decision_style},
        'D': {'text': 'Increasing Trend\n↓\nElevated Risk Signal →\nConsider Maneuver\n(77% directional reliability)', 'pos': (0.15, 0.1), 'style': inc_style},
        'E': {'text': 'Decreasing Trend\n↓\nMonitor Closely\n(77% directional reliability)', 'pos': (0.5, 0.1), 'style': dec_style},
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
    
    plt.title("Operator Decision Flow", pad=20, weight="bold", fontsize=18)
    
    # Add bottom footer insight
    plt.text(0.5, -0.05, "Early signals are absent in ~44% of events — requiring delayed decisions.",
             ha='center', va='center', fontsize=14, style='italic', color='#457B9D', weight='bold')
             
    plt.tight_layout()
    save_plot("chart6_decision_flow.png")


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
    plot_6_flowchart()
    
    log.info("All visualizations saved to %s", OUT_DIR)

if __name__ == "__main__":
    main()
