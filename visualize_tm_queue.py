#!/usr/bin/env python3
"""
Visualize tm_shape_queue TSV log files.

This script reads tm_shape_queue TSV log files and creates visualizations for various metrics:
- queue_usage: Queue usage in cells
- queue_wm: Queue watermark in cells
- queue_drop: Queue drop count (cumulative)
- d_queue_drop: Queue drop rate (per interval)
- egress_usage: Egress port usage in cells
- egress_wm: Egress port watermark in cells
- egress_drop: Egress port drop count (cumulative)
- d_egress_drop: Egress port drop rate (per interval)
- rx_rate: Port RX rate in bps
- tx_rate: Port TX rate in bps

Supports two log formats:
- Single queue mode: monitors a specific queue
- All queues mode (--all-queues): monitors all 8 queues (0-7)

Usage:
    python3 visualize_tm_queue.py --tm-log ./tm_log.tsv --output queue_metrics.png
    python3 visualize_tm_queue.py --tm-log ./tm_log.tsv --metric drop_rate --output drops.png
    python3 visualize_tm_queue.py --tm-log ./tm_log.tsv --metric all --output all_metrics.png
"""

import argparse
import os
from typing import Dict, List, Optional, Tuple
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
    'queue_usage': {
        'label': 'Queue Usage [cells]',
        'title': 'Queue Usage vs Time',
        'fields_single': ['queue_usage'],
        'fields_all': ['q_usage'],
    },
    'queue_wm': {
        'label': 'Queue Watermark [cells]',
        'title': 'Queue Watermark vs Time',
        'fields_single': ['queue_wm'],
        'fields_all': ['q_wm'],
    },
    'drop_rate': {
        'label': 'Drop Rate [packets/interval]',
        'title': 'Drop Rate vs Time',
        'fields_single': ['d_queue_drop'],
        'fields_all': ['d_q_drop'],
    },
    'drop_count': {
        'label': 'Drop Count [packets]',
        'title': 'Cumulative Drop Count vs Time',
        'fields_single': ['queue_drop'],
        'fields_all': ['q_drop'],
    },
    'egress_usage': {
        'label': 'Egress Usage [cells]',
        'title': 'Egress Port Usage vs Time',
        'fields_single': ['egress_usage'],
        'fields_all': ['egress_usage'],
    },
    'egress_wm': {
        'label': 'Egress Watermark [cells]',
        'title': 'Egress Port Watermark vs Time',
        'fields_single': ['egress_wm'],
        'fields_all': ['egress_wm'],
    },
    'egress_drop_rate': {
        'label': 'Egress Drop Rate [packets/interval]',
        'title': 'Egress Port Drop Rate vs Time',
        'fields_single': ['d_egress_drop'],
        'fields_all': ['d_egress_drop'],
    },
    'rate': {
        'label': 'Rate [Mbps]',
        'title': 'Port RX/TX Rate vs Time',
        'fields_single': ['rx_rate', 'tx_rate'],
        'fields_all': ['rx_rate', 'tx_rate'],
    },
}


