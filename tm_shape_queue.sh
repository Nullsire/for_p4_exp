#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  tm_shape_queue.sh apply  --dev-port 189 [--queue 0] --max-gbps 1 [--sde /root/bf-sde-9.13.0]
  tm_shape_queue.sh reset  [--dev-port 189] [--queue 0]   # Without --dev-port: reset ALL ports
  tm_shape_queue.sh watch  --dev-port 189 [--queue 0] [--interval 1] [--duration 30 | --iterations 60] [--log-file /path/to/log.tsv]

Logging:
  --log-file <PATH>   Save output to specified file (in addition to stdout)
  --log-append        Append to log file instead of overwriting

Notes:
- pg_id is derived from `tf1.tm.port.cfg` (do not assume pg_id = dev_port % 128).
- Shaping can be applied at TM port or TM queue scope; default is port scope.
- Rate encoding: this SDE build uses unit="BPS" with values in ~1kbps units.
- Shaping/counters reset when `bf_switchd` (or `contrl_test`) restarts; re-run `apply` after a restart.
- Queue depth configuration is NOT supported via BFRT in this SDE version.

Examples:
  # Limit dev_port 189 queue0 to 1Gbps
  ./tm_shape_queue.sh apply --dev-port 189 --queue 0 --max-gbps 1

  # Watch counters for 30s
  ./tm_shape_queue.sh watch --dev-port 189 --queue 0 --duration 30 --interval 1

  # Remove the max-rate cap for a specific port
  ./tm_shape_queue.sh reset --dev-port 189 --queue 0

  # Reset ALL ports shaping (recommended before ending experiment)
  ./tm_shape_queue.sh reset
EOF
}

cmd=${1:-}
shift || true

DEV_PORT=""
QUEUE=0
SCOPE=""
ALL_QUEUES=0
CLEAR_COUNTERS=0
MAX_GBPS=""
MAX_MBPS=""
MAX_BPS=""
INTERVAL="1"
DURATION=""
ITERATIONS=""
LOG_FILE=""
LOG_APPEND=0
SDE_BASE="/root/bf-sde-9.13.0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope) SCOPE="$2"; shift 2;;
    --all-queues) ALL_QUEUES=1; shift 1;;
    --clear-counters) CLEAR_COUNTERS=1; shift 1;;
    --dev-port) DEV_PORT="$2"; shift 2;;
    --queue) QUEUE="$2"; shift 2;;
    --max-gbps) MAX_GBPS="$2"; shift 2;;
    --max-mbps) MAX_MBPS="$2"; shift 2;;
    --max-bps) MAX_BPS="$2"; shift 2;;
    --interval) INTERVAL="$2"; shift 2;;
    --duration) DURATION="$2"; shift 2;;
    --iterations) ITERATIONS="$2"; shift 2;;
    --log-file) LOG_FILE="$2"; shift 2;;
    --log-append) LOG_APPEND=1; shift 1;;
    --sde) SDE_BASE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

if [[ -z "$cmd" ]]; then
  usage
  exit 2
fi

case "$cmd" in
  apply)
    MODE=apply
    if [[ -z "$DEV_PORT" ]]; then
      echo "--dev-port is required for apply"
      usage
      exit 2
    fi
    ;;
  reset)
    MODE=reset
    # reset without --dev-port will reset ALL ports
    ;;
  watch)
    MODE=watch
    if [[ -z "$DEV_PORT" ]]; then
      echo "--dev-port is required for watch"
      usage
      exit 2
    fi
    ;;
  *)
    echo "Unknown command: $cmd"
    usage
    exit 2
    ;;
esac

# shellcheck disable=SC1090
# set_sde.bash probes $PWD/*.manifest via `ls`, which returns non-zero
# when no manifest exists; under `set -e` that would abort this script.
set +e
source "$SDE_BASE/set_sde.bash"
set -e

# Preflight: bfshell/bfrt_python requires BFRT to be up.
# Note: BFRT may run as a standalone `bf_switchd` *process* OR be embedded inside `contrl_test`
# (in that case there may be no `bf_switchd` process name to match).
have_bf_switchd=0
pgrep -af bf_switchd >/dev/null 2>&1 && have_bf_switchd=1

have_contrl=0
pgrep -af contrl_test >/dev/null 2>&1 && have_contrl=1

have_bfrt_port=0
ss -ltn 2>/dev/null | grep -qE '[:.]50052\b|[:.]9999\b|[:.]8008\b|[:.]7777\b' && have_bfrt_port=1

if [[ $have_bf_switchd -eq 0 && $have_contrl -eq 0 && $have_bfrt_port -eq 0 ]]; then
  cat <<EOF
ERROR: BFRT is not running, so BFRT cannot be initialized (you'll see: "could not initialize bf_rt ... err: 1").

Start the dataplane first (in another terminal) using ONE of:
  1) $SDE_BASE/run_switchd.sh -p simple_forward
  2) $SDE_BASE/run_switchd.sh -c "$SDE_INSTALL/share/p4/targets/tofino/simple_forward.conf"
  3) cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)/.." && ./contrl_test

Then re-run this script.
EOF
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)

BOOT=/tmp/tm_shape_queue_bootstrap.py
# Remove old bootstrap file to avoid permission issues
rm -f "$BOOT"
{
  echo "import sys"
  echo "path = r\"$SCRIPT_DIR/tm_shape_queue.py\""
  echo "sys.argv = [path, '--mode', '$MODE', '--queue', '$QUEUE', '--interval', '$INTERVAL']"
  if [[ -n "$DEV_PORT" ]]; then
    echo "sys.argv += ['--dev-port', '$DEV_PORT']"
  fi
  if [[ -n "$SCOPE" ]]; then
    echo "sys.argv += ['--scope', '$SCOPE']"
  fi
  if [[ "$ALL_QUEUES" -eq 1 ]]; then
    echo "sys.argv += ['--all-queues']"
  fi
  if [[ "$CLEAR_COUNTERS" -eq 1 ]]; then
    echo "sys.argv += ['--clear-counters']"
  fi
  if [[ -n "$DURATION" ]]; then
    echo "sys.argv += ['--duration', '$DURATION']"
  fi
  if [[ -n "$ITERATIONS" ]]; then
    echo "sys.argv += ['--iterations', '$ITERATIONS']"
  fi
  if [[ -n "$MAX_GBPS" ]]; then
    echo "sys.argv += ['--max-gbps', '$MAX_GBPS']"
  fi
  if [[ -n "$MAX_MBPS" ]]; then
    echo "sys.argv += ['--max-mbps', '$MAX_MBPS']"
  fi
  if [[ -n "$MAX_BPS" ]]; then
    echo "sys.argv += ['--max-bps', '$MAX_BPS']"
  fi
  if [[ -n "$LOG_FILE" ]]; then
    echo "sys.argv += ['--log-file', '$LOG_FILE']"
  fi
  if [[ "$LOG_APPEND" -eq 1 ]]; then
    echo "sys.argv += ['--log-append']"
  fi
  echo "with open(path, 'r', encoding='utf-8') as f:" 
  echo "  code = compile(f.read(), path, 'exec')"
  echo "exec(code, globals())"
} > "$BOOT"

# Run bfshell and filter out error messages about invalid ports
# (these errors occur when scanning all ports during reset without --dev-port)
bfshell -b "$BOOT" 2>&1 | grep -v "Error: table_entry_get failed"
