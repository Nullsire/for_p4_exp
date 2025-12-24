#!/usr/bin/env python3
"""
Merge iperf3 JSON logs from sender and receiver sides.

This script combines sender and receiver iperf3 logs to create merged JSON files
that contain the most accurate metrics from each side:
  - From SENDER: rtt, rttvar, snd_cwnd, retransmits (accurate)
  - From RECEIVER: bits_per_second (goodput - accurate)

The merged logs can then be used with visualize_iperf3.py for accurate visualization.

Usage:
    python3 merge_iperf3_logs.py --sender-dir ./exp_logs_I --receiver-dir ./exp_logs_I_receiver --output-dir ./merged_logs_I

    # Then visualize with:
    python3 visualize_iperf3.py --iperf-dir ./merged_logs_I --metric goodput --output goodput.png
"""

import argparse
import json
import os
import glob
import sys
from typing import Dict, List, Tuple, Optional, Any
from copy import deepcopy


def load_iperf3_json(filepath: str) -> Optional[Dict]:
    """Load iperf3 JSON log file."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not load {filepath}: {e}")
        return None


def get_flow_info(filepath: str) -> Tuple[str, int]:
    """Extract flow type and ID from filename.
    
    Args:
        filepath: Path like './exp_logs_I/cubic_flow_1.json'
        
    Returns:
        Tuple of (flow_type, flow_id), e.g., ('cubic', 1)
    """
    filename = os.path.basename(filepath)
    name = os.path.splitext(filename)[0]
    
    if name.startswith('cubic_flow_'):
        return 'cubic', int(name.split('_')[-1])
    elif name.startswith('prague_flow_'):
        return 'prague', int(name.split('_')[-1])
    else:
        # Try to extract any flow type and ID
        parts = name.split('_')
        if len(parts) >= 2:
            try:
                flow_id = int(parts[-1])
                flow_type = '_'.join(parts[:-2]) if 'flow' in parts else parts[0]
                return flow_type, flow_id
            except ValueError:
                pass
        return 'unknown', 0


def merge_interval_data(sender_interval: Dict, receiver_interval: Dict) -> Dict:
    """Merge interval data from sender and receiver.
    
    Takes accurate metrics from each side:
    - From sender: rtt, rttvar, snd_cwnd, snd_wnd, retransmits
    - From receiver: bits_per_second, bytes
    
    Args:
        sender_interval: Interval data from sender log
        receiver_interval: Interval data from receiver log
        
    Returns:
        Merged interval data
    """
    merged = deepcopy(sender_interval)
    
    # Fields to take from receiver (goodput-related)
    receiver_fields = ['bits_per_second', 'bytes']
    
    # Merge stream data
    if 'streams' in merged and 'streams' in receiver_interval:
        for i, stream in enumerate(merged['streams']):
            if i < len(receiver_interval['streams']):
                recv_stream = receiver_interval['streams'][i]
                for field in receiver_fields:
                    if field in recv_stream:
                        stream[field] = recv_stream[field]
    
    # Merge sum data
    if 'sum' in merged and 'sum' in receiver_interval:
        for field in receiver_fields:
            if field in receiver_interval['sum']:
                merged['sum'][field] = receiver_interval['sum'][field]
    
    return merged


def align_intervals(sender_intervals: List[Dict], receiver_intervals: List[Dict]) -> List[Tuple[Dict, Dict]]:
    """Align sender and receiver intervals by timestamp.
    
    iperf3 intervals may not be perfectly aligned, so we match them by closest end time.
    
    Args:
        sender_intervals: List of interval data from sender
        receiver_intervals: List of interval data from receiver
        
    Returns:
        List of (sender_interval, receiver_interval) tuples
    """
    aligned = []
    
    # Build list of receiver intervals with time
    recv_list = []
    for interval in receiver_intervals:
        if 'sum' in interval:
            end_time = interval['sum'].get('end', 0)
        elif 'streams' in interval and len(interval['streams']) > 0:
            end_time = interval['streams'][0].get('end', 0)
        else:
            continue
        recv_list.append((end_time, interval))
    
    # Sort by time
    recv_list.sort(key=lambda x: x[0])
    
    # Match sender intervals to receiver intervals
    for sender_int in sender_intervals:
        if 'sum' in sender_int:
            end_time = sender_int['sum'].get('end', 0)
        elif 'streams' in sender_int and len(sender_int['streams']) > 0:
            end_time = sender_int['streams'][0].get('end', 0)
        else:
            continue
        
        # Find closest receiver interval
        best_match = None
        min_diff = float('inf')
        
        # Simple linear search (efficient enough for typical log sizes)
        for r_time, r_int in recv_list:
            diff = abs(r_time - end_time)
            if diff < min_diff:
                min_diff = diff
                best_match = r_int
        
        # Use a tolerance threshold (e.g., 0.2s) to accept the match
        # This handles jitter while avoiding matching completely different intervals
        if best_match and min_diff < 0.2:
            aligned.append((sender_int, best_match))
        else:
            # No matching receiver interval, use sender data only
            aligned.append((sender_int, sender_int))
    
    return aligned


def merge_iperf3_logs(sender_data: Dict, receiver_data: Dict) -> Dict:
    """Merge sender and receiver iperf3 JSON data.
    
    Args:
        sender_data: Parsed JSON from sender log
        receiver_data: Parsed JSON from receiver log
        
    Returns:
        Merged JSON data with accurate metrics from each side
    """
    merged = deepcopy(sender_data)
    
    # Add metadata about merge
    if 'start' not in merged:
        merged['start'] = {}
    merged['start']['merged'] = True
    merged['start']['merge_info'] = {
        'sender_metrics': ['rtt', 'rttvar', 'snd_cwnd', 'snd_wnd', 'retransmits'],
        'receiver_metrics': ['bits_per_second', 'bytes']
    }
    
    # Merge intervals
    if 'intervals' in merged and 'intervals' in receiver_data:
        sender_intervals = merged['intervals']
        receiver_intervals = receiver_data['intervals']
        
        aligned = align_intervals(sender_intervals, receiver_intervals)
        
        merged_intervals = []
        for sender_int, recv_int in aligned:
            merged_int = merge_interval_data(sender_int, recv_int)
            merged_intervals.append(merged_int)
        
        merged['intervals'] = merged_intervals
    
    # Merge end summary - take goodput from receiver
    if 'end' in merged and 'end' in receiver_data:
        # Copy receiver's sum_received for accurate goodput
        if 'sum_received' in receiver_data['end']:
            merged['end']['sum_received'] = receiver_data['end']['sum_received']
        
        # Keep sender's sum_sent for retransmits etc
        # (already in merged from sender_data)
    
    return merged


def process_directory(sender_dir: str, receiver_dir: str, output_dir: str, 
                     verbose: bool = True) -> Dict[str, int]:
    """Process all flow logs in sender and receiver directories.
    
    Args:
        sender_dir: Directory containing sender iperf3 logs
        receiver_dir: Directory containing receiver iperf3 logs
        output_dir: Directory to write merged logs
        verbose: Whether to print progress
        
    Returns:
        Statistics dict with counts
    """
    os.makedirs(output_dir, exist_ok=True)
    
    stats = {
        'merged': 0,
        'sender_only': 0,
        'receiver_only': 0,
        'failed': 0
    }
    
    # Find all sender logs
    sender_files = glob.glob(os.path.join(sender_dir, "*.json"))
    
    if not sender_files:
        print(f"Warning: No JSON files found in sender directory: {sender_dir}")
    
    # Create a map of flow -> receiver file
    receiver_map = {}
    receiver_files = glob.glob(os.path.join(receiver_dir, "*.json"))
    for rf in receiver_files:
        flow_type, flow_id = get_flow_info(rf)
        if flow_type != 'unknown':
            receiver_map[(flow_type, flow_id)] = rf
    
    # Process each sender file
    for sender_file in sorted(sender_files):
        flow_type, flow_id = get_flow_info(sender_file)
        
        if flow_type == 'unknown':
            if verbose:
                print(f"Skipping unknown file format: {sender_file}")
            continue
        
        output_file = os.path.join(output_dir, f"{flow_type}_flow_{flow_id}.json")
        
        # Load sender data
        sender_data = load_iperf3_json(sender_file)
        if sender_data is None:
            stats['failed'] += 1
            continue
        
        # Find matching receiver file
        receiver_file = receiver_map.get((flow_type, flow_id))
        
        if receiver_file:
            receiver_data = load_iperf3_json(receiver_file)
            
            if receiver_data:
                # Merge sender and receiver data
                merged_data = merge_iperf3_logs(sender_data, receiver_data)
                stats['merged'] += 1
                if verbose:
                    print(f"✓ Merged {flow_type}_flow_{flow_id}: {sender_file} + {receiver_file}")
            else:
                # Use sender data only
                merged_data = sender_data
                merged_data['start'] = merged_data.get('start', {})
                merged_data['start']['merged'] = False
                merged_data['start']['merge_info'] = 'receiver_load_failed'
                stats['sender_only'] += 1
                if verbose:
                    print(f"⚠ Sender only {flow_type}_flow_{flow_id}: receiver load failed")
        else:
            # No receiver file, use sender data only
            merged_data = sender_data
            merged_data['start'] = merged_data.get('start', {})
            merged_data['start']['merged'] = False
            merged_data['start']['merge_info'] = 'no_receiver_file'
            stats['sender_only'] += 1
            if verbose:
                print(f"⚠ Sender only {flow_type}_flow_{flow_id}: no receiver file found")
        
        # Write merged data
        with open(output_file, 'w') as f:
            json.dump(merged_data, f, indent=2)
    
    # Check for receiver-only files
    processed_flows = set()
    for sf in sender_files:
        ft, fid = get_flow_info(sf)
        if ft != 'unknown':
            processed_flows.add((ft, fid))
    
    for (flow_type, flow_id), receiver_file in receiver_map.items():
        if (flow_type, flow_id) not in processed_flows:
            # Receiver file without sender file
            receiver_data = load_iperf3_json(receiver_file)
            if receiver_data:
                receiver_data['start'] = receiver_data.get('start', {})
                receiver_data['start']['merged'] = False
                receiver_data['start']['merge_info'] = 'receiver_only'
                
                output_file = os.path.join(output_dir, f"{flow_type}_flow_{flow_id}.json")
                with open(output_file, 'w') as f:
                    json.dump(receiver_data, f, indent=2)
                
                stats['receiver_only'] += 1
                if verbose:
                    print(f"⚠ Receiver only {flow_type}_flow_{flow_id}: no sender file found")
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Merge iperf3 JSON logs from sender and receiver sides",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic merge
    python3 merge_iperf3_logs.py --sender-dir ./exp_logs_I --receiver-dir ./exp_logs_I_receiver --output-dir ./merged_logs_I
    
    # Then visualize the merged logs
    python3 visualize_iperf3.py --iperf-dir ./merged_logs_I --metric goodput --output goodput.png
    python3 visualize_iperf3.py --iperf-dir ./merged_logs_I --metric rtt --output rtt.png
    
Merge Logic:
    The script combines the most accurate metrics from each side:
    
    FROM SENDER (accurate):
      - rtt: Round-trip time (measured via ACK timing)
      - rttvar: RTT variance
      - snd_cwnd: Congestion window size
      - retransmits: Retransmission count
    
    FROM RECEIVER (accurate):
      - bits_per_second: Actual received goodput
      - bytes: Actual received bytes
    
    This is necessary because:
      - Sender's bits_per_second reflects TCP send buffer writes, not actual delivered data
      - Receiver's RTT is not available (only sender measures ACK timing)
        """
    )
    
    parser.add_argument("--sender-dir", required=True,
                        help="Directory containing sender iperf3 JSON logs")
    parser.add_argument("--receiver-dir", required=True,
                        help="Directory containing receiver iperf3 JSON logs")
    parser.add_argument("--output-dir", required=True,
                        help="Directory to write merged JSON logs")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress per-file progress output")
    
    args = parser.parse_args()
    
    # Validate directories
    if not os.path.isdir(args.sender_dir):
        print(f"Error: Sender directory does not exist: {args.sender_dir}")
        sys.exit(1)
    
    if not os.path.isdir(args.receiver_dir):
        print(f"Error: Receiver directory does not exist: {args.receiver_dir}")
        sys.exit(1)
    
    print(f"Merging iperf3 logs:")
    print(f"  Sender:   {args.sender_dir}")
    print(f"  Receiver: {args.receiver_dir}")
    print(f"  Output:   {args.output_dir}")
    print()
    
    stats = process_directory(
        args.sender_dir, 
        args.receiver_dir, 
        args.output_dir,
        verbose=not args.quiet
    )
    
    print()
    print("=" * 50)
    print("MERGE SUMMARY")
    print("=" * 50)
    print(f"  ✓ Fully merged:    {stats['merged']}")
    print(f"  ⚠ Sender only:     {stats['sender_only']}")
    print(f"  ⚠ Receiver only:   {stats['receiver_only']}")
    print(f"  ✗ Failed:          {stats['failed']}")
    print(f"  Total files:       {sum(stats.values())}")
    print()
    
    if stats['merged'] > 0:
        print(f"Merged logs saved to: {args.output_dir}")
        print()
        print("Next steps:")
        print(f"  # Visualize accurate goodput")
        print(f"  python3 visualize_iperf3.py --iperf-dir {args.output_dir} --metric goodput --output goodput.png")
        print()
        print(f"  # Visualize RTT")
        print(f"  python3 visualize_iperf3.py --iperf-dir {args.output_dir} --metric rtt --output rtt.png")
    else:
        print("Warning: No files were successfully merged!")
        print("Check that sender and receiver directories contain matching flow logs.")


if __name__ == "__main__":
    main()