#!/usr/bin/env python3
"""
Visualize iperf3 JSON log files.

This script reads iperf3 JSON log files and creates visualizations for various metrics:
- goodput/throughput (bits_per_second)
- bytes (transferred bytes)
- retransmits (retransmission count)
- cwnd (congestion window size)
- rtt (round-trip time)
- rttvar (RTT variance)

Usage:
    python3 visualize_iperf3.py --iperf-dir ./logs --output goodput.png
    python3 visualize_iperf3.py --iperf-dir ./logs --metric rtt --output rtt.png
    python3 visualize_iperf3.py --iperf-dir ./logs --metric cwnd --output cwnd.png
    python3 visualize_iperf3.py --iperf-dir ./logs --metric all --output all_metrics.png
"""

import argparse
import json
import os
import glob
from typing import Dict, List, Tuple, Optional
import sys

try:
    # Use non-interactive backend for headless servers
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("Error: matplotlib and numpy are required.")
    print("Install with: pip install matplotlib numpy")
    sys.exit(1)


# Supported metrics and their configurations
METRICS_CONFIG = {
    'goodput': {
        'field': 'bits_per_second',
        'label': 'Goodput [Mbps]',
        'title': 'Goodput vs Time',
        'scale': 1_000_000,  # Convert to Mbps
        'aggregate': True,   # Can aggregate across flows
    },
    'bytes': {
        'field': 'bytes',
        'label': 'Bytes Transferred [MB]',
        'title': 'Bytes Transferred vs Time',
        'scale': 1_000_000,  # Convert to MB
        'aggregate': True,
    },
    'retransmits': {
        'field': 'retransmits',
        'label': 'Retransmits [packets]',
        'title': 'Retransmits vs Time',
        'scale': 1,
        'aggregate': True,
    },
    'cwnd': {
        'field': 'snd_cwnd',
        'label': 'Congestion Window [KB]',
        'title': 'Congestion Window vs Time',
        'scale': 1024,  # Convert to KB
        'aggregate': False,  # Per-flow metric, not aggregated
    },
    'rtt': {
        'field': 'rtt',
        'label': 'RTT [ms]',
        'title': 'Round-Trip Time vs Time',
        'scale': 1000,  # Convert us to ms
        'aggregate': False,
    },
    'rttvar': {
        'field': 'rttvar',
        'label': 'RTT Variance [ms]',
        'title': 'RTT Variance vs Time',
        'scale': 1000,  # Convert us to ms
        'aggregate': False,
    },
}


def parse_iperf3_json(filepath: str, metric: str = 'goodput') -> Tuple[List[float], List[float], Optional[str]]:
    """
    Parse iperf3 JSON log file and extract time series data for the specified metric.
    
    Args:
        filepath: Path to the iperf3 JSON log file
        metric: Metric to extract ('goodput', 'bytes', 'retransmits', 'cwnd', 'rtt', 'rttvar')
    
    Returns:
        Tuple of (timestamps, values, congestion_control_algorithm)
    """
    if metric not in METRICS_CONFIG:
        raise ValueError(f"Unknown metric: {metric}. Supported: {list(METRICS_CONFIG.keys())}")
    
    config = METRICS_CONFIG[metric]
    field = config['field']
    scale = config['scale']
    
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not parse {filepath}: {e}")
        return [], [], None
    
    timestamps = []
    values = []
    
    # Get congestion control algorithm
    cc_algo = None
    if 'start' in data and 'test_start' in data['start']:
        cc_algo = data['start']['test_start'].get('congestion', 'unknown')
    
    # Also check end section for sender_tcp_congestion
    if cc_algo is None or cc_algo == 'unknown':
        if 'end' in data:
            cc_algo = data['end'].get('sender_tcp_congestion', cc_algo)
    
    # Extract interval data
    if 'intervals' in data:
        for interval in data['intervals']:
            # Get stream data - prefer first stream for per-flow metrics
            stream_data = None
            if 'streams' in interval and len(interval['streams']) > 0:
                stream_data = interval['streams'][0]
            elif 'sum' in interval:
                stream_data = interval['sum']
            
            if stream_data is None:
                continue
            
            end_time = stream_data.get('end', 0)
            timestamps.append(end_time)
            
            # Extract the requested field
            value = stream_data.get(field, 0)
            if value is None:
                value = 0
            
            # Scale the value
            scaled_value = value / scale if scale != 1 else value
            values.append(scaled_value)
    
    return timestamps, values, cc_algo


