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
  for port in $(seq 5201 5250); do
    pkill -f "iperf3 -s.*-p $port" 2>/dev/null || true
  done
  # Also kill by PID
  for pid in "${IPERF_PIDS[@]}"; do
    kill $pid 2>/dev/null || true
  done
  echo 'All servers stopped.'
  echo "Receiver logs saved to: $LOG_DIR"
  exit 0
}

trap cleanup SIGINT SIGTERM

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