def parse_tm_log(filepath: str) -> Optional[Dict]:
    """
    Parse tm_shape_queue TSV log file.
    
    Returns:
        Dictionary with time series data for various metrics, or None if parsing fails.
        
    Log format (single queue mode):
        time, dev_port, queue, egress_drop, d_egress_drop, egress_usage, egress_wm,
        queue_drop, d_queue_drop, queue_usage, queue_wm, rx_rate, tx_rate
    
    Log format (all queues mode):
        time, dev_port, egress_drop, d_egress_drop, egress_usage, egress_wm,
        rx_rate, tx_rate, q_drop[0-7], d_q_drop[0-7], sum_d_q_drop, d_unattributed,
        q_usage[0-7], q_wm[0-7]
    """
    data = {
        'time': [],
        'dev_port': None,
        'egress_drop': [],
        'd_egress_drop': [],
        'egress_usage': [],
        'egress_wm': [],
        'rx_rate': [],
        'tx_rate': [],
        'queue_mode': None,  # 'single' or 'all'
    }
    
    # Single queue mode data
    single_queue_data = {
        'queue': None,
        'queue_drop': [],
        'd_queue_drop': [],
        'queue_usage': [],
        'queue_wm': [],
    }
    
    # All queues mode data
    all_queues_data = {
        'q_drop': [[] for _ in range(8)],
        'd_q_drop': [[] for _ in range(8)],
        'sum_d_q_drop': [],
        'd_unattributed': [],
        'q_usage': [[] for _ in range(8)],
        'q_wm': [[] for _ in range(8)],
    }
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: Could not find file '{filepath}'")
        return None
    except IOError as e:
        print(f"Error: Could not read file '{filepath}': {e}")
        return None
    
    header_line = None
    line_count = 0
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Find header line
        if line.startswith('time\t'):
            header_line = line
            # Determine mode by checking header format
            if '\tqueue\t' in line:
                data['queue_mode'] = 'single'
            else:
                data['queue_mode'] = 'all'
            continue
        
        if header_line is None:
            continue
        
        parts = line.split('\t')
        if len(parts) < 7:
            continue
        
        try:
            t = float(parts[0])
            data['time'].append(t)
            
            if data['dev_port'] is None:
                data['dev_port'] = int(parts[1])
            
            if data['queue_mode'] == 'single':
                # Single queue mode: 13 columns
                # time, dev_port, queue, egress_drop, d_egress_drop, egress_usage, egress_wm,
                # queue_drop, d_queue_drop, queue_usage, queue_wm, rx_rate, tx_rate
                if len(parts) < 13:
                    print(f"Warning: Incomplete single queue line (expected 13 fields, got {len(parts)})")
                    continue
                
                if single_queue_data['queue'] is None:
                    single_queue_data['queue'] = int(parts[2])
                
                data['egress_drop'].append(int(parts[3]))
                data['d_egress_drop'].append(int(parts[4]))
                data['egress_usage'].append(int(parts[5]))
                data['egress_wm'].append(int(parts[6]))
                single_queue_data['queue_drop'].append(int(parts[7]))
                single_queue_data['d_queue_drop'].append(int(parts[8]))
                single_queue_data['queue_usage'].append(int(parts[9]))
                single_queue_data['queue_wm'].append(int(parts[10]))
                data['rx_rate'].append(int(parts[11]))
                data['tx_rate'].append(int(parts[12]))
                
            else:
                # All queues mode: 14 columns
                # time, dev_port, egress_drop, d_egress_drop, egress_usage, egress_wm,
                # rx_rate, tx_rate, q_drop[0-7], d_q_drop[0-7], sum_d_q_drop, d_unattributed,
                # q_usage[0-7], q_wm[0-7]
                if len(parts) < 14:
                    print(f"Warning: Incomplete all-queues line (expected 14 fields, got {len(parts)})")
                    continue
                
                data['egress_drop'].append(int(parts[2]))
                data['d_egress_drop'].append(int(parts[3]))
                data['egress_usage'].append(int(parts[4]))
                data['egress_wm'].append(int(parts[5]))
                data['rx_rate'].append(int(parts[6]))
                data['tx_rate'].append(int(parts[7]))
                
                # Parse queue arrays [x,y,z,...]
                q_drop_str = parts[8].strip('[]')
                d_q_drop_str = parts[9].strip('[]')
                sum_d_q = int(parts[10])
                d_unattr = int(parts[11])
                q_usage_str = parts[12].strip('[]')
                q_wm_str = parts[13].strip('[]')
                
                q_drop_vals = [int(x) for x in q_drop_str.split(',') if x]
                d_q_drop_vals = [int(x) for x in d_q_drop_str.split(',') if x]
                q_usage_vals = [int(x) for x in q_usage_str.split(',') if x]
                q_wm_vals = [int(x) for x in q_wm_str.split(',') if x]
                
                for i in range(min(8, len(q_drop_vals))):
                    all_queues_data['q_drop'][i].append(q_drop_vals[i])
                    all_queues_data['d_q_drop'][i].append(d_q_drop_vals[i])
                    all_queues_data['q_usage'][i].append(q_usage_vals[i])
                    all_queues_data['q_wm'][i].append(q_wm_vals[i])
                
                all_queues_data['sum_d_q_drop'].append(sum_d_q)
                all_queues_data['d_unattributed'].append(d_unattr)
                
            line_count += 1
                
        except (ValueError, IndexError) as e:
            print(f"Warning: Could not parse line: {line[:60]}... Error: {e}")
            continue
    
    if not data['time']:
        print(f"Warning: No valid data points found in '{filepath}'")
        return None
    
    # Merge single/all queue data into main data structure
    if data['queue_mode'] == 'single':
        data.update(single_queue_data)
    else:
        data.update(all_queues_data)
    
    # Normalize timestamps to start from 0
    if data['time']:
        t0 = data['time'][0]
        data['time'] = [t - t0 for t in data['time']]
    
    print(f"Loaded {line_count} data points from '{filepath}', mode={data['queue_mode']}, dev_port={data['dev_port']}")
    
    return data


