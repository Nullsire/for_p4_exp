#!/usr/bin/env python3
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.collections as mcoll
import seaborn as sns
import argparse
import os
import time
import numpy as np
from concurrent.futures import ProcessPoolExecutor


def plot_rtt_cdf(df: pd.DataFrame, output_dir: str, palette: dict, filename: str = "rtt_cdf.png"):
    """Plot empirical CDF of RTT (ms) for each flow_type.

    x-axis: RTT in ms
    y-axis: CDF probability
    """
    if df.empty or 'rtt_ms' not in df.columns:
        print("Skipping RTT CDF: no data")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    any_plotted = False
    for flow_type, color in palette.items():
        subset = df[df['flow_type'] == flow_type]
        if subset.empty:
            continue

        rtt = subset['rtt_ms'].to_numpy(dtype=float)
        rtt = rtt[np.isfinite(rtt) & (rtt > 0)]
        if rtt.size == 0:
            continue

        rtt.sort()
        # Empirical CDF: y in (0, 1]
        y = (np.arange(1, rtt.size + 1, dtype=float)) / float(rtt.size)

        ax.plot(rtt, y, color=color, linewidth=2.0, label=f"{flow_type.capitalize()} (n={rtt.size})")
        any_plotted = True

    ax.set_title("RTT CDF")
    ax.set_xlabel("RTT (ms)")
    ax.set_ylabel("CDF")
    ax.set_ylim(0.0, 1.0)
    ax.grid(True, alpha=0.3)
    if any_plotted:
        ax.legend(loc='lower right')
    else:
        ax.text(0.5, 0.5, "No valid RTT samples", ha="center", va="center", transform=ax.transAxes)

    plt.tight_layout()
    output_path = os.path.join(output_dir, filename)
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Finished {filename}")

def plot_single_metric_optimized(args):
    """
    Worker function to plot a single metric using LineCollection for speed.
    args: (df_subset, metric_col, ylabel, title, filename, output_dir, palette, use_log_scale)
    """
    df, metric_col, ylabel, title, filename, output_dir, palette, use_log_scale = args
    
    print(f"Starting plot: {title}")
    start_time = time.time()
    
    fig, ax = plt.subplots(figsize=(14, 7))
    
    # 1. Plot Individual Flows using LineCollection (High Performance)
    # We need to group by flow_id and create segments
    # df is already sorted by flow_id and time_sec
    
    for flow_type, color in palette.items():
        type_subset = df[df['flow_type'] == flow_type]
        if type_subset.empty:
            continue
            
        # Create segments for LineCollection
        # This is the most expensive part, but much faster than plt.plot loop
        segments = []
        
        # Group by flow_id. Since it's sorted, we can just iterate?
        # groupby is safer and reasonably fast
        for _, flow_data in type_subset.groupby('flow_id'):
            # Filter out invalid/zero values to avoid horizontal lines
            # RTT should be > 0, CWND should be > 0, delivery_rate can be 0 but skip if all zeros
            if metric_col == 'rtt_ms':
                valid_mask = flow_data[metric_col] > 0
            elif metric_col == 'cwnd':
                valid_mask = flow_data[metric_col] > 0
            elif metric_col == 'delivery_rate_mbps':
                # For delivery rate, filter out rows where rate is 0 (inactive flows)
                valid_mask = flow_data[metric_col] > 0
            else:
                # For retransmits, 0 is valid, so don't filter
                valid_mask = pd.Series([True] * len(flow_data), index=flow_data.index)
            
            # Skip if no valid data points
            if not valid_mask.any():
                continue
            
            # Extract x and y as a list of (x, y) tuples
            # Using numpy column_stack is faster
            valid_data = flow_data[valid_mask]
            points = np.column_stack((valid_data['time_sec'].values, valid_data[metric_col].values))
            segments.append(points)
            
        # Create LineCollection with semi-transparent lines (alpha=0.8)
        lc = mcoll.LineCollection(
            segments,
            colors=[color] * len(segments),
            linewidths=0.5,
            alpha=0.8,  # Semi-transparent lines
            zorder=1,
            label=f"{flow_type.capitalize()}",
            rasterized=True # Important for performance when saving vector formats, keeps file size down
        )
        ax.add_collection(lc)

    ax.set_title(title, fontsize=16)
    ax.set_xlabel('Time (s)', fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)
    
    # Apply log scale if requested
    if use_log_scale:
        ax.set_yscale('log')
    
    # Auto-scale axes since add_collection doesn't do it automatically
    ax.autoscale_view()
    
    plt.tight_layout()
    output_path = os.path.join(output_dir, filename)
    plt.savefig(output_path, dpi=150)
    plt.close()
    
    elapsed = time.time() - start_time
    print(f"Finished {filename} in {elapsed:.2f}s")
    return filename

