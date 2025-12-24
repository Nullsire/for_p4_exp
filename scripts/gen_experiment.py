#!/usr/bin/env python3
import argparse
import os
import stat

# Table 2: Configurations
CONFIGS = {
    "I":    {"bw": 120,  "rtt": 10, "mtu": 1500},
    "II":   {"bw": 120,  "rtt": 50, "mtu": 1500},
    "III":  {"bw": 1000, "rtt": 10, "mtu": 1500},
    "IV":   {"bw": 1000, "rtt": 50, "mtu": 1500},
    "V":    {"bw": 120,  "rtt": 10, "mtu": 800},
    "VI":   {"bw": 120,  "rtt": 50, "mtu": 800},
    "VII":  {"bw": 1000, "rtt": 10, "mtu": 800},
    "VIII": {"bw": 1000, "rtt": 50, "mtu": 800},
    "IX":   {"bw": 120,  "rtt": 10, "mtu": 400},
    "X":    {"bw": 120,  "rtt": 50, "mtu": 400},
    "XI":   {"bw": 1000, "rtt": 10, "mtu": 400},
    "XII":  {"bw": 1000, "rtt": 50, "mtu": 400},
}

# Table 3: Load Phases
# Each phase lasts 120 seconds.
# Flows are accumulative or total concurrent? 
# "In each phase, new flows enter the system... The number of Cubic and Prague flows are shown in Table 3."
# Table 3 shows: Phase 1: 1, Phase 2: 2, Phase 3: 10, Phase 4: 25.
# This usually means TOTAL concurrent flows in that phase.
# So we need to start (2-1)=1 new flow at 120s, (10-2)=8 new flows at 240s, etc.
PHASES = [
    {"duration": 120, "cubic": 1,  "prague": 1},
    {"duration": 120, "cubic": 2,  "prague": 2},
    {"duration": 120, "cubic": 10, "prague": 10},
    {"duration": 120, "cubic": 25, "prague": 25},
]

# Base port for iperf3 servers (each flow uses a different port)
BASE_PORT = 5201
# Max flows needed: 25 cubic + 25 prague = 50
MAX_FLOWS = 50

# Sampling intervals
IPERF3_INTERVAL = 0.1  # 100ms - minimum supported by iperf3
SS_INTERVAL_MS = 2     # 2ms - fine-grained sampling using ss command