def plot_single_metric(tm_data: Dict, output_file: str,
                       metric: str = 'queue_usage',
                       title: str = None,
                       max_time: float = None):
    """
    Plot a single metric from tm_shape_queue log.
    
    Args:
        tm_data: Parsed tm log data
        output_file: Output file path
        metric: Metric to plot
        title: Custom title (optional)
        max_time: Maximum time to plot (optional)
    """
    if metric not in METRICS_CONFIG:
        raise ValueError(f"Unknown metric: {metric}. Supported: {list(METRICS_CONFIG.keys())}")
    
    config = METRICS_CONFIG[metric]
    ylabel = config['label']
    default_title = config['title']
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    time = tm_data['time']
    if max_time:
        # Filter data by max_time
        valid_idx = [i for i, t in enumerate(time) if t <= max_time]
        time = [time[i] for i in valid_idx]
    else:
        valid_idx = list(range(len(time)))
    
    # Color palette for queues
    colors = plt.cm.tab10(np.linspace(0, 1, 10))
    
    if tm_data['queue_mode'] == 'single':
        queue_num = tm_data['queue']
        fields = config['fields_single']
        
        if metric == 'rate':
            # Special handling for RX/TX rate
            rx_rate = [tm_data['rx_rate'][i] / 1_000_000 for i in valid_idx]  # Convert to Mbps
            tx_rate = [tm_data['tx_rate'][i] / 1_000_000 for i in valid_idx]
            ax.plot(time, rx_rate, color='green', linewidth=1.5, label='RX Rate')
            ax.plot(time, tx_rate, color='purple', linewidth=1.5, label='TX Rate')
        else:
            for field in fields:
                values = [tm_data[field][i] for i in valid_idx]
                label = f'Queue {queue_num}' if 'queue' in field else field.replace('_', ' ').title()
                ax.plot(time, values, color=colors[0], linewidth=1.5, label=label)
    
    else:
        # All queues mode
        fields = config['fields_all']
        
        if metric == 'rate':
            # Special handling for RX/TX rate
            rx_rate = [tm_data['rx_rate'][i] / 1_000_000 for i in valid_idx]  # Convert to Mbps
            tx_rate = [tm_data['tx_rate'][i] / 1_000_000 for i in valid_idx]
            ax.plot(time, rx_rate, color='green', linewidth=1.5, label='RX Rate')
            ax.plot(time, tx_rate, color='purple', linewidth=1.5, label='TX Rate')
        elif fields[0] in ['egress_usage', 'egress_wm', 'd_egress_drop']:
            # Egress port level metrics
            values = [tm_data[fields[0]][i] for i in valid_idx]
            ax.plot(time, values, color=colors[0], linewidth=1.5, 
                    label=fields[0].replace('_', ' ').title())
        else:
            # Per-queue metrics (arrays)
            for qid in range(8):
                if tm_data[fields[0]][qid]:
                    values = [tm_data[fields[0]][qid][i] for i in valid_idx if i < len(tm_data[fields[0]][qid])]
                    if len(values) == len(time):
                        ax.plot(time, values, color=colors[qid], linewidth=1, 
                                label=f'Q{qid}', alpha=0.8)
    
    ax.set_xlabel('Time [s]', fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title or f"{default_title} (Port {tm_data['dev_port']})", fontsize=14)
    ax.set_xlim(0, max_time or (time[-1] if time else 1))
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', fontsize=9, ncol=2 if tm_data['queue_mode'] == 'all' else 1)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Saved {metric} plot to {output_file}")
    plt.close()


