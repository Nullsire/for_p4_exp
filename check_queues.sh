#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  check_queues.sh [--pipe 0|1] [--dev-port NUM] [--sde /root/bf-sde-9.13.0]

Options:
  --pipe <NUM>   Pipe number to scan (0 or 1, default: 1)
  --dev-port <NUM>  Query specific dev_port (overrides --pipe)
  --sde <PATH>   SDE installation path (default: ~/bf-sde-9.13.0)

Examples:
  # Scan Pipe 1 (ports 128-255)
  ./check_queues.sh

  # Scan Pipe 0 (ports 0-127)
  ./check_queues.sh --pipe 0

  # Query specific port 189
  ./check_queues.sh --dev-port 189

  # Use custom SDE path
  ./check_queues.sh --pipe 0 --sde /custom/path/bf-sde-9.13.0

Note: Queue depth configuration is not supported via BFRT in this SDE version.
EOF
}

PIPE=1
DEV_PORT=""
SDE_BASE="/root/bf-sde-9.13.0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pipe) PIPE="$2"; shift 2;;
    --dev-port) DEV_PORT="$2"; shift 2;;
    --sde) SDE_BASE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

# Validate pipe number
if [[ "$PIPE" != "0" && "$PIPE" != "1" ]]; then
  echo "Error: --pipe must be 0 or 1"
  usage
  exit 2
fi

# Source SDE environment
if [ -f "$SDE_BASE/set_sde.bash" ]; then
    set +e
    . "$SDE_BASE/set_sde.bash"
else
    echo "Error: Cannot find set_sde.bash at $SDE_BASE"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOT=/tmp/check_queues_bootstrap.py

# Generate bootstrap
{
  echo "import sys"
  echo "path = r\"$SCRIPT_DIR/check_queues.py\""
  echo "sys.argv = [path, '--pipe', '$PIPE']"
  if [[ -n "$DEV_PORT" ]]; then
    echo "sys.argv += ['--dev-port', '$DEV_PORT']"
  fi
  echo "with open(path, 'r', encoding='utf-8') as f:" 
  echo "  code = compile(f.read(), path, 'exec')"
  echo "exec(code, globals())"
} > "$BOOT"

# Run bfshell and filter out error messages about invalid ports
bfshell -b "$BOOT" 2>&1 | grep -v "Error: table_entry_get failed"
