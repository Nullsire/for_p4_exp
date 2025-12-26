#!/bin/bash
# Configuration I: BW=120Mbps, RTT=10ms, MTU=1500B

INTERFACE=enp2s0
BIND_IP=0.0.0.0

# 1. Set MTU
echo 'Setting MTU to 1500 on $INTERFACE...'
sudo ip link set dev $INTERFACE mtu 1500

# 2. Set RTT (tc netem)
echo 'Setting RTT delay 10ms on $INTERFACE...'
# Reset existing tc qdiscs
sudo tc qdisc del dev $INTERFACE root 2>/dev/null || true
# Add netem delay
sudo tc qdisc add dev $INTERFACE root netem delay 10ms

# 3. Start multiple iperf3 Servers (one per flow)
# iperf3 can only handle one client per server instance,
# so we need to start multiple servers on different ports.
echo 'Starting 50 iperf3 server instances on ports 5201-5250...'
echo "Binding to IP: $BIND_IP"

# Array to store server PIDs
declare -a IPERF_PIDS

for port in $(seq 5201 5250); do
  iperf3 -s -B $BIND_IP -p $port -D
  IPERF_PIDS+=($!)
done

echo '50 iperf3 servers started (ports 5201-5250) on $BIND_IP.'
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
  
  echo 'All servers stopped.'
}

# Use a flag to prevent duplicate cleanup calls
CLEANUP_DONE=0
safe_cleanup() {
  if [ $CLEANUP_DONE -eq 0 ]; then
    CLEANUP_DONE=1
    cleanup
  fi
  exit 0
}
trap safe_cleanup SIGINT SIGTERM EXIT

# Wait and show connection status periodically
echo 'Receiver is ready. Waiting for traffic...'
echo "You can monitor traffic with: ss -tn state established '( dport >= 5201 and dport <= 5250 )'"
echo ''

# Show connection count every 10 seconds
while true; do
  # Count active iperf3 flows (not TCP connections)
  # iperf3 creates 2 TCP connections per flow (control + data)
  # So we count unique local ports in the 5201-5250 range
  FLOW_COUNT=$(ss -tn state established '( sport >= 5201 and sport <= 5250 )' 2>/dev/null | awk 'NR>1 {split($4,a,":"); print a[2]}' | sort -u | wc -l)
  echo "[$(date '+%H:%M:%S')] Active iperf3 flows: $FLOW_COUNT"
  sleep 10
done