def visualize_tcp_metrics_optimized(csv_file, output_dir):
    """
    Optimized visualization script using LineCollection and multiprocessing.
    NO DOWNSAMPLING.
    """
    
    if not os.path.exists(csv_file):
        print(f"Error: File {csv_file} not found.")
        return

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Reading data from {csv_file}...")
    t0 = time.time()
    
    # Read only necessary columns
    usecols = ['timestamp_ns', 'flow_type', 'flow_id', 'rtt_us', 'cwnd', 'delivery_rate_bps', 'retrans']
    df = pd.read_csv(csv_file, usecols=usecols)
    
    print(f"Data loaded in {time.time() - t0:.2f}s. Rows: {len(df)}")

    # Filter valid flows
    df = df[df['flow_type'].notna() & (df['flow_type'] != 'unknown')]
    
    # Time conversion
    start_time = df['timestamp_ns'].min()
    df['time_sec'] = (df['timestamp_ns'] - start_time) / 1e9
    
    # Pre-calculate RTT in ms (from us)
    df['rtt_ms'] = df['rtt_us'] / 1000.0

    # # Filter outliers: ignore rows with RTT > 400ms (keep NaNs to avoid dropping other metrics)
    # before_rows = len(df)
    # df = df[df['rtt_ms'].isna() | (df['rtt_ms'] <= 400.0)]
    # filtered_rows = before_rows - len(df)
    # if filtered_rows > 0:
    #     print(f"Filtered {filtered_rows} rows with rtt_ms > 400ms")
    
    # Pre-calculate delivery rate in Mbps (from bps)
    df['delivery_rate_mbps'] = df['delivery_rate_bps'] / 1e6
    
    # Sort by flow_id and time for correct line segments
    print("Sorting data...")
    df.sort_values(by=['flow_id', 'time_sec'], inplace=True)
    
    palette = {"cubic": "blue", "prague": "orange"}

    # RTT CDF (single plot, computed once to avoid heavy dataframe copies)
    print("Generating RTT CDF...")
    plot_rtt_cdf(df[['flow_type', 'rtt_ms']].copy(), output_dir, palette)
    
    # Prepare tasks
    # We pass the full dataframe (filtered by columns if needed to save RAM, but here we just pass slices)
    # Note: Passing slices of 4.8M rows to processes is heavy. 
    # Optimization: Pass only the relevant columns for each task.
    
    tasks = [
        (df[['time_sec', 'flow_type', 'flow_id', 'rtt_ms']].copy(), 'rtt_ms', 'RTT (ms)', 'RTT over Time (Full Resolution)', 'rtt_over_time_opt.png', output_dir, palette, False),
        (df[['time_sec', 'flow_type', 'flow_id', 'cwnd']].copy(), 'cwnd', 'CWND (segments)', 'Congestion Window over Time (Full Resolution)', 'cwnd_over_time_opt.png', output_dir, palette, False),
        (df[['time_sec', 'flow_type', 'flow_id', 'delivery_rate_mbps']].copy(), 'delivery_rate_mbps', 'Delivery Rate (Mbps)', 'Delivery Rate over Time (Full Resolution)', 'delivery_rate_over_time_opt.png', output_dir, palette, True),
        (df[['time_sec', 'flow_type', 'flow_id', 'retrans']].copy(), 'retrans', 'Cumulative Retransmits', 'Retransmits over Time (Full Resolution)', 'retransmits_over_time_opt.png', output_dir, palette, False)
    ]
    
    print(f"Starting parallel plotting of {len(tasks)} charts...")
    
    with ProcessPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(plot_single_metric_optimized, tasks))
        
    print("All plots generated.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optimized Visualization of TCP metrics (No Downsampling).")
    parser.add_argument("--input", default="tcp_metrics.csv", help="Path to the input CSV file.")
    parser.add_argument("--output", default="plots", help="Directory to save the plots.")
    
    args = parser.parse_args()
    
    visualize_tcp_metrics_optimized(args.input, args.output)