def load_iperf_logs(log_dir: str, metric: str = 'goodput') -> Dict[str, Dict]:
    """Load all iperf3 JSON log files from a directory."""
    flows = {}
    json_files = glob.glob(os.path.join(log_dir, "*.json"))
    
    if not json_files:
        print(f"Warning: No JSON files found in {log_dir}")
        return flows
    
    for filepath in sorted(json_files):
        filename = os.path.basename(filepath)
        flow_name = os.path.splitext(filename)[0]
        
        timestamps, values, cc_algo = parse_iperf3_json(filepath, metric)
        
        if timestamps and values:
            # Determine flow type based on filename or cc_algo
            if 'cubic' in flow_name.lower() or cc_algo == 'cubic':
                flow_type = 'cubic'
            elif 'prague' in flow_name.lower() or cc_algo == 'prague':
                flow_type = 'prague'
            elif 'bbr' in flow_name.lower() or cc_algo == 'bbr':
                flow_type = 'bbr'
            elif 'reno' in flow_name.lower() or cc_algo == 'reno':
                flow_type = 'reno'
            else:
                flow_type = 'unknown'
            
            flows[flow_name] = {
                'timestamps': timestamps,
                'values': values,
                'cc_algo': cc_algo,
                'flow_type': flow_type,
                'filepath': filepath
            }
            print(f"Loaded {flow_name}: {len(timestamps)} data points, CC={cc_algo}")
    
    return flows


def calculate_aggregate(flows: Dict[str, Dict], flow_type: str, 
                        time_resolution: float = 1.0,
                        max_time: float = 480.0) -> Tuple[np.ndarray, np.ndarray]:
    """Calculate aggregate values for all flows of a given type."""
    time_bins = np.arange(0, max_time + time_resolution, time_resolution)
    aggregate = np.zeros(len(time_bins))
    
    for flow_name, flow_data in flows.items():
        if flow_data['flow_type'] != flow_type:
            continue
        
        timestamps = flow_data['timestamps']
        values = flow_data['values']
        
        for t, v in zip(timestamps, values):
            if t <= max_time:
                bin_idx = int(t / time_resolution)
                if bin_idx < len(aggregate):
                    aggregate[bin_idx] += v
    
    return time_bins, aggregate


def calculate_average(flows: Dict[str, Dict], flow_type: str,
                      time_resolution: float = 1.0,
                      max_time: float = 480.0) -> Tuple[np.ndarray, np.ndarray]:
    """Calculate average values for all flows of a given type."""
    time_bins = np.arange(0, max_time + time_resolution, time_resolution)
    sum_values = np.zeros(len(time_bins))
    count_values = np.zeros(len(time_bins))
    
    for flow_name, flow_data in flows.items():
        if flow_data['flow_type'] != flow_type:
            continue
        
        timestamps = flow_data['timestamps']
        values = flow_data['values']
        
        for t, v in zip(timestamps, values):
            if t <= max_time:
                bin_idx = int(t / time_resolution)
                if bin_idx < len(sum_values):
                    sum_values[bin_idx] += v
                    count_values[bin_idx] += 1
    
    # Avoid division by zero
    average = np.divide(sum_values, count_values, 
                        out=np.zeros_like(sum_values), 
                        where=count_values != 0)
    
    return time_bins, average


