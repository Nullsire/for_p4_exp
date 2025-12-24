#!/bin/bash
# Configuration I: BW=120Mbps, RTT=10ms, MTU=1500B

INTERFACE=enp2s0
DST_IP=192.168.6.2
LOG_DIR="./exp_logs_I"
mkdir -p "$LOG_DIR"
echo "Logs will be saved to $LOG_DIR"

# 1. Set MTU
echo 'Setting MTU to 1500 on $INTERFACE...'
sudo ifconfig $INTERFACE mtu 1500

# 2. Start Traffic Phases
echo 'Starting traffic generation...'
# Global flow ID counters
CUBIC_FLOW_ID=0
PRAGUE_FLOW_ID=0

echo 'Phase 1: Starting 1 new Cubic flows and 1 new Prague flows...'
# Add 1 Cubic flows for 480s
for j in $(seq 1 1); do
  CUBIC_FLOW_ID=$((CUBIC_FLOW_ID + 1))
  PORT=$((5201 + $CUBIC_FLOW_ID - 1))
  LOGFILE="$LOG_DIR/cubic_flow_${CUBIC_FLOW_ID}.json"
  iperf3 -c $DST_IP -p $PORT -t 480 -i 0.1 -C cubic -J --logfile "$LOGFILE" &
  echo "  Started Cubic flow $CUBIC_FLOW_ID on port $PORT -> $LOGFILE"
done
# Add 1 Prague flows for 480s
for j in $(seq 1 1); do
  PRAGUE_FLOW_ID=$((PRAGUE_FLOW_ID + 1))
  PORT=$((5201 + 25 + $PRAGUE_FLOW_ID - 1))
  LOGFILE="$LOG_DIR/prague_flow_${PRAGUE_FLOW_ID}.json"
  iperf3 -c $DST_IP -p $PORT -t 480 -i 0.1 -C prague -J --logfile "$LOGFILE" &
  echo "  Started Prague flow $PRAGUE_FLOW_ID on port $PORT -> $LOGFILE"
done
echo 'Sleeping 120s before Phase 2...'
sleep 120
echo 'Phase 2: Starting 1 new Cubic flows and 1 new Prague flows...'
# Add 1 Cubic flows for 360s
for j in $(seq 1 1); do
  CUBIC_FLOW_ID=$((CUBIC_FLOW_ID + 1))
  PORT=$((5201 + $CUBIC_FLOW_ID - 1))
  LOGFILE="$LOG_DIR/cubic_flow_${CUBIC_FLOW_ID}.json"
  iperf3 -c $DST_IP -p $PORT -t 360 -i 0.1 -C cubic -J --logfile "$LOGFILE" &
  echo "  Started Cubic flow $CUBIC_FLOW_ID on port $PORT -> $LOGFILE"
done
# Add 1 Prague flows for 360s
for j in $(seq 1 1); do
  PRAGUE_FLOW_ID=$((PRAGUE_FLOW_ID + 1))
  PORT=$((5201 + 25 + $PRAGUE_FLOW_ID - 1))
  LOGFILE="$LOG_DIR/prague_flow_${PRAGUE_FLOW_ID}.json"
  iperf3 -c $DST_IP -p $PORT -t 360 -i 0.1 -C prague -J --logfile "$LOGFILE" &
  echo "  Started Prague flow $PRAGUE_FLOW_ID on port $PORT -> $LOGFILE"
done
echo 'Sleeping 120s before Phase 3...'
sleep 120
echo 'Phase 3: Starting 8 new Cubic flows and 8 new Prague flows...'
# Add 8 Cubic flows for 240s
for j in $(seq 1 8); do
  CUBIC_FLOW_ID=$((CUBIC_FLOW_ID + 1))
  PORT=$((5201 + $CUBIC_FLOW_ID - 1))
  LOGFILE="$LOG_DIR/cubic_flow_${CUBIC_FLOW_ID}.json"
  iperf3 -c $DST_IP -p $PORT -t 240 -i 0.1 -C cubic -J --logfile "$LOGFILE" &
  echo "  Started Cubic flow $CUBIC_FLOW_ID on port $PORT -> $LOGFILE"
done
# Add 8 Prague flows for 240s
for j in $(seq 1 8); do
  PRAGUE_FLOW_ID=$((PRAGUE_FLOW_ID + 1))
  PORT=$((5201 + 25 + $PRAGUE_FLOW_ID - 1))
  LOGFILE="$LOG_DIR/prague_flow_${PRAGUE_FLOW_ID}.json"
  iperf3 -c $DST_IP -p $PORT -t 240 -i 0.1 -C prague -J --logfile "$LOGFILE" &
  echo "  Started Prague flow $PRAGUE_FLOW_ID on port $PORT -> $LOGFILE"
done
echo 'Sleeping 120s before Phase 4...'
sleep 120
echo 'Phase 4: Starting 15 new Cubic flows and 15 new Prague flows...'
# Add 15 Cubic flows for 120s
for j in $(seq 1 15); do
  CUBIC_FLOW_ID=$((CUBIC_FLOW_ID + 1))
  PORT=$((5201 + $CUBIC_FLOW_ID - 1))
  LOGFILE="$LOG_DIR/cubic_flow_${CUBIC_FLOW_ID}.json"
  iperf3 -c $DST_IP -p $PORT -t 120 -i 0.1 -C cubic -J --logfile "$LOGFILE" &
  echo "  Started Cubic flow $CUBIC_FLOW_ID on port $PORT -> $LOGFILE"
done
# Add 15 Prague flows for 120s
for j in $(seq 1 15); do
  PRAGUE_FLOW_ID=$((PRAGUE_FLOW_ID + 1))
  PORT=$((5201 + 25 + $PRAGUE_FLOW_ID - 1))
  LOGFILE="$LOG_DIR/prague_flow_${PRAGUE_FLOW_ID}.json"
  iperf3 -c $DST_IP -p $PORT -t 120 -i 0.1 -C prague -J --logfile "$LOGFILE" &
  echo "  Started Prague flow $PRAGUE_FLOW_ID on port $PORT -> $LOGFILE"
done

echo 'All flows started. Waiting for experiment to finish...'
wait
echo 'Experiment Done.'
echo "Logs saved to: $LOG_DIR"
echo "Total Cubic flows: $CUBIC_FLOW_ID, Total Prague flows: $PRAGUE_FLOW_ID"
