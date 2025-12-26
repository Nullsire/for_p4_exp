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

def generate_sender_script(args, config, filename="run_sender.sh"):
    lines = []
    lines.append("#!/bin/bash")
    lines.append(f"# Configuration {args.config}: BW={config['bw']}Mbps, RTT={config['rtt']}ms, MTU={config['mtu']}B")
    lines.append("")
    lines.append(f"INTERFACE={args.sender_if}")
    lines.append(f"DST_IP={args.receiver_ip}")
    lines.append("")
    
    lines.append("# 1. Set MTU")
    lines.append(f"echo 'Setting MTU to {config['mtu']} on $INTERFACE...'")
    lines.append(f"sudo ip link set dev $INTERFACE mtu {config['mtu']}")
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
            lines.append(f"  iperf3 -c $DST_IP -p $PORT -t {remaining_time} -i {IPERF3_INTERVAL} -C cubic --logfile /dev/null &")
            lines.append('  echo "  Started Cubic flow $CUBIC_FLOW_ID on port $PORT"')
            lines.append("done")
            
        if delta_prague > 0:
            lines.append(f"# Add {delta_prague} Prague flows for {remaining_time}s")
            lines.append(f"for j in $(seq 1 {delta_prague}); do")
            lines.append("  PRAGUE_FLOW_ID=$((PRAGUE_FLOW_ID + 1))")
            # Each prague flow uses port BASE_PORT + 25 + PRAGUE_FLOW_ID - 1 (offset by max cubic flows)
            lines.append(f"  PORT=$(({BASE_PORT} + 25 + $PRAGUE_FLOW_ID - 1))")
            # Note: 'prague' might need to be 'bbr' or something if prague isn't installed.
            lines.append(f"  iperf3 -c $DST_IP -p $PORT -t {remaining_time} -i {IPERF3_INTERVAL} -C prague --logfile /dev/null &")
            lines.append('  echo "  Started Prague flow $PRAGUE_FLOW_ID on port $PORT"')
            lines.append("done")
            
        running_cubic = phase['cubic']
        running_prague = phase['prague']
        current_time += phase['duration']

    lines.append("")
    lines.append("echo 'All flows started. Waiting for experiment to finish...'")
    lines.append("wait")
    lines.append("echo 'Experiment Done.'")
    
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
    
    lines.append("# 1. Set MTU")
    lines.append(f"echo 'Setting MTU to {config['mtu']} on $INTERFACE...'")
    lines.append(f"sudo ip link set dev $INTERFACE mtu {config['mtu']}")
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
    lines.append(f"echo 'Starting {MAX_FLOWS} iperf3 server instances on ports {BASE_PORT}-{BASE_PORT + MAX_FLOWS - 1}...'")
    lines.append('echo "Binding to IP: $BIND_IP"')
    lines.append("")
    lines.append("# Array to store server PIDs")
    lines.append("declare -a IPERF_PIDS")
    lines.append("")
    
    # Start iperf3 servers
    lines.append(f"for port in $(seq {BASE_PORT} {BASE_PORT + MAX_FLOWS - 1}); do")
    lines.append("  iperf3 -s -B $BIND_IP -p $port -D")  # -D for daemon mode (no logging)
    lines.append("  IPERF_PIDS+=($!)")
    lines.append("done")
    lines.append("")
    lines.append(f"echo '{MAX_FLOWS} iperf3 servers started (ports {BASE_PORT}-{BASE_PORT + MAX_FLOWS - 1}) on $BIND_IP.'")
    lines.append("echo 'Press Ctrl+C to stop all servers.'")
    lines.append("")
    lines.append("# Function to cleanup servers on exit")
    lines.append("cleanup() {")
    lines.append("  echo ''")
    lines.append("  echo 'Stopping all iperf3 servers...'")
    lines.append("  ")
    lines.append("  # Send SIGTERM first for graceful shutdown")
    lines.append('  for pid in "${IPERF_PIDS[@]}"; do')
    lines.append("    kill -TERM $pid 2>/dev/null || true")
    lines.append("  done")
    lines.append("  ")
    lines.append("  # Wait a moment for graceful shutdown")
    lines.append("  sleep 1")
    lines.append("  ")
    lines.append("  # Force kill any remaining processes")
    lines.append('  for pid in "${IPERF_PIDS[@]}"; do')
    lines.append("    kill -9 $pid 2>/dev/null || true")
    lines.append("  done")
    lines.append("  ")
    lines.append("  # Also cleanup by port pattern")
    lines.append(f'  pkill -9 -f "iperf3 -s.*-p 52" 2>/dev/null || true')
    lines.append("  ")
    lines.append("  echo 'All servers stopped.'")
    lines.append("  exit 0")
    lines.append("}")
    lines.append("trap cleanup SIGINT SIGTERM EXIT")
    lines.append("")
    lines.append("# Wait and show connection status periodically")
    lines.append("echo 'Receiver is ready. Waiting for traffic...'")
    lines.append("echo \"You can monitor traffic with: ss -tn state established | grep -E ':52(0[1-9]|[1-4][0-9]|50)\\\\b'\"")
    lines.append("echo ''")
    lines.append("")
    lines.append("# Show connection count every 10 seconds")
    lines.append("while true; do")
    lines.append("  # Count ESTABLISHED connections on ports 5201-5250")
    lines.append("  # ss -tn state established shows only established TCP connections (not listening)")
    lines.append("  CONN_COUNT=$(ss -tn state established 2>/dev/null | grep -cE ':52(0[1-9]|[1-4][0-9]|50)\\b' || echo 0)")
    lines.append('  echo "[$(date ' + "'+%H:%M:%S')] Active iperf3 connections: $CONN_COUNT\"")
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
    
    args = parser.parse_args()
    
    if args.config not in CONFIGS:
        print(f"Error: Unknown configuration {args.config}")
        return

    config = CONFIGS[args.config]
    
    print(f"Generating scripts for Config {args.config}: {config}")
    
    sender_file = os.path.join(args.out_dir, f"run_sender_conf{args.config}.sh")
    receiver_file = os.path.join(args.out_dir, f"run_receiver_conf{args.config}.sh")
    
    generate_sender_script(args, config, sender_file)
    generate_receiver_script(args, config, receiver_file)
    
    print("" + "="*60)
    print("INSTRUCTIONS")
    print("="*60)
    print(f"1. Copy {receiver_file} to Receiver host and run it.")
    print(f"2. Copy {sender_file} to Sender host and run it.")
    print("3. Ensure the switch is configured with the correct bandwidth limit (use tm_shape_queue.sh).")
    print(f"   For Config {args.config}, bandwidth is {config['bw']} Mbps.")
    
    print("" + "="*60)

if __name__ == "__main__":
    main()