def plot_metric(flows: Dict[str, Dict], output_file: str,
                metric: str = 'goodput',
                title: str = None,
                show_individual: bool = False,
                max_time: float = 480.0):
    """
    Plot the specified metric for Cubic and Prague flows.
    
    Args:
        flows: Dictionary of flow data
        output_file: Output file path
        metric: Metric to plot
        title: Custom title (optional)
        show_individual: Whether to show individual flow lines
        max_time: Maximum time to plot
    """
    if metric not in METRICS_CONFIG:
        raise ValueError(f"Unknown metric: {metric}")
    
    config = METRICS_CONFIG[metric]
    ylabel = config['label']
    default_title = config['title']
    can_aggregate = config['aggregate']
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Get unique flow types
    flow_types = set(f['flow_type'] for f in flows.values())
    
    # Color scheme for different flow types
    colors = {
        'cubic': 'blue',
        'prague': 'orange',
        'bbr': 'green',
        'reno': 'purple',
        'unknown': 'gray'
    }
    
    if can_aggregate:
        # Plot aggregate values for each flow type
        for flow_type in sorted(flow_types):
            if flow_type == 'unknown' and len(flow_types) > 1:
                continue  # Skip unknown if there are other types
            
            time_bins, agg_values = calculate_aggregate(flows, flow_type, max_time=max_time)
            color = colors.get(flow_type, 'gray')
            ax.plot(time_bins, agg_values, color=color, linewidth=2, 
                    label=f'{flow_type.capitalize()} (aggregate)')
        
        # Plot total if multiple flow types
        if len(flow_types) > 1:
            time_bins, total = calculate_aggregate(flows, list(flow_types)[0], max_time=max_time)
            for ft in list(flow_types)[1:]:
                _, other = calculate_aggregate(flows, ft, max_time=max_time)
                total = total + other
            ax.plot(time_bins, total, color='green', linewidth=1.5, linestyle='--', 
                    alpha=0.7, label='Total')
    else:
        # For per-flow metrics (cwnd, rtt), show averages or individual flows
        for flow_type in sorted(flow_types):
            if flow_type == 'unknown' and len(flow_types) > 1:
                continue
            
            time_bins, avg_values = calculate_average(flows, flow_type, max_time=max_time)
            color = colors.get(flow_type, 'gray')
            ax.plot(time_bins, avg_values, color=color, linewidth=2,
                    label=f'{flow_type.capitalize()} (average)')
        
        # Optionally show individual flows
        if show_individual:
            for flow_name, flow_data in flows.items():
                flow_type = flow_data['flow_type']
                color = colors.get(flow_type, 'gray')
                ax.plot(flow_data['timestamps'], flow_data['values'],
                        color=color, linewidth=0.5, alpha=0.3)
    
    # Add phase markers (common in experiment visualization)
    phase_info = [(0, "Phase 1"), (120, "Phase 2"), (240, "Phase 3"), (360, "Phase 4")]
    for t, label in phase_info:
        if t < max_time:
            ax.axvline(x=t, color='gray', linestyle=':', alpha=0.5)
            ax.text(t + 5, ax.get_ylim()[1] * 0.95 if ax.get_ylim()[1] > 0 else 10, 
                    label, fontsize=9, alpha=0.7)
    
    ax.set_xlabel('Time [s]', fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title or default_title, fontsize=14)
    ax.set_xlim(0, max_time)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Saved {metric} plot to {output_file}")
    plt.close()


