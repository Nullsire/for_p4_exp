#!/bin/bash
# Wrapper to run check_queues.py in bfrt_python

# Source SDE environment
if [ -f ~/bf-sde-9.13.0/set_sde.bash ]; then
    set +e
    . ~/bf-sde-9.13.0/set_sde.bash
    set -e
else
    echo "Error: Cannot find set_sde.bash"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOT=/tmp/check_queues_bootstrap.py

# Generate bootstrap
{
  echo "import sys"
  echo "path = r\"$SCRIPT_DIR/check_queues.py\""
  echo "with open(path, 'r', encoding='utf-8') as f:" 
  echo "  code = compile(f.read(), path, 'exec')"
  echo "exec(code, globals())"
} > "$BOOT"

# Run bfshell and filter out error messages about invalid ports
bfshell -b "$BOOT" 2>&1 | grep -v "Error: table_entry_get failed"
