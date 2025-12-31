#!/usr/bin/env python3
"""
High-precision TCP metrics collector for concurrent flows (Cubic + Prague).

This script uses the `ss` command to collect TCP socket statistics at millisecond
precision, properly identifying each flow by its port number and congestion control
algorithm.

Features:
- Millisecond-level sampling precision (configurable, default 1ms)
- Proper flow identification by port and congestion control algorithm
- Records: RTT, RTT variance, cwnd, ssthresh, bytes_sent, bytes_acked, 
  delivery_rate, pacing_rate, retransmits, lost packets
- Outputs to CSV format with proper flow identification

Usage:
    python3 tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 1 --duration 480 --output ./exp_logs_I/tcp_metrics.csv

Requirements:
    - Linux with iproute2 (ss command)
    - Python 3.6+
    - Root/sudo privileges for detailed socket info
"""

import argparse
import csv
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np

# Port ranges for identifying flow types (matching gen_experiment.py)
CUBIC_PORT_MIN = 5201
CUBIC_PORT_MAX = 5225
PRAGUE_PORT_MIN = 5226
PRAGUE_PORT_MAX = 5250


@dataclass
class TCPFlowMetrics:
    """Represents metrics for a single TCP flow at a point in time."""
    timestamp_ns: int
    timestamp_ms: float  # Relative time in milliseconds
    local_addr: str
    local_port: int
    remote_addr: str
    remote_port: int
    state: str
    congestion_algo: str  # cubic, prague, bbr, etc.
    flow_type: str  # cubic, prague, unknown (based on port)
    flow_id: str  # Unique identifier for the flow
    
    # Core metrics
    cwnd: int = 0
    ssthresh: int = 0
    rtt_us: float = 0.0  # RTT in microseconds
    rttvar_us: float = 0.0  # RTT variance in microseconds
    rto_ms: int = 0  # Retransmission timeout in milliseconds
    mss: int = 0
    
    # Byte counters
    bytes_sent: int = 0
    bytes_acked: int = 0
    bytes_received: int = 0
    
    # Segment counters
    segs_out: int = 0
    segs_in: int = 0
    
    # Loss/retransmit metrics
    retrans: int = 0
    lost: int = 0
    
    # Rate metrics (in bps)
    delivery_rate_bps: float = 0.0
    pacing_rate_bps: float = 0.0
    
    # ECN metrics (important for Prague)
    ecn_flags: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for CSV output."""
        return {
            'timestamp_ns': self.timestamp_ns,
            'local_port': self.local_port,
            'remote_port': self.remote_port,
            'state': self.state,
            'flow_type': self.flow_type,
            'flow_id': self.flow_id,
            'cwnd': self.cwnd,
            'rtt_us': f"{self.rtt_us:.3f}",
            'rtt_var_us': f"{self.rttvar_us:.3f}",
            'retrans': self.retrans,
            'lost': self.lost,
            'delivery_rate_bps': f"{self.delivery_rate_bps:.0f}",
        }


def identify_flow_type(local_port: int, remote_port: int) -> str:
    """Identify flow type based on port numbers."""
    # Check local port first (sender side)
    if CUBIC_PORT_MIN <= local_port <= CUBIC_PORT_MAX:
        return 'cubic'
    elif PRAGUE_PORT_MIN <= local_port <= PRAGUE_PORT_MAX:
        return 'prague'
    # Check remote port (receiver side)
    elif CUBIC_PORT_MIN <= remote_port <= CUBIC_PORT_MAX:
        return 'cubic'
    elif PRAGUE_PORT_MIN <= remote_port <= PRAGUE_PORT_MAX:
        return 'prague'
    else:
        return 'unknown'


def parse_rate(rate_str: str) -> float:
    """Parse rate string (e.g., '100Mbps', '1.5Gbps') to bps."""
    if not rate_str:
        return 0.0
    
    rate_str = rate_str.strip()
    multipliers = {
        'bps': 1,
        'Kbps': 1_000,
        'Mbps': 1_000_000,
        'Gbps': 1_000_000_000,
    }
    
    for suffix, mult in multipliers.items():
        if rate_str.endswith(suffix):
            try:
                return float(rate_str[:-len(suffix)]) * mult
            except ValueError:
                return 0.0
    
    # Try parsing as plain number
    try:
        return float(rate_str)
    except ValueError:
        return 0.0


def parse_ss_output(ss_output: str, timestamp_ns: int, start_time_ns: int) -> List[TCPFlowMetrics]:
    """
    Parse ss -tin output and extract TCP flow metrics.
    
    The ss output format is:
    ESTAB  0  0  192.168.6.1:5201  192.168.6.2:54321
        cubic wscale:7,7 rto:212 rtt:10.5/0.5 ato:40 mss:1448 pmtu:1500 rcvmss:536 advmss:1448 cwnd:10 ssthresh:7 bytes_sent:1234 bytes_acked:1000 ...
    """
    flows = []
    lines = ss_output.strip().split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Skip empty lines
        if not line:
            i += 1
            continue
        
        # Look for connection line (starts with state like ESTAB, SYN-SENT, etc.)
        if line.startswith(('ESTAB', 'SYN-SENT', 'SYN-RECV', 'FIN-WAIT', 'TIME-WAIT', 'CLOSE', 'LAST-ACK')):
            parts = line.split()
            if len(parts) >= 5:
                state = parts[0]
                # Parse local address:port
                local_parts = parts[3].rsplit(':', 1)
                if len(local_parts) == 2:
                    local_addr = local_parts[0]
                    try:
                        local_port = int(local_parts[1])
                    except ValueError:
                        local_port = 0
                else:
                    local_addr = parts[3]
                    local_port = 0
                
                # Parse remote address:port
                remote_parts = parts[4].rsplit(':', 1)
                if len(remote_parts) == 2:
                    remote_addr = remote_parts[0]
                    try:
                        remote_port = int(remote_parts[1])
                    except ValueError:
                        remote_port = 0
                else:
                    remote_addr = parts[4]
                    remote_port = 0
                
                # Look for the next line with detailed info
                if i + 1 < len(lines):
                    detail_line = lines[i + 1].strip()
                    
                    # Parse the detail line
                    metrics = parse_detail_line(
                        detail_line, timestamp_ns, start_time_ns,
                        local_addr, local_port, remote_addr, remote_port, state
                    )
                    
                    if metrics:
                        flows.append(metrics)
                    
                    i += 2
                    continue
        
        i += 1
    
    return flows


def parse_detail_line(detail_line: str, timestamp_ns: int, start_time_ns: int,
                      local_addr: str, local_port: int, 
                      remote_addr: str, remote_port: int, state: str) -> Optional[TCPFlowMetrics]:
    """Parse the detail line from ss output."""
    
    # Detect congestion control algorithm
    congestion_algo = 'unknown'
    for algo in ['cubic', 'prague', 'bbr', 'reno', 'vegas', 'westwood', 'htcp', 'dctcp']:
        if algo in detail_line.lower():
            congestion_algo = algo
            break
    
    # Skip if no recognized congestion control (might be a control connection)
    if congestion_algo == 'unknown':
        return None
    
    # Calculate relative timestamp in milliseconds
    timestamp_ms = (timestamp_ns - start_time_ns) / 1_000_000
    
    # Identify flow type based on port
    flow_type = identify_flow_type(local_port, remote_port)
    
    # Create unique flow ID
    flow_id = f"{flow_type}_{local_port}_{remote_port}"
    
    # Initialize metrics
    metrics = TCPFlowMetrics(
        timestamp_ns=timestamp_ns,
        timestamp_ms=timestamp_ms,
        local_addr=local_addr,
        local_port=local_port,
        remote_addr=remote_addr,
        remote_port=remote_port,
        state=state,
        congestion_algo=congestion_algo,
        flow_type=flow_type,
        flow_id=flow_id,
    )
    
    # Parse key-value pairs from detail line
    # Common patterns: key:value or key:value/value2
    
    # cwnd
    match = re.search(r'\bcwnd:(\d+)', detail_line)
    if match:
        metrics.cwnd = int(match.group(1))
    
    # ssthresh
    match = re.search(r'\bssthresh:(\d+)', detail_line)
    if match:
        metrics.ssthresh = int(match.group(1))
    
    # rtt (format: rtt:10.5/0.5 means rtt=10.5ms, rttvar=0.5ms)
    # Note: ss reports RTT in milliseconds, we convert to microseconds for precision
    match = re.search(r'\brtt:([\d.]+)/([\d.]+)', detail_line)
    if match:
        metrics.rtt_us = float(match.group(1)) * 1000  # ms to us
        metrics.rttvar_us = float(match.group(2)) * 1000  # ms to us
    
    # rto
    match = re.search(r'\brto:(\d+)', detail_line)
    if match:
        metrics.rto_ms = int(match.group(1))
    
    # mss
    match = re.search(r'\bmss:(\d+)', detail_line)
    if match:
        metrics.mss = int(match.group(1))
    
    # bytes_sent
    match = re.search(r'\bbytes_sent:(\d+)', detail_line)
    if match:
        metrics.bytes_sent = int(match.group(1))
    
    # bytes_acked
    match = re.search(r'\bbytes_acked:(\d+)', detail_line)
    if match:
        metrics.bytes_acked = int(match.group(1))
    
    # bytes_received
    match = re.search(r'\bbytes_received:(\d+)', detail_line)
    if match:
        metrics.bytes_received = int(match.group(1))
    
    # segs_out
    match = re.search(r'\bsegs_out:(\d+)', detail_line)
    if match:
        metrics.segs_out = int(match.group(1))
    
    # segs_in
    match = re.search(r'\bsegs_in:(\d+)', detail_line)
    if match:
        metrics.segs_in = int(match.group(1))
    
    # retrans (format: retrans:0/1 means current/total)
    match = re.search(r'\bretrans:(\d+)/(\d+)', detail_line)
    if match:
        metrics.retrans = int(match.group(2))  # Total retransmits
    else:
        match = re.search(r'\bretrans:(\d+)', detail_line)
        if match:
            metrics.retrans = int(match.group(1))
    
    # lost
    match = re.search(r'\blost:(\d+)', detail_line)
    if match:
        metrics.lost = int(match.group(1))
    
    # delivery_rate
    match = re.search(r'\bdelivery_rate\s+([\d.]+[KMG]?bps)', detail_line)
    if match:
        metrics.delivery_rate_bps = parse_rate(match.group(1))
    
    # pacing_rate
    match = re.search(r'\bpacing_rate\s+([\d.]+[KMG]?bps)', detail_line)
    if match:
        metrics.pacing_rate_bps = parse_rate(match.group(1))
    
    # ECN flags
    ecn_flags = []
    if 'ecn' in detail_line.lower():
        ecn_flags.append('ecn')
    if 'ecnseen' in detail_line.lower():
        ecn_flags.append('ecnseen')
    if 'ce_mark' in detail_line.lower():
        ecn_flags.append('ce_mark')
    metrics.ecn_flags = ','.join(ecn_flags)
    
    return metrics


def collect_tcp_metrics(dst_ip: str) -> str:
    """Run ss command and return output."""
    try:
        # Use ss with:
        # -t: TCP sockets
        # -i: Show internal TCP info
        # -n: Don't resolve names
        # dst/src filter: Only connections to/from target IP
        cmd = ['ss', '-tin', f'dst {dst_ip} or src {dst_ip}']
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1.0  # 1 second timeout
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return ""
    except Exception as e:
        print(f"Error running ss: {e}", file=sys.stderr)
        return ""


class RealTimePlotter:
    """Real-time plotter for TCP metrics."""
    
    def __init__(self, output_dir: str = "./plots", plot_interval: int = 1000):
        """
        Initialize the real-time plotter.
        
        Args:
            output_dir: Directory to save plots
            plot_interval: Number of samples between plot updates
        """
        self.output_dir = output_dir
        self.plot_interval = plot_interval
        self.sample_count = 0
        
        # Data storage for plotting
        self.data = {
            'time_sec': [],
            'rtt_ms': [],
            'cwnd': [],
            'delivery_rate_mbps': [],
            'retrans': [],
            'flow_type': [],
            'flow_id': [],
        }
        
        # Create output directory
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Color palette
        self.palette = {"cubic": "blue", "prague": "orange"}
    
    def add_data(self, flows: List[TCPFlowMetrics], start_time_ns: int):
        """Add flow data to the plotter."""
        for flow in flows:
            time_sec = (flow.timestamp_ns - start_time_ns) / 1e9
            self.data['time_sec'].append(time_sec)
            self.data['rtt_ms'].append(flow.rtt_us / 1000.0)
            self.data['cwnd'].append(flow.cwnd)
            self.data['delivery_rate_mbps'].append(flow.delivery_rate_bps / 1e6)
            self.data['retrans'].append(flow.retrans)
            self.data['flow_type'].append(flow.flow_type)
            self.data['flow_id'].append(flow.flow_id)
        
        self.sample_count += 1
    
    def should_plot(self) -> bool:
        """Check if it's time to update plots."""
        return self.sample_count % self.plot_interval == 0
    
    def plot_metrics(self):
        """Generate and save plots for all metrics."""
        if not self.data['time_sec']:
            return
        
        # Convert to numpy arrays for faster processing
        time_sec = np.array(self.data['time_sec'])
        rtt_ms = np.array(self.data['rtt_ms'])
        cwnd = np.array(self.data['cwnd'])
        delivery_rate_mbps = np.array(self.data['delivery_rate_mbps'])
        retrans = np.array(self.data['retrans'])
        flow_type = np.array(self.data['flow_type'])
        flow_id = np.array(self.data['flow_id'])
        
        # Plot RTT
        self._plot_single_metric(
            time_sec, rtt_ms, flow_type, flow_id,
            'RTT over Time', 'RTT (ms)', 'rtt_over_time.png'
        )
        
        # Plot CWND
        self._plot_single_metric(
            time_sec, cwnd, flow_type, flow_id,
            'Congestion Window over Time', 'CWND (segments)', 'cwnd_over_time.png'
        )
        
        # Plot Delivery Rate
        self._plot_single_metric(
            time_sec, delivery_rate_mbps, flow_type, flow_id,
            'Delivery Rate over Time', 'Delivery Rate (Mbps)', 'delivery_rate_over_time.png',
            use_log_scale=True
        )
        
        # Plot Retransmits
        self._plot_single_metric(
            time_sec, retrans, flow_type, flow_id,
            'Retransmits over Time', 'Cumulative Retransmits', 'retransmits_over_time.png'
        )
    
    def _plot_single_metric(self, time_sec, values, flow_type, flow_id,
                           title, ylabel, filename, use_log_scale=False):
        """Plot a single metric."""
        fig, ax = plt.subplots(figsize=(14, 7))
        
        # Plot each flow type
        for ft, color in self.palette.items():
            mask = flow_type == ft
            if not np.any(mask):
                continue
            
            # Get unique flow IDs for this type
            unique_flow_ids = np.unique(flow_id[mask])
            
            for fid in unique_flow_ids:
                flow_mask = (flow_type == ft) & (flow_id == fid)
                
                # Create a copy of values for this flow and set invalid values to NaN
                # This prevents matplotlib from drawing horizontal lines across gaps
                flow_values = np.where(flow_mask, values, np.nan)
                
                # Set invalid/zero values to NaN to avoid horizontal lines
                # RTT should be > 0, CWND should be > 0, delivery_rate can be 0 but skip if all zeros
                if 'RTT' in title:
                    flow_values = np.where(flow_values <= 0, np.nan, flow_values)
                elif 'CWND' in title:
                    flow_values = np.where(flow_values <= 0, np.nan, flow_values)
                elif 'Delivery Rate' in title:
                    # For delivery rate, set 0 values to NaN (inactive flows)
                    flow_values = np.where(flow_values <= 0, np.nan, flow_values)
                # For retransmits, 0 is valid, so don't modify
                
                # Skip if no valid data points
                if np.all(np.isnan(flow_values)):
                    continue
                
                ax.plot(time_sec, flow_values,
                       color=color, linewidth=0.5, alpha=0.8, label=f"{ft}" if fid == unique_flow_ids[0] else "")
        
        ax.set_title(title, fontsize=16)
        ax.set_xlabel('Time (s)', fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        
        # Create legend with only one entry per flow type
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        ax.legend(by_label.values(), by_label.keys(), loc='upper right')
        
        ax.grid(True, alpha=0.3)
        
        if use_log_scale:
            ax.set_yscale('log')
        
        plt.tight_layout()
        output_path = os.path.join(self.output_dir, filename)
        plt.savefig(output_path, dpi=150)
        plt.close()


def high_precision_sleep(duration_sec: float):
    """
    High-precision sleep using busy-wait for sub-millisecond accuracy.
    For durations > 10ms, uses regular sleep.
    """
    if duration_sec <= 0:
        return
    
    if duration_sec > 0.01:  # > 10ms
        time.sleep(duration_sec)
    else:
        # Busy-wait for high precision
        end_time = time.perf_counter() + duration_sec
        while time.perf_counter() < end_time:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="High-precision TCP metrics collector for concurrent flows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect metrics at 1ms intervals for 60 seconds
  python3 tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 1 --duration 60

  # Collect metrics at 2ms intervals for 480 seconds (8 minutes)
  python3 tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 2 --duration 480 --output ./exp_logs_I/tcp_metrics.csv

  # Collect with verbose output
  python3 tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 5 --duration 30 --verbose

Output CSV columns:
  - timestamp_ns: Nanosecond timestamp
  - local_port: Local port number
  - remote_port: Remote port number
  - state: TCP connection state
  - flow_type: Flow type based on port (cubic, prague, unknown)
  - flow_id: Unique flow identifier
  - cwnd: Congestion window in segments
  - rtt_us: RTT in microseconds
  - rtt_var_us: RTT variance in microseconds
  - retrans: Retransmit counter
  - lost: Lost packet counter
  - delivery_rate_bps: Delivery rate in bits per second
        """
    )
    
    parser.add_argument("--dst-ip", required=True,
                        help="Destination IP address to filter connections")
    parser.add_argument("--interval-ms", type=float, default=1.0,
                        help="Sampling interval in milliseconds (default: 1)")
    parser.add_argument("--duration", type=float, default=60.0,
                        help="Collection duration in seconds (default: 60)")
    parser.add_argument("--output", default="./tcp_metrics.csv",
                        help="Output CSV file path (default: ./tcp_metrics.csv)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print progress information")
    parser.add_argument("--no-header", action="store_true",
                        help="Don't write CSV header (for appending)")
    parser.add_argument("--plot", action="store_true",
                        help="Enable real-time plotting during collection")
    parser.add_argument("--plot-dir", default="./plots",
                        help="Directory to save real-time plots (default: ./plots)")
    parser.add_argument("--plot-interval", type=int, default=1000,
                        help="Number of samples between plot updates (default: 1000)")
    
    args = parser.parse_args()
    
    # Create output directory if needed
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Calculate timing
    interval_sec = args.interval_ms / 1000.0
    total_samples = int(args.duration / interval_sec)
    
    print(f"TCP Metrics Collector")
    print(f"  Target IP: {args.dst_ip}")
    print(f"  Interval: {args.interval_ms}ms")
    print(f"  Duration: {args.duration}s")
    print(f"  Expected samples: ~{total_samples}")
    print(f"  Output: {args.output}")
    if args.plot:
        print(f"  Real-time plotting: ENABLED")
        print(f"  Plot directory: {args.plot_dir}")
        print(f"  Plot update interval: every {args.plot_interval} samples")
    print()
    
    # CSV field names
    fieldnames = [
        'timestamp_ns', 'local_port', 'remote_port', 'state',
        'flow_type', 'flow_id', 'cwnd', 'rtt_us', 'rtt_var_us',
        'retrans', 'lost', 'delivery_rate_bps'
    ]
    
    # Open output file
    with open(args.output, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        if not args.no_header:
            writer.writeheader()
        
        # Initialize real-time plotter if enabled
        plotter = None
        if args.plot:
            plotter = RealTimePlotter(output_dir=args.plot_dir, plot_interval=args.plot_interval)
        
        # Record start time
        start_time_ns = time.time_ns()
        start_time_perf = time.perf_counter()
        end_time_perf = start_time_perf + args.duration
        
        sample_count = 0
        flow_count = 0
        last_progress_time = start_time_perf
        last_plot_time = start_time_perf
        
        print(f"Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("Press Ctrl+C to stop early")
        print()
        
        try:
            while time.perf_counter() < end_time_perf:
                sample_start = time.perf_counter()
                
                # Get current timestamp
                timestamp_ns = time.time_ns()
                
                # Collect metrics
                ss_output = collect_tcp_metrics(args.dst_ip)
                
                # Parse output
                flows = parse_ss_output(ss_output, timestamp_ns, start_time_ns)
                
                # Write to CSV
                for flow in flows:
                    writer.writerow(flow.to_dict())
                    flow_count += 1
                
                # Add data to plotter if enabled
                if plotter:
                    plotter.add_data(flows, start_time_ns)
                
                sample_count += 1
                
                # Progress update every second
                current_time = time.perf_counter()
                if args.verbose and current_time - last_progress_time >= 1.0:
                    elapsed = current_time - start_time_perf
                    remaining = args.duration - elapsed
                    print(f"\r  Elapsed: {elapsed:.1f}s, Remaining: {remaining:.1f}s, "
                          f"Samples: {sample_count}, Flow records: {flow_count}", end='')
                    last_progress_time = current_time
                
                # Update plots if enabled and interval reached
                if plotter and plotter.should_plot():
                    plot_start = time.perf_counter()
                    plotter.plot_metrics()
                    plot_duration = time.perf_counter() - plot_start
                    if args.verbose:
                        print(f"\n  Plots updated in {plot_duration:.2f}s")
                
                # Calculate sleep time to maintain interval
                sample_duration = time.perf_counter() - sample_start
                sleep_time = interval_sec - sample_duration
                
                if sleep_time > 0:
                    high_precision_sleep(sleep_time)
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
        
        finally:
            # Flush output
            csvfile.flush()
    
    # Summary
    elapsed = time.perf_counter() - start_time_perf
    print(f"\n\nCollection complete!")
    print(f"  Duration: {elapsed:.2f}s")
    print(f"  Samples: {sample_count}")
    print(f"  Flow records: {flow_count}")
    print(f"  Average sample rate: {sample_count / elapsed:.1f} samples/s")
    print(f"  Output saved to: {args.output}")
    if plotter:
        print(f"  Plots saved to: {args.plot_dir}")
    
    # Show file size
    file_size = os.path.getsize(args.output)
    if file_size > 1_000_000:
        print(f"  File size: {file_size / 1_000_000:.2f} MB")
    else:
        print(f"  File size: {file_size / 1_000:.2f} KB")


if __name__ == "__main__":
    main()