def plot_all_metrics(log_dir: str, output_file: str,
                     title: str = None, max_time: float = 480.0):
    """
    Plot all metrics in a multi-panel figure.
    
    Args:
        log_dir: Directory containing iperf3 JSON log files
        output_file: Output file path
        title: Custom title (optional)
        max_time: Maximum time to plot
    """
    # Metrics to plot in the combined view
    metrics_to_plot = ['goodput', 'cwnd', 'rtt', 'retransmits']
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    axes = axes.flatten()
    
    colors = {
        'cubic': 'blue',
        'prague': 'orange',
        'bbr': 'green',
        'reno': 'purple',
        'unknown': 'gray'
    }
    
    for idx, metric in enumerate(metrics_to_plot):
        ax = axes[idx]
        config = METRICS_CONFIG[metric]
        ylabel = config['label']
        metric_title = config['title']
        can_aggregate = config['aggregate']
        
        # Load data for this specific metric
        print(f"Loading data for metric: {metric}")
        flows = load_iperf_logs(log_dir, metric)
        
        if not flows:
            ax.text(0.5, 0.5, f'No data for {metric}', 
                    transform=ax.transAxes, ha='center', va='center')
            continue
        
        # Get unique flow types for this metric's data
        flow_types = set(f['flow_type'] for f in flows.values())
        
        if can_aggregate:
            for flow_type in sorted(flow_types):
                if flow_type == 'unknown' and len(flow_types) > 1:
                    continue
                time_bins, agg_values = calculate_aggregate(flows, flow_type, max_time=max_time)
                color = colors.get(flow_type, 'gray')
                ax.plot(time_bins, agg_values, color=color, linewidth=1.5,
                        label=f'{flow_type.capitalize()}')
        else:
            for flow_type in sorted(flow_types):
                if flow_type == 'unknown' and len(flow_types) > 1:
                    continue
                time_bins, avg_values = calculate_average(flows, flow_type, max_time=max_time)
                color = colors.get(flow_type, 'gray')
                ax.plot(time_bins, avg_values, color=color, linewidth=1.5,
                        label=f'{flow_type.capitalize()} (avg)')
        
        ax.set_xlabel('Time [s]', fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_title(metric_title, fontsize=11)
        ax.set_xlim(0, max_time)
        
        # Use log scale for goodput, linear scale for others
        if metric == 'goodput':
            ax.set_yscale('log')
            ax.set_ylim(bottom=1)  # Set minimum to 1 Mbps for log scale
        else:
            ax.set_ylim(bottom=0)
        
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', fontsize=8)
    
    plt.suptitle(title or 'iperf3 Metrics Overview', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Saved all metrics plot to {output_file}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Visualize iperf3 JSON log files with support for multiple metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Visualize goodput (default)
  python3 visualize_iperf3.py --iperf-dir ./exp_logs --output goodput.png
  
  # Visualize RTT
  python3 visualize_iperf3.py --iperf-dir ./exp_logs --metric rtt --output rtt.png
  
  # Visualize congestion window
  python3 visualize_iperf3.py --iperf-dir ./exp_logs --metric cwnd --output cwnd.png
  
  # Visualize all metrics in one figure
  python3 visualize_iperf3.py --iperf-dir ./exp_logs --metric all --output all_metrics.png
  
  # Visualize retransmits
  python3 visualize_iperf3.py --iperf-dir ./exp_logs --metric retransmits --output retransmits.png

Available metrics:
  - goodput: Throughput in Mbps (aggregated)
  - bytes: Bytes transferred in MB (aggregated)
  - retransmits: Retransmission count (aggregated)
  - cwnd: Congestion window in KB (average per flow type)
  - rtt: Round-trip time in ms (average per flow type)
  - rttvar: RTT variance in ms (average per flow type)
  - all: Plot all major metrics in one figure
        """
    )
    
    parser.add_argument("--iperf-dir", required=True,
                        help="Directory containing iperf3 JSON log files")
    parser.add_argument("--output", default="iperf3_plot.png",
                        help="Output file name (default: iperf3_plot.png)")
    parser.add_argument("--metric", default="goodput",
                        choices=['goodput', 'bytes', 'retransmits', 'cwnd', 'rtt', 'rttvar', 'all'],
                        help="Metric to plot (default: goodput)")
    parser.add_argument("--title", default=None,
                        help="Custom title for the plot")
    parser.add_argument("--max-time", type=float, default=480.0,
                        help="Maximum time to plot in seconds (default: 480)")
    parser.add_argument("--show-individual", action="store_true",
                        help="Show individual flow lines for per-flow metrics")
    
    args = parser.parse_args()
    
    # Validate directory
    if not os.path.isdir(args.iperf_dir):
        print(f"Error: Directory '{args.iperf_dir}' does not exist")
        sys.exit(1)
    
    # Load data
    print(f"Loading iperf3 logs from: {args.iperf_dir}")
    
    # For 'all' metric, plot_all_metrics will load data for each metric
    if args.metric == 'all':
        plot_all_metrics(args.iperf_dir, args.output, args.title, args.max_time)
    else:
        flows = load_iperf_logs(args.iperf_dir, args.metric)
        if not flows:
            print("Error: No valid iperf3 data found")
            sys.exit(1)
        plot_metric(flows, args.output, args.metric, args.title, 
                    args.show_individual, args.max_time)
    
    print("Visualization complete!")


if __name__ == "__main__":
    main()
