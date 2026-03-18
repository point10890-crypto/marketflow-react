#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Analysis - Visualization Module (Dark Pro Theme)
Generates professional-grade charts for lead-lag correlation analysis.
"""
import os
import logging
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import FancyBboxPatch
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# Dark Pro Theme
# ═══════════════════════════════════════
BG_COLOR = '#1c1c1e'
CARD_COLOR = '#2c2c2e'
GRID_COLOR = '#3a3a3c'
TEXT_COLOR = '#e5e5e7'
TEXT_DIM = '#8e8e93'
ACCENT_AMBER = '#f59e0b'
ACCENT_EMERALD = '#10b981'
ACCENT_RED = '#ef4444'
ACCENT_BLUE = '#3b82f6'
ACCENT_PURPLE = '#8b5cf6'
ACCENT_CYAN = '#06b6d4'

def _apply_dark_theme():
    """Apply dark theme to matplotlib."""
    plt.rcParams.update({
        'figure.facecolor': BG_COLOR,
        'axes.facecolor': CARD_COLOR,
        'axes.edgecolor': GRID_COLOR,
        'axes.labelcolor': TEXT_DIM,
        'axes.grid': True,
        'grid.color': GRID_COLOR,
        'grid.alpha': 0.3,
        'grid.linestyle': '--',
        'text.color': TEXT_COLOR,
        'xtick.color': TEXT_DIM,
        'ytick.color': TEXT_DIM,
        'xtick.labelsize': 9,
        'ytick.labelsize': 9,
        'font.family': 'sans-serif',
        'font.size': 10,
        'axes.unicode_minus': False,
        'figure.dpi': 180,
        'savefig.facecolor': BG_COLOR,
        'savefig.edgecolor': 'none',
        'savefig.bbox': 'tight',
        'savefig.pad_inches': 0.3,
    })


def _make_diverging_cmap():
    """Create custom red-blue diverging colormap."""
    colors_list = [
        (0.0, '#ef4444'),   # red
        (0.25, '#7f1d1d'),  # dark red
        (0.5, '#1c1c1e'),   # bg (center)
        (0.75, '#1e3a5f'),  # dark blue
        (1.0, '#3b82f6'),   # blue
    ]
    cmap = mcolors.LinearSegmentedColormap.from_list(
        'dark_diverging',
        [(pos, col) for pos, col in colors_list],
        N=256
    )
    return cmap


def plot_lag_correlation_heatmap(
    lead_lag_results: List,
    target: str = "BTC",
    save_path: str = None,
    top_n: int = 15
):
    """Heatmap: correlation at different lags. Dark pro theme."""
    _apply_dark_theme()
    fig, ax = plt.subplots(figsize=(16, 10))

    variables = []
    lag_range = list(range(-6, 7))
    data_matrix = []

    for result in lead_lag_results[:top_n]:
        var_name = result.var1 if hasattr(result, 'var1') else result.get('var1', 'Unknown')
        lags = result.all_lags if hasattr(result, 'all_lags') else result.get('all_lags', {})
        row = []
        for lag in lag_range:
            corr = lags.get(lag, lags.get(str(lag), 0))
            row.append(corr)
        variables.append(var_name)
        data_matrix.append(row)

    data_matrix = np.array(data_matrix)
    cmap = _make_diverging_cmap()
    im = ax.imshow(data_matrix, cmap=cmap, aspect='auto', vmin=-1, vmax=1, interpolation='nearest')

    ax.set_xticks(range(len(lag_range)))
    ax.set_xticklabels([str(l) for l in lag_range], fontsize=9, color=TEXT_DIM)
    ax.set_yticks(range(len(variables)))
    ax.set_yticklabels(variables, fontsize=10, fontweight='bold', color=TEXT_COLOR)

    # Axis labels
    ax.set_xlabel('Lag (months)  ←  Variable Lags  |  Variable Leads  →', fontsize=11, color=TEXT_DIM, labelpad=12)

    # Title
    ax.set_title(f'Cross-Correlation Heatmap  ·  Macro Indicators vs {target}',
                 fontsize=15, fontweight='bold', color=TEXT_COLOR, pad=16)

    # Colorbar
    cbar = plt.colorbar(im, ax=ax, fraction=0.02, pad=0.03)
    cbar.set_label('Correlation (r)', fontsize=10, color=TEXT_DIM)
    cbar.ax.yaxis.set_tick_params(color=TEXT_DIM)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=TEXT_DIM, fontsize=8)

    # Annotations
    for i in range(len(variables)):
        for j in range(len(lag_range)):
            val = data_matrix[i, j]
            if abs(val) > 0.5:
                ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                        color='white' if abs(val) > 0.7 else TEXT_DIM,
                        fontsize=7, fontweight='bold' if abs(val) > 0.7 else 'normal')

    # Star markers for optimal lag
    for i, result in enumerate(lead_lag_results[:top_n]):
        opt_lag = result.optimal_lag if hasattr(result, 'optimal_lag') else result.get('optimal_lag', 0)
        if opt_lag in lag_range:
            opt_idx = lag_range.index(opt_lag)
            ax.scatter(opt_idx, i, marker='*', s=220, c=ACCENT_AMBER,
                       edgecolors='none', zorder=5, alpha=0.95)

    # Vertical center line
    center_idx = lag_range.index(0)
    ax.axvline(x=center_idx, color=ACCENT_AMBER, linewidth=1, alpha=0.3, linestyle='-')

    # Border styling
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
        spine.set_linewidth(0.5)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path)
        logger.info(f"Heatmap saved to {save_path}")
    plt.close(fig)
    return fig


def plot_cross_correlation_function(
    df: pd.DataFrame,
    var1: str,
    var2: str,
    max_lag: int = 12,
    save_path: str = None
):
    """CCF bar chart with gradient bars and confidence bands."""
    _apply_dark_theme()
    from lead_lag.cross_correlation import compute_lagged_correlation

    correlations = compute_lagged_correlation(df[var1], df[var2], max_lag)
    lags = sorted(correlations.keys())
    corrs = [correlations[l] for l in lags]

    fig, ax = plt.subplots(figsize=(12, 6))

    # Gradient bars
    for lag, corr in zip(lags, corrs):
        alpha = 0.4 + 0.6 * min(abs(corr), 1.0)
        color = ACCENT_EMERALD if corr >= 0 else ACCENT_RED
        ax.bar(lag, corr, color=color, alpha=alpha, width=0.7,
               edgecolor='none', zorder=3)

    # Optimal lag highlight
    opt_lag = max(lags, key=lambda l: abs(correlations[l]))
    opt_corr = correlations[opt_lag]
    highlight_color = ACCENT_EMERALD if opt_corr >= 0 else ACCENT_RED
    ax.bar(opt_lag, opt_corr, color=highlight_color, alpha=1.0, width=0.7,
           edgecolor=ACCENT_AMBER, linewidth=2, zorder=4)

    # Confidence interval
    n = len(df)
    ci = 1.96 / np.sqrt(n)
    ax.axhspan(-ci, ci, color=GRID_COLOR, alpha=0.15, zorder=1)
    ax.axhline(y=ci, color=TEXT_DIM, linestyle=':', alpha=0.4, linewidth=0.8)
    ax.axhline(y=-ci, color=TEXT_DIM, linestyle=':', alpha=0.4, linewidth=0.8)
    ax.axhline(y=0, color=GRID_COLOR, linewidth=0.8, zorder=2)

    # Annotation
    ax.annotate(
        f'r = {opt_corr:+.3f}\nlag {opt_lag}',
        xy=(opt_lag, opt_corr),
        xytext=(opt_lag + (2 if opt_lag < 6 else -3), opt_corr + 0.15 * np.sign(opt_corr)),
        fontsize=11, fontweight='bold', color=ACCENT_AMBER,
        arrowprops=dict(arrowstyle='->', color=ACCENT_AMBER, lw=1.5),
        bbox=dict(boxstyle='round,pad=0.4', facecolor=BG_COLOR, edgecolor=ACCENT_AMBER, alpha=0.9),
        zorder=6
    )

    ax.set_xlabel('Lag (months)', fontsize=10, color=TEXT_DIM, labelpad=8)
    ax.set_ylabel('Correlation', fontsize=10, color=TEXT_DIM, labelpad=8)
    ax.set_title(f'{var1}  →  {var2}  Cross-Correlation',
                 fontsize=13, fontweight='bold', color=TEXT_COLOR, pad=12)

    # Subtitle
    ax.text(0.5, 1.02, 'Positive Lag = Variable Leads Target',
            transform=ax.transAxes, ha='center', fontsize=8, color=TEXT_DIM)

    ax.set_xticks(lags)
    ax.set_ylim(-1.1, 1.1)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
        spine.set_linewidth(0.5)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path)
        logger.info(f"CCF plot saved to {save_path}")
    plt.close(fig)
    return fig


def plot_granger_summary(
    granger_results: List,
    target: str = "BTC",
    save_path: str = None
):
    """Horizontal bar chart of Granger predictors with significance bands."""
    _apply_dark_theme()
    fig, ax = plt.subplots(figsize=(14, 9))

    causes, p_values, lags = [], [], []
    for result in granger_results:
        cause = result.cause if hasattr(result, 'cause') else result.get('cause', '')
        p_val = result.best_p_value if hasattr(result, 'best_p_value') else result.get('best_p_value', 1)
        lag = result.best_lag if hasattr(result, 'best_lag') else result.get('best_lag', 0)
        causes.append(cause)
        p_values.append(p_val)
        lags.append(lag)

    # Sort by p-value (most significant first → bottom of chart)
    sorted_idx = np.argsort(p_values)[::-1]  # reverse so best is at bottom (visually top)
    causes = [causes[i] for i in sorted_idx]
    p_values = [p_values[i] for i in sorted_idx]
    lags = [lags[i] for i in sorted_idx]

    y_pos = range(len(causes))
    neg_log_p = [-np.log10(max(p, 1e-10)) for p in p_values]

    # Color by significance
    colors = []
    for p in p_values:
        if p < 0.001:
            colors.append(ACCENT_AMBER)
        elif p < 0.01:
            colors.append(ACCENT_EMERALD)
        elif p < 0.05:
            colors.append(ACCENT_BLUE)
        else:
            colors.append(TEXT_DIM)

    bars = ax.barh(y_pos, neg_log_p, color=colors, alpha=0.85, height=0.65,
                   edgecolor='none', zorder=3)

    # Significance threshold lines
    ax.axvline(x=-np.log10(0.05), color=ACCENT_RED, linestyle='--', linewidth=1.2, alpha=0.6, zorder=2)
    ax.axvline(x=-np.log10(0.01), color=ACCENT_AMBER, linestyle='--', linewidth=1.2, alpha=0.6, zorder=2)
    ax.axvline(x=-np.log10(0.001), color=ACCENT_EMERALD, linestyle='--', linewidth=1.2, alpha=0.6, zorder=2)

    # Labels on bars
    ax.set_yticks(y_pos)
    y_labels = []
    for c, l in zip(causes, lags):
        y_labels.append(f'{c}')
    ax.set_yticklabels(y_labels, fontsize=10, fontweight='bold', color=TEXT_COLOR)

    # P-value & lag text on each bar
    for i, (bar, p, lag) in enumerate(zip(bars, p_values, lags)):
        # Stars
        stars = '★★★' if p < 0.001 else '★★' if p < 0.01 else '★' if p < 0.05 else ''
        text = f'  p={p:.4f}  lag={lag}  {stars}'
        ax.text(bar.get_width() + 0.08, bar.get_y() + bar.get_height() / 2,
                text, va='center', fontsize=8, color=TEXT_DIM, fontweight='bold')

    # Threshold labels (top)
    ax.text(-np.log10(0.05), len(causes) + 0.3, 'p=0.05', ha='center', fontsize=8, color=ACCENT_RED, alpha=0.8)
    ax.text(-np.log10(0.01), len(causes) + 0.3, 'p=0.01', ha='center', fontsize=8, color=ACCENT_AMBER, alpha=0.8)
    ax.text(-np.log10(0.001), len(causes) + 0.3, 'p=0.001', ha='center', fontsize=8, color=ACCENT_EMERALD, alpha=0.8)

    ax.set_xlabel('−log₁₀(p-value)  →  Higher = More Significant', fontsize=11, color=TEXT_DIM, labelpad=12)
    ax.set_title(f'Granger Causality  ·  What Predicts {target}?',
                 fontsize=15, fontweight='bold', color=TEXT_COLOR, pad=16)

    ax.set_xlim(0, max(neg_log_p) * 1.25 if neg_log_p else 5)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
        spine.set_linewidth(0.5)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path)
        logger.info(f"Granger summary saved to {save_path}")
    plt.close(fig)
    return fig


def generate_all_charts(
    df: pd.DataFrame,
    lead_lag_results: List,
    granger_results: List,
    target: str = "BTC",
    output_dir: str = None
):
    """Generate all visualization charts and save to output directory."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    charts = []

    # 1. Heatmap
    try:
        fig1 = plot_lag_correlation_heatmap(
            lead_lag_results, target=target,
            save_path=os.path.join(output_dir, f'heatmap_{timestamp}.png')
        )
        charts.append(('heatmap', fig1))
    except Exception as e:
        logger.warning(f"Heatmap generation failed: {e}")

    # 2. Top CCF plots (top 5 by |correlation|)
    sorted_results = sorted(
        lead_lag_results,
        key=lambda r: abs(r.optimal_correlation if hasattr(r, 'optimal_correlation') else r.get('optimal_correlation', 0)),
        reverse=True
    )
    for result in sorted_results[:5]:
        var1 = result.var1 if hasattr(result, 'var1') else result.get('var1', '')
        try:
            target_col = f"{target}_MoM" if f"{target}_MoM" in df.columns else target
            if var1 in df.columns:
                fig = plot_cross_correlation_function(
                    df, var1, target_col,
                    save_path=os.path.join(output_dir, f'ccf_{var1}_{timestamp}.png')
                )
                charts.append((f'ccf_{var1}', fig))
        except Exception as e:
            logger.warning(f"CCF plot failed for {var1}: {e}")

    # 3. Granger summary
    if granger_results:
        try:
            fig3 = plot_granger_summary(
                granger_results, target=target,
                save_path=os.path.join(output_dir, f'granger_{timestamp}.png')
            )
            charts.append(('granger', fig3))
        except Exception as e:
            logger.warning(f"Granger plot failed: {e}")

    logger.info(f"Generated {len(charts)} charts in {output_dir}")
    return charts


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from lead_lag import fetch_all_data, build_lead_lag_matrix, find_granger_causal_indicators

    print("\n📊 Generating Lead-Lag Visualization Charts...\n")

    df = fetch_all_data(start_date="2020-01-01", resample="monthly")
    if df.empty:
        print("❌ No data fetched")
        exit(1)

    target = "BTC_MoM" if "BTC_MoM" in df.columns else "BTC"

    matrix = build_lead_lag_matrix(df, target=target, max_lag=6)
    granger_results = find_granger_causal_indicators(df, target=target, max_lag=6)

    output_dir = os.path.join(os.path.dirname(__file__), "lead_lag_charts")
    charts = generate_all_charts(
        df, matrix.results, granger_results,
        target="BTC", output_dir=output_dir
    )
    print(f"\n✅ Generated {len(charts)} charts in {output_dir}")
