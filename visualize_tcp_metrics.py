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
            # Extract x and y as a list of (x, y) tuples
            # Using numpy column_stack is faster
            points = np.column_stack((flow_data['time_sec'].values, flow_data[metric_col].values))
            segments.append(points)
            
        # Create LineCollection with solid lines (alpha=1.0)
        lc = mcoll.LineCollection(
            segments,
            colors=[color] * len(segments),
            linewidths=0.5,
            alpha=1.0,  # Solid lines
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
    
    # Pre-calculate delivery rate in Mbps (from bps)
    df['delivery_rate_mbps'] = df['delivery_rate_bps'] / 1e6
    
    # Sort by flow_id and time for correct line segments
    print("Sorting data...")
    df.sort_values(by=['flow_id', 'time_sec'], inplace=True)
    
    palette = {"cubic": "blue", "prague": "orange"}
    
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
