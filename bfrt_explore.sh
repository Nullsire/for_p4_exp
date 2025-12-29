#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bfrt_explore.sh [--filter PATTERN] [--max-depth N] [--list-tables] [--sde /root/bf-sde-9.13.0]

Options:
  --filter <PATTERN>  Filter results by pattern (e.g., 'tm', 'port', 'queue')
  --max-depth <N>     Maximum recursion depth (default: 3)
  --list-tables        List all tables only (no field details)
  --sde <PATH>        SDE installation path (default: ~/bf-sde-9.13.0)

Examples:
  # Explore all BFRT interfaces
  ./bfrt_explore.sh

  # Filter for TM-related tables
  ./bfrt_explore.sh --filter tm

  # List all tables only
  ./bfrt_explore.sh --list-tables

  # Explore with deeper recursion
  ./bfrt_explore.sh --max-depth 5

  # Use custom SDE path
  ./bfrt_explore.sh --sde /custom/path/bf-sde-9.13.0
EOF
}

FILTER=""
MAX_DEPTH=3
LIST_TABLES=0
SDE_BASE="/root/bf-sde-9.13.0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --filter) FILTER="$2"; shift 2;;
    --max-depth) MAX_DEPTH="$2"; shift 2;;
    --list-tables) LIST_TABLES=1; shift 1;;
    --sde) SDE_BASE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

# Source SDE environment
if [ -f "$SDE_BASE/set_sde.bash" ]; then
    set +e
    . "$SDE_BASE/set_sde.bash"
else
    echo "Error: Cannot find set_sde.bash at $SDE_BASE"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOT=/tmp/bfrt_explore_bootstrap.py

# Generate bootstrap
{
  echo "import sys"
  echo "path = r\"$SCRIPT_DIR/bfrt_explore.py\""
  echo "sys.argv = [path]"
  if [[ -n "$FILTER" ]]; then
    echo "sys.argv += ['--filter', '$FILTER']"
  fi
  echo "sys.argv += ['--max-depth', '$MAX_DEPTH']"
  if [[ "$LIST_TABLES" -eq 1 ]]; then
    echo "sys.argv += ['--list-tables']"
  fi
  echo "with open(path, 'r', encoding='utf-8') as f:" 
  echo "  code = compile(f.read(), path, 'exec')"
  echo "exec(code, globals())"
} > "$BOOT"

# Run bfshell
bfshell -b "$BOOT"