def plot_all_metrics(tm_data: Dict, output_file: str,
                     title: str = None, max_time: float = None):
    """
    Plot all metrics in a multi-panel figure.
    
    Args:
        tm_data: Parsed tm log data
        output_file: Output file path
        title: Custom title (optional)
        max_time: Maximum time to plot (optional)
    """
    # Metrics to plot in the combined view
    metrics_to_plot = ['queue_usage', 'queue_wm', 'drop_rate', 'rate']
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    axes = axes.flatten()
    
    time = tm_data['time']
    if max_time:
        valid_idx = [i for i, t in enumerate(time) if t <= max_time]
        time = [time[i] for i in valid_idx]
    else:
        valid_idx = list(range(len(time)))
    
    colors = plt.cm.tab10(np.linspace(0, 1, 10))
    
    for idx, metric in enumerate(metrics_to_plot):
        ax = axes[idx]
        config = METRICS_CONFIG[metric]
        ylabel = config['label']
        metric_title = config['title']
        
        if tm_data['queue_mode'] == 'single':
            queue_num = tm_data['queue']
            fields = config['fields_single']
            
            if metric == 'rate':
                rx_rate = [tm_data['rx_rate'][i] / 1_000_000 for i in valid_idx]
                tx_rate = [tm_data['tx_rate'][i] / 1_000_000 for i in valid_idx]
                ax.plot(time, rx_rate, color='green', linewidth=1.5, label='RX')
                ax.plot(time, tx_rate, color='purple', linewidth=1.5, label='TX')
            else:
                for field in fields:
                    values = [tm_data[field][i] for i in valid_idx]
                    ax.plot(time, values, color=colors[0], linewidth=1.5, 
                            label=f'Q{queue_num}')
        else:
            fields = config['fields_all']
            
            if metric == 'rate':
                rx_rate = [tm_data['rx_rate'][i] / 1_000_000 for i in valid_idx]
                tx_rate = [tm_data['tx_rate'][i] / 1_000_000 for i in valid_idx]
                ax.plot(time, rx_rate, color='green', linewidth=1.5, label='RX')
                ax.plot(time, tx_rate, color='purple', linewidth=1.5, label='TX')
            else:
                for qid in range(8):
                    if tm_data[fields[0]][qid]:
                        values = [tm_data[fields[0]][qid][i] for i in valid_idx 
                                  if i < len(tm_data[fields[0]][qid])]
                        if len(values) == len(time):
                            ax.plot(time, values, color=colors[qid], linewidth=1,
                                    label=f'Q{qid}', alpha=0.8)
        
        ax.set_xlabel('Time [s]', fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_title(metric_title, fontsize=11)
        ax.set_xlim(0, max_time or (time[-1] if time else 1))
        ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', fontsize=8, ncol=2 if tm_data['queue_mode'] == 'all' else 1)
    
    suptitle = title or f"TM Queue Metrics Overview (Port {tm_data['dev_port']})"
    plt.suptitle(suptitle, fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Saved all metrics plot to {output_file}")
    plt.close()


def plot_detailed_view(tm_data: Dict, output_file: str,
                       title: str = None, max_time: float = None):
    """
    Create a detailed multi-panel view with all available metrics.
    
    Args:
        tm_data: Parsed tm log data
        output_file: Output file path
        title: Custom title (optional)
        max_time: Maximum time to plot (optional)
    """
    time = tm_data['time']
    if max_time:
        valid_idx = [i for i, t in enumerate(time) if t <= max_time]
        time = [time[i] for i in valid_idx]
    else:
        valid_idx = list(range(len(time)))
    
    colors = plt.cm.tab10(np.linspace(0, 1, 10))
    
    if tm_data['queue_mode'] == 'single':
        # Single queue: 3 rows × 2 cols
        fig, axes = plt.subplots(3, 2, figsize=(14, 12))
        queue_num = tm_data['queue']
        
        # Row 1: Queue usage and watermark
        ax = axes[0, 0]
        values = [tm_data['queue_usage'][i] for i in valid_idx]
        ax.plot(time, values, color='blue', linewidth=1.5, label='Usage')
        ax.set_ylabel('Queue Usage [cells]')
        ax.set_title(f'Queue {queue_num} Usage')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
        ax = axes[0, 1]
        values = [tm_data['queue_wm'][i] for i in valid_idx]
        ax.plot(time, values, color='red', linewidth=1.5, label='Watermark')
        ax.set_ylabel('Queue Watermark [cells]')
        ax.set_title(f'Queue {queue_num} Watermark')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
        # Row 2: Drop rate and cumulative drops
        ax = axes[1, 0]
        values = [tm_data['d_queue_drop'][i] for i in valid_idx]
        ax.plot(time, values, color='red', linewidth=1.5, label='Drop Rate')
        ax.set_ylabel('Drop Rate [pkts/interval]')
        ax.set_title(f'Queue {queue_num} Drop Rate')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
        ax = axes[1, 1]
        values = [tm_data['queue_drop'][i] for i in valid_idx]
        ax.plot(time, values, color='darkred', linewidth=1.5, label='Cumulative')
        ax.set_ylabel('Drop Count [packets]')
        ax.set_title(f'Queue {queue_num} Cumulative Drops')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
        # Row 3: Egress port and RX/TX rate
        ax = axes[2, 0]
        values = [tm_data['egress_usage'][i] for i in valid_idx]
        ax.plot(time, values, color='blue', linewidth=1.5, alpha=0.7, label='Egress Usage')
        values = [tm_data['egress_wm'][i] for i in valid_idx]
        ax.plot(time, values, color='red', linewidth=1.5, alpha=0.7, label='Egress WM')
        ax.set_xlabel('Time [s]')
        ax.set_ylabel('Cells')
        ax.set_title('Egress Port Usage/Watermark')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
        ax = axes[2, 1]
        rx_rate = [tm_data['rx_rate'][i] / 1_000_000 for i in valid_idx]
        tx_rate = [tm_data['tx_rate'][i] / 1_000_000 for i in valid_idx]
        ax.plot(time, rx_rate, color='green', linewidth=1.5, label='RX Rate')
        ax.plot(time, tx_rate, color='purple', linewidth=1.5, label='TX Rate')
        ax.set_xlabel('Time [s]')
        ax.set_ylabel('Rate [Mbps]')
        ax.set_title(f'Port {tm_data["dev_port"]} RX/TX Rate')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
    else:
        # All queues: 4 rows × 2 cols
        fig, axes = plt.subplots(4, 2, figsize=(14, 16))
        
        # Row 1: All queues usage and watermark
        ax = axes[0, 0]
        for qid in range(8):
            if tm_data['q_usage'][qid]:
                values = [tm_data['q_usage'][qid][i] for i in valid_idx 
                          if i < len(tm_data['q_usage'][qid])]
                if len(values) == len(time):
                    ax.plot(time, values, color=colors[qid], linewidth=1, 
                            label=f'Q{qid}', alpha=0.8)
        ax.set_ylabel('Queue Usage [cells]')
        ax.set_title('All Queues Usage')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', ncol=4, fontsize=8)
        
        ax = axes[0, 1]
        for qid in range(8):
            if tm_data['q_wm'][qid]:
                values = [tm_data['q_wm'][qid][i] for i in valid_idx 
                          if i < len(tm_data['q_wm'][qid])]
                if len(values) == len(time):
                    ax.plot(time, values, color=colors[qid], linewidth=1,
                            label=f'Q{qid}', alpha=0.8)
        ax.set_ylabel('Queue Watermark [cells]')
        ax.set_title('All Queues Watermark')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', ncol=4, fontsize=8)
        
        # Row 2: All queues drop rate and cumulative drops
        ax = axes[1, 0]
        for qid in range(8):
            if tm_data['d_q_drop'][qid]:
                values = [tm_data['d_q_drop'][qid][i] for i in valid_idx 
                          if i < len(tm_data['d_q_drop'][qid])]
                if len(values) == len(time):
                    ax.plot(time, values, color=colors[qid], linewidth=1,
                            label=f'Q{qid}', alpha=0.8)
        ax.set_ylabel('Drop Rate [pkts/interval]')
        ax.set_title('All Queues Drop Rate')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', ncol=4, fontsize=8)
        
        ax = axes[1, 1]
        for qid in range(8):
            if tm_data['q_drop'][qid]:
                values = [tm_data['q_drop'][qid][i] for i in valid_idx 
                          if i < len(tm_data['q_drop'][qid])]
                if len(values) == len(time):
                    ax.plot(time, values, color=colors[qid], linewidth=1,
                            label=f'Q{qid}', alpha=0.8)
        ax.set_ylabel('Drop Count [packets]')
        ax.set_title('All Queues Cumulative Drops')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', ncol=4, fontsize=8)
        
        # Row 3: Sum drops and unattributed drops
        ax = axes[2, 0]
        values = [tm_data['sum_d_q_drop'][i] for i in valid_idx]
        ax.plot(time, values, color='red', linewidth=1.5, label='Sum Q Drops')
        values = [tm_data['d_egress_drop'][i] for i in valid_idx]
        ax.plot(time, values, color='darkred', linewidth=1.5, linestyle='--', 
                alpha=0.7, label='Egress Drops')
        ax.set_ylabel('Drop Rate [pkts/interval]')
        ax.set_title('Total Drop Rate')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
        ax = axes[2, 1]
        values = [tm_data['d_unattributed'][i] for i in valid_idx]
        ax.plot(time, values, color='orange', linewidth=1.5, label='Unattributed')
        ax.set_ylabel('Unattributed Drops [pkts/interval]')
        ax.set_title('Unattributed Drops (Egress - Sum of Queues)')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
        # Row 4: Egress port and RX/TX rate
        ax = axes[3, 0]
        values = [tm_data['egress_usage'][i] for i in valid_idx]
        ax.plot(time, values, color='blue', linewidth=1.5, alpha=0.7, label='Egress Usage')
        values = [tm_data['egress_wm'][i] for i in valid_idx]
        ax.plot(time, values, color='red', linewidth=1.5, alpha=0.7, label='Egress WM')
        ax.set_xlabel('Time [s]')
        ax.set_ylabel('Cells')
        ax.set_title('Egress Port Usage/Watermark')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
        ax = axes[3, 1]
        rx_rate = [tm_data['rx_rate'][i] / 1_000_000 for i in valid_idx]
        tx_rate = [tm_data['tx_rate'][i] / 1_000_000 for i in valid_idx]
        ax.plot(time, rx_rate, color='green', linewidth=1.5, label='RX Rate')
        ax.plot(time, tx_rate, color='purple', linewidth=1.5, label='TX Rate')
        ax.set_xlabel('Time [s]')
        ax.set_ylabel('Rate [Mbps]')
        ax.set_title(f'Port {tm_data["dev_port"]} RX/TX Rate')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
    
    suptitle = title or f"TM Queue Detailed View (Port {tm_data['dev_port']})"
    plt.suptitle(suptitle, fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Saved detailed view plot to {output_file}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Visualize tm_shape_queue TSV log files with support for multiple metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Visualize queue usage (default)
  python3 visualize_tm_queue.py --tm-log ./tm_log.tsv --output queue_usage.png
  
  # Visualize drop rate
  python3 visualize_tm_queue.py --tm-log ./tm_log.tsv --metric drop_rate --output drops.png
  
  # Visualize RX/TX rate
  python3 visualize_tm_queue.py --tm-log ./tm_log.tsv --metric rate --output rate.png
  
  # Visualize all metrics in one figure
  python3 visualize_tm_queue.py --tm-log ./tm_log.tsv --metric all --output all_metrics.png
  
  # Visualize detailed view with all available metrics
  python3 visualize_tm_queue.py --tm-log ./tm_log.tsv --metric detailed --output detailed.png

Available metrics:
  - queue_usage: Queue usage in cells
  - queue_wm: Queue watermark in cells
  - drop_rate: Drop rate per interval (packets/interval)
  - drop_count: Cumulative drop count (packets)
  - egress_usage: Egress port usage in cells
  - egress_wm: Egress port watermark in cells
  - egress_drop_rate: Egress port drop rate per interval
  - rate: Port RX/TX rate in Mbps
  - all: Plot major metrics (usage, watermark, drops, rate) in one figure
  - detailed: Plot all available metrics in a detailed multi-panel figure
        """
    )
    
    parser.add_argument("--tm-log", required=True,
                        help="Path to tm_shape_queue TSV log file")
    parser.add_argument("--output", default="tm_queue_plot.png",
                        help="Output file name (default: tm_queue_plot.png)")
    parser.add_argument("--metric", default="queue_usage",
                        choices=['queue_usage', 'queue_wm', 'drop_rate', 'drop_count',
                                 'egress_usage', 'egress_wm', 'egress_drop_rate', 
                                 'rate', 'all', 'detailed'],
                        help="Metric to plot (default: queue_usage)")
    parser.add_argument("--title", default=None,
                        help="Custom title for the plot")
    parser.add_argument("--max-time", type=float, default=None,
                        help="Maximum time to plot in seconds (default: all data)")
    
    args = parser.parse_args()
    
    # Validate file
    if not os.path.isfile(args.tm_log):
        print(f"Error: File '{args.tm_log}' does not exist")
        sys.exit(1)
    
    # Load data
    print(f"Loading tm_shape_queue log from: {args.tm_log}")
    tm_data = parse_tm_log(args.tm_log)
    
    if tm_data is None:
        print("Error: Failed to parse tm_shape_queue log file")
        sys.exit(1)
    
    # Generate plot based on metric type
    if args.metric == 'all':
        plot_all_metrics(tm_data, args.output, args.title, args.max_time)
    elif args.metric == 'detailed':
        plot_detailed_view(tm_data, args.output, args.title, args.max_time)
    else:
        plot_single_metric(tm_data, args.output, args.metric, args.title, args.max_time)
    
    print("Visualization complete!")


if __name__ == "__main__":
    main()
