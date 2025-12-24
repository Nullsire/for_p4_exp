#!/bin/bash
# Configuration I: BW=120Mbps, RTT=10ms, MTU=1500B

INTERFACE=enp2s0
BIND_IP=0.0.0.0

LOG_DIR="./exp_logs_I_receiver"
mkdir -p "$LOG_DIR"
echo "Receiver logs will be saved to $LOG_DIR"

# 1. Set MTU
echo 'Setting MTU to 1500 on $INTERFACE...'
sudo ifconfig $INTERFACE mtu 1500

# 2. Set RTT (tc netem)
echo 'Setting RTT delay 10ms on $INTERFACE...'
# Reset existing tc qdiscs
sudo tc qdisc del dev $INTERFACE root 2>/dev/null || true
# Add netem delay
sudo tc qdisc add dev $INTERFACE root netem delay 10ms

# 3. Start multiple iperf3 Servers (one per flow)
# iperf3 can only handle one client per server instance,
# so we need to start multiple servers on different ports.
# Each server logs to a JSON file for accurate goodput measurement.
# NOTE: Receiver logs provide accurate goodput (bits_per_second)
#       Sender logs provide accurate RTT, cwnd, retransmits
echo 'Starting 50 iperf3 server instances on ports 5201-5250...'
echo "Binding to IP: $BIND_IP"

# Array to store server PIDs
declare -a IPERF_PIDS

for port in $(seq 5201 5250); do
  # Determine flow type and ID based on port
  if [ $port -lt 5226 ]; then
    FLOW_ID=$((port - 5201 + 1))
    LOGFILE="$LOG_DIR/cubic_flow_${FLOW_ID}.json"
  else
    FLOW_ID=$((port - 5226 + 1))
    LOGFILE="$LOG_DIR/prague_flow_${FLOW_ID}.json"
  fi
  iperf3 -s -B $BIND_IP -p $port -J --logfile "$LOGFILE" &
  IPERF_PIDS+=($!)
  echo "  Started iperf3 server on port $port -> $LOGFILE"
done

echo '50 iperf3 servers started (ports 5201-5250) on $BIND_IP.'
echo 'Each server will log to JSON file for accurate goodput measurement.'
echo 'Press Ctrl+C to stop all servers.'

# Function to cleanup servers on exit
cleanup() {
  echo ''
  echo 'Stopping all iperf3 servers...'
  
  # Send SIGTERM first for graceful shutdown
  for pid in "${IPERF_PIDS[@]}"; do
    kill -TERM $pid 2>/dev/null || true
  done
  
  # Wait a moment for graceful shutdown
  sleep 1
  
  # Force kill any remaining processes
  for pid in "${IPERF_PIDS[@]}"; do
    kill -9 $pid 2>/dev/null || true
  done
  
  # Also cleanup by port pattern
  pkill -9 -f "iperf3 -s.*-p 52" 2>/dev/null || true
  
  # Clean up trailing invalid JSON fragments from log files
  # When iperf3 server is interrupted, it appends an error JSON fragment to the log
  # We need to find and remove these trailing fragments
  echo 'Cleaning up log files...'
  for logfile in "$LOG_DIR"/*.json; do
    if [ -f "$logfile" ]; then
      # Check if file has trailing interrupt error
      if grep -q '"error".*interrupt.*server has terminated' "$logfile" 2>/dev/null; then
        # Use Python to clean up the trailing invalid JSON fragment
        python3 -c '
import sys
filepath = sys.argv[1]
with open(filepath, "r") as f:
    content = f.read()
# Find the start of the trailing invalid fragment
# It looks like: {"start":{"connected":[],... with empty connected array
# The valid JSON ends with } before this fragment starts
marker = chr(123) + chr(10) + chr(9) + chr(34) + "start" + chr(34) + chr(58) + chr(9) + chr(123) + chr(10) + chr(9) + chr(9) + chr(34) + "connected" + chr(34) + chr(58) + chr(9) + chr(91) + chr(93)
pos = content.rfind(marker)
if pos > 0:
    cleaned = content[:pos].rstrip()
    with open(filepath, "w") as f:
        f.write(cleaned)
    print(f"  Cleaned: {filepath}")
' "$logfile" 2>/dev/null || echo "  Warning: Could not clean $logfile"
      fi
    fi
  done
  
  echo 'All servers stopped.'
  echo "Receiver logs saved to: $LOG_DIR"
  # Show summary of valid logs
  VALID_LOGS=$(ls -1 "$LOG_DIR"/*.json 2>/dev/null | wc -l)
  echo "Valid log files: $VALID_LOGS"
  exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# Wait and show connection status periodically
echo 'Receiver is ready. Waiting for traffic...'
echo 'You can monitor traffic with: ss -tn | grep -E "520[0-9]" or netstat -tn | grep -E "520[0-9]"'
echo ''

# Show connection count every 10 seconds
while true; do
  CONN_COUNT=$(ss -tn 2>/dev/null | grep -cE ':520[0-9]' || echo 0)
  echo "[$(date '+%H:%M:%S')] Active iperf3 connections: $CONN_COUNT"
  sleep 10
done
