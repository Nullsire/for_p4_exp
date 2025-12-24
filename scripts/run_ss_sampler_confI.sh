#!/bin/bash
# Fine-grained TCP stats sampler - Configuration I
# Sampling interval: 2ms
# Total duration: 480s

# Configuration
INTERVAL_MS=2
DURATION=480
DST_IP=192.168.6.2

LOG_DIR="./exp_logs_I"
mkdir -p "$LOG_DIR"
SS_LOG="$LOG_DIR/ss_stats.csv"

# Convert ms to seconds for sleep (using bc for floating point)
INTERVAL_SEC=$(echo "scale=6; $INTERVAL_MS / 1000" | bc)

echo "Starting fine-grained TCP stats sampling..."
echo "  Interval: ${INTERVAL_MS}ms"
echo "  Duration: ${DURATION}s"
echo "  Target IP: $DST_IP"
echo "  Output: $SS_LOG"

# Write CSV header
echo 'timestamp_ns,local_addr,local_port,remote_addr,remote_port,state,cwnd,ssthresh,rtt_us,rttvar_us,rto_ms,mss,bytes_sent,bytes_acked,bytes_received,segs_out,segs_in,retrans,lost,delivery_rate,pacing_rate' > "$SS_LOG"

# Calculate end time
START_TIME=$(date +%s%N)
END_TIME=$((START_TIME + DURATION * 1000000000))

echo "Sampling started at $(date)"
echo "Press Ctrl+C to stop early"

# Trap for cleanup
cleanup() {
  echo ""
  echo "Sampling stopped. $(wc -l < "$SS_LOG") samples collected."
  echo "Output saved to: $SS_LOG"
  exit 0
}
trap cleanup SIGINT SIGTERM

# Main sampling loop
SAMPLE_COUNT=0
while [ $(date +%s%N) -lt $END_TIME ]; do
  TIMESTAMP=$(date +%s%N)
  
  # Get TCP stats for connections to/from target IP
  # ss -tin provides detailed TCP info including cwnd, rtt, etc.
  ss -tin dst $DST_IP or src $DST_IP 2>/dev/null | awk -v ts="$TIMESTAMP" '
    /^tcp/ {
      state=$1
      # Parse local and remote addresses
      split($4, local, ":")
      split($5, remote, ":")
      local_addr=local[1]; local_port=local[2]
      remote_addr=remote[1]; remote_port=remote[2]
    }
    /cubic|prague|bbr|reno/ {
      # Initialize variables
      cwnd=""; ssthresh=""; rtt=""; rttvar=""; rto=""; mss=""
      bytes_sent=""; bytes_acked=""; bytes_received=""
      segs_out=""; segs_in=""; retrans=""; lost=""
      delivery_rate=""; pacing_rate=""
      
      # Parse key-value pairs
      for(i=1; i<=NF; i++) {
        if($i ~ /^cwnd:/) { split($i, a, ":"); cwnd=a[2] }
        if($i ~ /^ssthresh:/) { split($i, a, ":"); ssthresh=a[2] }
        if($i ~ /^rtt:/) { split($i, a, ":"); split(a[2], b, "/"); rtt=b[1]; rttvar=b[2] }
        if($i ~ /^rto:/) { split($i, a, ":"); rto=a[2] }
        if($i ~ /^mss:/) { split($i, a, ":"); mss=a[2] }
        if($i ~ /^bytes_sent:/) { split($i, a, ":"); bytes_sent=a[2] }
        if($i ~ /^bytes_acked:/) { split($i, a, ":"); bytes_acked=a[2] }
        if($i ~ /^bytes_received:/) { split($i, a, ":"); bytes_received=a[2] }
        if($i ~ /^segs_out:/) { split($i, a, ":"); segs_out=a[2] }
        if($i ~ /^segs_in:/) { split($i, a, ":"); segs_in=a[2] }
        if($i ~ /^retrans:/) { split($i, a, ":"); split(a[2], b, "/"); retrans=b[1] }
        if($i ~ /^lost:/) { split($i, a, ":"); lost=a[2] }
        if($i ~ /^delivery_rate/) { split($i, a, ":"); delivery_rate=a[2] }
        if($i ~ /^pacing_rate/) { split($i, a, ":"); pacing_rate=a[2] }
      }
      
      # Output CSV line
      printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n", \
        ts, local_addr, local_port, remote_addr, remote_port, state, \
        cwnd, ssthresh, rtt, rttvar, rto, mss, \
        bytes_sent, bytes_acked, bytes_received, segs_out, segs_in, \
        retrans, lost, delivery_rate, pacing_rate
    }
  ' >> "$SS_LOG"
  
  SAMPLE_COUNT=$((SAMPLE_COUNT + 1))
  
  # Progress indicator every 1000 samples
  if [ $((SAMPLE_COUNT % 1000)) -eq 0 ]; then
    ELAPSED=$(($(date +%s) - START_TIME / 1000000000))
    echo -ne "\r  Samples: $SAMPLE_COUNT, Elapsed: ${ELAPSED}s"
  fi
  
  # Sleep for interval (using python for precise sub-ms sleep)
  python3 -c "import time; time.sleep($INTERVAL_SEC)" 2>/dev/null || sleep $INTERVAL_SEC
done

echo ""
echo "Sampling complete. $SAMPLE_COUNT samples collected."
echo "Output saved to: $SS_LOG"

# Show sample statistics
echo ""
echo "Sample statistics:"
echo "  Total lines: $(wc -l < "$SS_LOG")"
echo "  File size: $(du -h "$SS_LOG" | cut -f1)"