def generate_sender_script(args, config, filename="run_sender.sh"):
    lines = []
    lines.append("#!/bin/bash")
    lines.append(f"# Configuration {args.config}: BW={config['bw']}Mbps, RTT={config['rtt']}ms, MTU={config['mtu']}B")
    lines.append("")
    lines.append(f"INTERFACE={args.sender_if}")
    lines.append(f"DST_IP={args.receiver_ip}")
    
    # Log directory setup
    if args.log_dir:
        lines.append(f"LOG_DIR=\"{args.log_dir}_{args.config}\"")
        lines.append("mkdir -p \"$LOG_DIR\"")
        lines.append("echo \"Logs will be saved to $LOG_DIR\"")
    else:
        lines.append("LOG_DIR=\"\"")
    lines.append("")
    
    lines.append("# 1. Set MTU")
    lines.append(f"echo 'Setting MTU to {config['mtu']} on $INTERFACE...'")
    lines.append(f"sudo ifconfig $INTERFACE mtu {config['mtu']}")
    lines.append("")
    
    lines.append("# 2. Start Traffic Phases")
    lines.append("echo 'Starting traffic generation...'")
    
    # Initialize global flow counters
    lines.append("# Global flow ID counters")
    lines.append("CUBIC_FLOW_ID=0")
    lines.append("PRAGUE_FLOW_ID=0")
    lines.append("")
    
    total_duration = sum(p['duration'] for p in PHASES)
    
    # Track running counts to calculate delta
    running_cubic = 0
    running_prague = 0
    
    current_time = 0
    
    for i, phase in enumerate(PHASES):
        delta_cubic = phase['cubic'] - running_cubic
        delta_prague = phase['prague'] - running_prague
        
        remaining_time = total_duration - current_time
        
        if i > 0:
            lines.append(f"echo 'Sleeping 120s before Phase {i+1}...'")
            lines.append("sleep 120")
        
        lines.append(f"echo 'Phase {i+1}: Starting {delta_cubic} new Cubic flows and {delta_prague} new Prague flows...'")
            
        if delta_cubic > 0:
            lines.append(f"# Add {delta_cubic} Cubic flows for {remaining_time}s")
            lines.append(f"for j in $(seq 1 {delta_cubic}); do")
            lines.append("  CUBIC_FLOW_ID=$((CUBIC_FLOW_ID + 1))")
            # Each cubic flow uses port BASE_PORT + CUBIC_FLOW_ID - 1
            lines.append(f"  PORT=$(({BASE_PORT} + $CUBIC_FLOW_ID - 1))")
            if args.log_dir:
                # Use JSON output with unique log file per flow
                # -i 0.1 sets 100ms sampling interval (minimum supported by iperf3)
                lines.append("  LOGFILE=\"$LOG_DIR/cubic_flow_${CUBIC_FLOW_ID}.json\"")
                lines.append(f"  iperf3 -c $DST_IP -p $PORT -t {remaining_time} -i {IPERF3_INTERVAL} -C cubic -J --logfile \"$LOGFILE\" &")
                lines.append("  echo \"  Started Cubic flow $CUBIC_FLOW_ID on port $PORT -> $LOGFILE\"")
            else:
                lines.append(f"  iperf3 -c $DST_IP -p $PORT -t {remaining_time} -i {IPERF3_INTERVAL} -C cubic --logfile /dev/null &")
                lines.append("  echo \"  Started Cubic flow $CUBIC_FLOW_ID on port $PORT\"")
            lines.append("done")
            
        if delta_prague > 0:
            lines.append(f"# Add {delta_prague} Prague flows for {remaining_time}s")
            lines.append(f"for j in $(seq 1 {delta_prague}); do")
            lines.append("  PRAGUE_FLOW_ID=$((PRAGUE_FLOW_ID + 1))")
            # Each prague flow uses port BASE_PORT + 25 + PRAGUE_FLOW_ID - 1 (offset by max cubic flows)
            lines.append(f"  PORT=$(({BASE_PORT} + 25 + $PRAGUE_FLOW_ID - 1))")
            if args.log_dir:
                # Use JSON output with unique log file per flow
                # -i 0.1 sets 100ms sampling interval (minimum supported by iperf3)
                lines.append("  LOGFILE=\"$LOG_DIR/prague_flow_${PRAGUE_FLOW_ID}.json\"")
                # Note: 'prague' might need to be 'bbr' or something if prague isn't installed.
                lines.append(f"  iperf3 -c $DST_IP -p $PORT -t {remaining_time} -i {IPERF3_INTERVAL} -C prague -J --logfile \"$LOGFILE\" &")
                lines.append("  echo \"  Started Prague flow $PRAGUE_FLOW_ID on port $PORT -> $LOGFILE\"")
            else:
                # Note: 'prague' might need to be 'bbr' or something if prague isn't installed.
                lines.append(f"  iperf3 -c $DST_IP -p $PORT -t {remaining_time} -i {IPERF3_INTERVAL} -C prague --logfile /dev/null &")
                lines.append("  echo \"  Started Prague flow $PRAGUE_FLOW_ID on port $PORT\"")
            lines.append("done")
            
        running_cubic = phase['cubic']
        running_prague = phase['prague']
        current_time += phase['duration']

    lines.append("")
    lines.append("echo 'All flows started. Waiting for experiment to finish...'")
    lines.append("wait")
    lines.append("echo 'Experiment Done.'")
    if args.log_dir:
        lines.append("echo \"Logs saved to: $LOG_DIR\"")
        lines.append("echo \"Total Cubic flows: $CUBIC_FLOW_ID, Total Prague flows: $PRAGUE_FLOW_ID\"")
    
    with open(filename, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.chmod(filename, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
    print(f"Generated {filename}")


def generate_ss_sampler_script(args, config, filename="run_ss_sampler.sh"):
    """Generate a fine-grained TCP stats sampler using 'ss' command.
    
    This script samples TCP connection statistics at millisecond intervals
    (default 2ms), providing much finer granularity than iperf3's 100ms minimum.
    
    Collected metrics include: cwnd, rtt, retrans, bytes_sent, bytes_acked, etc.
    """
    total_duration = sum(p['duration'] for p in PHASES)
    ss_interval = getattr(args, 'ss_interval_ms', SS_INTERVAL_MS)
    
    lines = []
    lines.append("#!/bin/bash")
    lines.append(f"# Fine-grained TCP stats sampler - Configuration {args.config}")
    lines.append(f"# Sampling interval: {ss_interval}ms")
    lines.append(f"# Total duration: {total_duration}s")
    lines.append("")
    lines.append("# Configuration")
    lines.append(f"INTERVAL_MS={ss_interval}")
    lines.append(f"DURATION={total_duration}")
    lines.append(f"DST_IP={args.receiver_ip}")
    lines.append("")
    
    # Log directory setup
    if args.log_dir:
        lines.append(f"LOG_DIR=\"{args.log_dir}_{args.config}\"")
        lines.append("mkdir -p \"$LOG_DIR\"")
        lines.append("SS_LOG=\"$LOG_DIR/ss_stats.csv\"")
    else:
        lines.append("SS_LOG=\"./ss_stats_${DST_IP}.csv\"")
    lines.append("")
    
    lines.append("# Convert ms to seconds for sleep (using bc for floating point)")
    lines.append("INTERVAL_SEC=$(echo \"scale=6; $INTERVAL_MS / 1000\" | bc)")
    lines.append("")
    
    lines.append("echo \"Starting fine-grained TCP stats sampling...\"")
    lines.append("echo \"  Interval: ${INTERVAL_MS}ms\"")
    lines.append("echo \"  Duration: ${DURATION}s\"")
    lines.append("echo \"  Target IP: $DST_IP\"")
    lines.append("echo \"  Output: $SS_LOG\"")
    lines.append("")
    
    # CSV header
    lines.append("# Write CSV header")
    lines.append("echo 'timestamp_ns,local_addr,local_port,remote_addr,remote_port,state,cwnd,ssthresh,rtt_us,rttvar_us,rto_ms,mss,bytes_sent,bytes_acked,bytes_received,segs_out,segs_in,retrans,lost,delivery_rate,pacing_rate' > \"$SS_LOG\"")
    lines.append("")
    
    lines.append("# Calculate end time")
    lines.append("START_TIME=$(date +%s%N)")
    lines.append("END_TIME=$((START_TIME + DURATION * 1000000000))")
    lines.append("")
    
    lines.append("echo \"Sampling started at $(date)\"")
    lines.append("echo \"Press Ctrl+C to stop early\"")
    lines.append("")
    
    lines.append("# Trap for cleanup")
    lines.append("cleanup() {")
    lines.append("  echo \"\"")
    lines.append("  echo \"Sampling stopped. $(wc -l < \"$SS_LOG\") samples collected.\"")
    lines.append("  echo \"Output saved to: $SS_LOG\"")
    lines.append("  exit 0")
    lines.append("}")
    lines.append("trap cleanup SIGINT SIGTERM")
    lines.append("")
    
    lines.append("# Main sampling loop")
    lines.append("SAMPLE_COUNT=0")
    lines.append("while [ $(date +%s%N) -lt $END_TIME ]; do")
    lines.append("  TIMESTAMP=$(date +%s%N)")
    lines.append("  ")
    lines.append("  # Get TCP stats for connections to/from target IP")
    lines.append("  # ss -tin provides detailed TCP info including cwnd, rtt, etc.")
    lines.append("  ss -tin dst $DST_IP or src $DST_IP 2>/dev/null | awk -v ts=\"$TIMESTAMP\" '")
    lines.append("    /^tcp/ {")
    lines.append("      state=$1")
    lines.append("      # Parse local and remote addresses")
    lines.append("      split($4, local, \":\")")
    lines.append("      split($5, remote, \":\")")
    lines.append("      local_addr=local[1]; local_port=local[2]")
    lines.append("      remote_addr=remote[1]; remote_port=remote[2]")
    lines.append("    }")
    lines.append("    /cubic|prague|bbr|reno/ {")
    lines.append("      # Initialize variables")
    lines.append("      cwnd=\"\"; ssthresh=\"\"; rtt=\"\"; rttvar=\"\"; rto=\"\"; mss=\"\"")
    lines.append("      bytes_sent=\"\"; bytes_acked=\"\"; bytes_received=\"\"")
    lines.append("      segs_out=\"\"; segs_in=\"\"; retrans=\"\"; lost=\"\"")
    lines.append("      delivery_rate=\"\"; pacing_rate=\"\"")
    lines.append("      ")
    lines.append("      # Parse key-value pairs")
    lines.append("      for(i=1; i<=NF; i++) {")
    lines.append("        if($i ~ /^cwnd:/) { split($i, a, \":\"); cwnd=a[2] }")
    lines.append("        if($i ~ /^ssthresh:/) { split($i, a, \":\"); ssthresh=a[2] }")
    lines.append("        if($i ~ /^rtt:/) { split($i, a, \":\"); split(a[2], b, \"/\"); rtt=b[1]; rttvar=b[2] }")
    lines.append("        if($i ~ /^rto:/) { split($i, a, \":\"); rto=a[2] }")
    lines.append("        if($i ~ /^mss:/) { split($i, a, \":\"); mss=a[2] }")
    lines.append("        if($i ~ /^bytes_sent:/) { split($i, a, \":\"); bytes_sent=a[2] }")
    lines.append("        if($i ~ /^bytes_acked:/) { split($i, a, \":\"); bytes_acked=a[2] }")
    lines.append("        if($i ~ /^bytes_received:/) { split($i, a, \":\"); bytes_received=a[2] }")
    lines.append("        if($i ~ /^segs_out:/) { split($i, a, \":\"); segs_out=a[2] }")
    lines.append("        if($i ~ /^segs_in:/) { split($i, a, \":\"); segs_in=a[2] }")
    lines.append("        if($i ~ /^retrans:/) { split($i, a, \":\"); split(a[2], b, \"/\"); retrans=b[1] }")
    lines.append("        if($i ~ /^lost:/) { split($i, a, \":\"); lost=a[2] }")
    lines.append("        if($i ~ /^delivery_rate/) { split($i, a, \":\"); delivery_rate=a[2] }")
    lines.append("        if($i ~ /^pacing_rate/) { split($i, a, \":\"); pacing_rate=a[2] }")
    lines.append("      }")
    lines.append("      ")
    lines.append("      # Output CSV line")
    lines.append("      printf \"%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\\n\", \\")
    lines.append("        ts, local_addr, local_port, remote_addr, remote_port, state, \\")
    lines.append("        cwnd, ssthresh, rtt, rttvar, rto, mss, \\")
    lines.append("        bytes_sent, bytes_acked, bytes_received, segs_out, segs_in, \\")
    lines.append("        retrans, lost, delivery_rate, pacing_rate")
    lines.append("    }")
    lines.append("  ' >> \"$SS_LOG\"")
    lines.append("  ")
    lines.append("  SAMPLE_COUNT=$((SAMPLE_COUNT + 1))")
    lines.append("  ")
    lines.append("  # Progress indicator every 1000 samples")
    lines.append("  if [ $((SAMPLE_COUNT % 1000)) -eq 0 ]; then")
    lines.append("    ELAPSED=$(($(date +%s) - START_TIME / 1000000000))")
    lines.append("    echo -ne \"\\r  Samples: $SAMPLE_COUNT, Elapsed: ${ELAPSED}s\"")
    lines.append("  fi")
    lines.append("  ")
    lines.append("  # Sleep for interval (using python for precise sub-ms sleep)")
    lines.append("  python3 -c \"import time; time.sleep($INTERVAL_SEC)\" 2>/dev/null || sleep $INTERVAL_SEC")
    lines.append("done")
    lines.append("")
    lines.append("echo \"\"")
    lines.append("echo \"Sampling complete. $SAMPLE_COUNT samples collected.\"")
    lines.append("echo \"Output saved to: $SS_LOG\"")
    lines.append("")
    lines.append("# Show sample statistics")
    lines.append("echo \"\"")
    lines.append("echo \"Sample statistics:\"")
    lines.append("echo \"  Total lines: $(wc -l < \"$SS_LOG\")\"")
    lines.append("echo \"  File size: $(du -h \"$SS_LOG\" | cut -f1)\"")
    
    with open(filename, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.chmod(filename, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
    print(f"Generated {filename}")


def generate_receiver_script(args, config, filename="run_receiver.sh"):
    lines = []
    lines.append("#!/bin/bash")
    lines.append(f"# Configuration {args.config}: BW={config['bw']}Mbps, RTT={config['rtt']}ms, MTU={config['mtu']}B")
    lines.append("")
    lines.append(f"INTERFACE={args.receiver_if}")
    lines.append(f"BIND_IP={args.receiver_bind_ip}")
    lines.append("")
    
    # Log directory setup for receiver
    if args.log_dir:
        lines.append(f"LOG_DIR=\"{args.log_dir}_{args.config}_receiver\"")
        lines.append("mkdir -p \"$LOG_DIR\"")
        lines.append("echo \"Receiver logs will be saved to $LOG_DIR\"")
    else:
        lines.append("LOG_DIR=\"\"")
    lines.append("")
    
    lines.append("# 1. Set MTU")
    lines.append(f"echo 'Setting MTU to {config['mtu']} on $INTERFACE...'")
    lines.append(f"sudo ifconfig $INTERFACE mtu {config['mtu']}")
    lines.append("")
    
    lines.append("# 2. Set RTT (tc netem)")
    # The paper says "The base RTT is emulated in the Receiver by the tc netem tool, delaying the ACKs".
    # Usually this means adding delay on the egress interface of the Receiver (sending ACKs back).
    lines.append(f"echo 'Setting RTT delay {config['rtt']}ms on $INTERFACE...'")
    lines.append("# Reset existing tc qdiscs")
    lines.append(f"sudo tc qdisc del dev $INTERFACE root 2>/dev/null || true")
    lines.append("# Add netem delay")
    lines.append(f"sudo tc qdisc add dev $INTERFACE root netem delay {config['rtt']}ms")
    lines.append("")
    
    lines.append("# 3. Start multiple iperf3 Servers (one per flow)")
    lines.append("# iperf3 can only handle one client per server instance,")
    lines.append("# so we need to start multiple servers on different ports.")
    lines.append("# Each server logs to a JSON file for accurate goodput measurement.")
    lines.append("# NOTE: Receiver logs provide accurate goodput (bits_per_second)")
    lines.append("#       Sender logs provide accurate RTT, cwnd, retransmits")
    lines.append(f"echo 'Starting {MAX_FLOWS} iperf3 server instances on ports {BASE_PORT}-{BASE_PORT + MAX_FLOWS - 1}...'")
    lines.append("echo \"Binding to IP: $BIND_IP\"")
    lines.append("")
    lines.append("# Array to store server PIDs")
    lines.append("declare -a IPERF_PIDS")
    lines.append("")
    
    # Start iperf3 servers with JSON logging
    lines.append(f"for port in $(seq {BASE_PORT} {BASE_PORT + MAX_FLOWS - 1}); do")
    if args.log_dir:
        # Determine flow type based on port range
        # Ports 5201-5225 are for Cubic flows (flow IDs 1-25)
        # Ports 5226-5250 are for Prague flows (flow IDs 1-25)
        lines.append("  # Determine flow type and ID based on port")
        lines.append(f"  if [ $port -lt {BASE_PORT + 25} ]; then")
        lines.append(f"    FLOW_ID=$((port - {BASE_PORT} + 1))")
        lines.append("    LOGFILE=\"$LOG_DIR/cubic_flow_${FLOW_ID}.json\"")
        lines.append("  else")
        lines.append(f"    FLOW_ID=$((port - {BASE_PORT + 25} + 1))")
        lines.append("    LOGFILE=\"$LOG_DIR/prague_flow_${FLOW_ID}.json\"")
        lines.append("  fi")
        lines.append(f"  iperf3 -s -B $BIND_IP -p $port -J --logfile \"$LOGFILE\" &")
        lines.append("  IPERF_PIDS+=($!)")
        lines.append("  echo \"  Started iperf3 server on port $port -> $LOGFILE\"")
    else:
        lines.append("  iperf3 -s -B $BIND_IP -p $port -D")  # -D for daemon mode (no logging)
        lines.append("  IPERF_PIDS+=($!)")
    lines.append("done")
    lines.append("")
    lines.append(f"echo '{MAX_FLOWS} iperf3 servers started (ports {BASE_PORT}-{BASE_PORT + MAX_FLOWS - 1}) on $BIND_IP.'")
    if args.log_dir:
        lines.append("echo 'Each server will log to JSON file for accurate goodput measurement.'")
    lines.append("echo 'Press Ctrl+C to stop all servers.'")
    lines.append("")
    lines.append("# Function to cleanup servers on exit")
    lines.append("cleanup() {")
    lines.append("  echo ''")
    lines.append("  echo 'Stopping all iperf3 servers...'")
    lines.append("  ")
    lines.append("  # Send SIGTERM first for graceful shutdown")
    lines.append("  for pid in \"${IPERF_PIDS[@]}\"; do")
    lines.append("    kill -TERM $pid 2>/dev/null || true")
    lines.append("  done")
    lines.append("  ")
    lines.append("  # Wait a moment for graceful shutdown")
    lines.append("  sleep 1")
    lines.append("  ")
    lines.append("  # Force kill any remaining processes")
    lines.append("  for pid in \"${IPERF_PIDS[@]}\"; do")
    lines.append("    kill -9 $pid 2>/dev/null || true")
    lines.append("  done")
    lines.append("  ")
    lines.append("  # Also cleanup by port pattern")
    lines.append(f"  pkill -9 -f \"iperf3 -s.*-p 52\" 2>/dev/null || true")
    lines.append("  ")
    if args.log_dir:
        lines.append("  # Clean up trailing invalid JSON fragments from log files")
        lines.append("  # When iperf3 server is interrupted, it appends an error JSON fragment to the log")
        lines.append("  # We need to find and remove these trailing fragments")
        lines.append("  echo 'Cleaning up log files...'")
        lines.append("  for logfile in \"$LOG_DIR\"/*.json; do")
        lines.append("    if [ -f \"$logfile\" ]; then")
        lines.append("      # Check if file has trailing interrupt error")
        lines.append("      if grep -q '\"error\".*interrupt.*server has terminated' \"$logfile\" 2>/dev/null; then")
        lines.append("        # Use Python to clean up the trailing invalid JSON fragment")
        lines.append("        python3 -c '")
        lines.append("import sys")
        lines.append("filepath = sys.argv[1]")
        lines.append("with open(filepath, \"r\") as f:")
        lines.append("    content = f.read()")
        lines.append("# Find the start of the trailing invalid fragment")
        lines.append("# It looks like: {\"start\":{\"connected\":[],... with empty connected array")
        lines.append("# The valid JSON ends with } before this fragment starts")
        lines.append("marker = chr(123) + chr(10) + chr(9) + chr(34) + \"start\" + chr(34) + chr(58) + chr(9) + chr(123) + chr(10) + chr(9) + chr(9) + chr(34) + \"connected\" + chr(34) + chr(58) + chr(9) + chr(91) + chr(93)")
        lines.append("pos = content.rfind(marker)")
        lines.append("if pos > 0:")
        lines.append("    cleaned = content[:pos].rstrip()")
        lines.append("    with open(filepath, \"w\") as f:")
        lines.append("        f.write(cleaned)")
        lines.append("    print(f\"  Cleaned: {filepath}\")")
        lines.append("' \"$logfile\" 2>/dev/null || echo \"  Warning: Could not clean $logfile\"")
        lines.append("      fi")
        lines.append("    fi")
        lines.append("  done")
        lines.append("  ")
    lines.append("  echo 'All servers stopped.'")
    if args.log_dir:
        lines.append("  echo \"Receiver logs saved to: $LOG_DIR\"")
        lines.append("  # Show summary of valid logs")
        lines.append("  VALID_LOGS=$(ls -1 \"$LOG_DIR\"/*.json 2>/dev/null | wc -l)")
        lines.append("  echo \"Valid log files: $VALID_LOGS\"")
    lines.append("  exit 0")
    lines.append("}")
    lines.append("")
    lines.append("trap cleanup SIGINT SIGTERM EXIT")
    lines.append("")
    lines.append("# Wait and show connection status periodically")
    lines.append("echo 'Receiver is ready. Waiting for traffic...'")
    lines.append("echo 'You can monitor traffic with: ss -tn | grep -E \"520[0-9]\" or netstat -tn | grep -E \"520[0-9]\"'")
    lines.append("echo ''")
    lines.append("")
    lines.append("# Show connection count every 10 seconds")
    lines.append("while true; do")
    lines.append("  CONN_COUNT=$(ss -tn 2>/dev/null | grep -cE ':520[0-9]' || echo 0)")
    lines.append("  echo \"[$(date '+%H:%M:%S')] Active iperf3 connections: $CONN_COUNT\"")
    lines.append("  sleep 10")
    lines.append("done")
    
    with open(filename, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.chmod(filename, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
    print(f"Generated {filename}")

def main():
    parser = argparse.ArgumentParser(description="Generate iRED experiment scripts (Sender/Receiver)")
    parser.add_argument("--config", required=True, choices=CONFIGS.keys(), help="Configuration ID (I-XII) from Table 2")
    parser.add_argument("--sender-if", default="enp2s0", help="Sender interface name")
    parser.add_argument("--receiver-if", default="enp2s0", help="Receiver interface name")
    parser.add_argument("--receiver-ip", default="192.168.6.2", help="Receiver IP address (for sender to connect to)")
    parser.add_argument("--receiver-bind-ip", default="0.0.0.0", help="IP address for iperf3 server to bind to (default: 0.0.0.0 for all interfaces)")
    parser.add_argument("--out-dir", default=".", help="Output directory for generated scripts")
    parser.add_argument("--log-dir", default="./exp_logs", help="Directory for iperf3 JSON log files (default: ./exp_logs). Use --no-log to disable logging.")
    parser.add_argument("--no-log", action="store_true", help="Disable iperf3 logging (not recommended)")
    parser.add_argument("--ss-interval-ms", type=int, default=SS_INTERVAL_MS, 
                        help=f"Fine-grained sampling interval in milliseconds for ss sampler (default: {SS_INTERVAL_MS}ms)")
    
    args = parser.parse_args()
    
    # Handle --no-log option: disable logging by setting log_dir to None
    if args.no_log:
        args.log_dir = None
        print("⚠️  Warning: Logging is disabled (--no-log). You may lose experiment data!")
    
    if args.config not in CONFIGS:
        print(f"Error: Unknown configuration {args.config}")
        return

    config = CONFIGS[args.config]
    
    print(f"Generating scripts for Config {args.config}: {config}")
    
    sender_file = os.path.join(args.out_dir, f"run_sender_conf{args.config}.sh")
    receiver_file = os.path.join(args.out_dir, f"run_receiver_conf{args.config}.sh")
    
    ss_sampler_file = os.path.join(args.out_dir, f"run_ss_sampler_conf{args.config}.sh")
    
    generate_sender_script(args, config, sender_file)
    generate_receiver_script(args, config, receiver_file)
    generate_ss_sampler_script(args, config, ss_sampler_file)
    
    print("\n" + "="*60)
    print("INSTRUCTIONS")
    print("="*60)
    print(f"\n1. Copy {receiver_file} to Receiver host and run it.")
    print(f"2. Copy {sender_file} to Sender host and run it.")
    print(f"3. (Optional) Run {ss_sampler_file} on Sender for fine-grained sampling.")
    print("4. Ensure the switch is configured with the correct bandwidth limit (use tm_shape_queue.sh).")
    print(f"   For Config {args.config}, bandwidth is {config['bw']} Mbps.")
    
    print("\n" + "-"*60)
    print("SAMPLING DETAILS")
    print("-"*60)
    print(f"\n📊 iperf3 sampling: {IPERF3_INTERVAL}s (100ms) intervals")
    print(f"   - SENDER logs: RTT, cwnd, retransmits (accurate)")
    print(f"   - RECEIVER logs: goodput/throughput (accurate)")
    print(f"   - Output: JSON files in log directory")
    print(f"\n📊 ss sampler: {args.ss_interval_ms}ms intervals (fine-grained)")
    print(f"   - Provides cwnd, rtt, ssthresh, bytes_sent/acked, etc.")
    print(f"   - Output: CSV file with nanosecond timestamps")
    print(f"   - Run CONCURRENTLY with sender script for best results")
    
    if args.log_dir:
        sender_log_dir = f"{args.log_dir}_{args.config}"
        receiver_log_dir = f"{args.log_dir}_{args.config}_receiver"
        print(f"\n" + "-"*60)
        print("LOG FILES")
        print("-"*60)
        print(f"\n   Sender log directory: {sender_log_dir}/")
        print(f"   ├── cubic_flow_{{1..25}}.json  (RTT, cwnd, retransmits)")
        print(f"   ├── prague_flow_{{1..25}}.json (RTT, cwnd, retransmits)")
        print(f"   └── ss_stats.csv              (fine-grained stats)")
        print(f"\n   Receiver log directory: {receiver_log_dir}/")
        print(f"   ├── cubic_flow_{{1..25}}.json  (accurate goodput)")
        print(f"   └── prague_flow_{{1..25}}.json (accurate goodput)")
        print(f"\n   ⚠️  IMPORTANT: Use merge_iperf3_logs.py to combine sender/receiver logs")
        print(f"      python3 merge_iperf3_logs.py --sender-dir {sender_log_dir} --receiver-dir {receiver_log_dir} --output-dir merged_logs/")
    else:
        print("\n⚠️  Logging is disabled. Use --log-dir to enable.")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()