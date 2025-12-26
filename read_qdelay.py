#!/usr/bin/env bfrt_python
"""Read a qdelay register entry using bfrt_python and print a single integer value.

This script follows the BFShell / bfrt_python conventions used in the
project's test utilities. It attempts to use `table.get(...)` (a higher-level
convenience API) with `from_hw=True`, and falls back to `entry_get` when
necessary.

Usage: bfrt_python read_qdelay.py <register_index> [--pipe PIPE]

Exit codes:
  0 - success and printed integer value
  2 - invalid usage/argument
  3 - table not found
  4 - no entry
  5 - read failed
  6 - no value found in entry
"""
from __future__ import annotations
import argparse
import sys


def _get_root():
    root = globals().get("bfrt") or globals().get("simple_forward")
    if root is None:
        raise RuntimeError("Cannot find BFRT root object (`bfrt` or `simple_forward`).")
    return root


def _extract_int_from_entry_data(ent) -> int | None:
    # ent is a table entry object returned by table.get() or table.entry_get()
    data = getattr(ent, "data", None)
    if data is None:
        # if it's the low-level response, try to_dict fallback
        try:
            dd = ent.to_dict()
            data = {k: v for k, v in dd.items()}
        except Exception:
            return None

    # keys may be bytes; normalize
    items = []
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                k_str = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
            except Exception:
                k_str = str(k)
            items.append((k_str, v))
    else:
        return None

    # prefer keys containing qdelay or scalar f1-like fields
    pref_order = ["qdelay", ".f1", ".first", ".value", "f1"]
    for pref in pref_order:
        for k, v in items:
            if pref in k.lower():
                cand = v[0] if isinstance(v, (list, tuple)) and len(v) > 0 else v
                if isinstance(cand, (bytes, bytearray)):
                    return int.from_bytes(cand, byteorder='big', signed=False)
                try:
                    return int(cand)
                except Exception:
                    continue

    # fallback: first numeric-looking field
    for _, v in items:
        cand = v[0] if isinstance(v, (list, tuple)) and len(v) > 0 else v
        if isinstance(cand, (bytes, bytearray)):
            return int.from_bytes(cand, byteorder='big', signed=False)
        try:
            return int(cand)
        except Exception:
            continue

    return None


def main() -> None:
    p = argparse.ArgumentParser(description="Read qdelay register via bfrt_python")
    p.add_argument("index", type=int)
    p.add_argument("--pipe", type=int, default=None, help="Optional pipe override")
    p.add_argument("--from-hw", action="store_true", help="Force reading from HW (default true)")
    args = p.parse_args()

    idx = args.index

    try:
        root = _get_root()
    except Exception as e:
        print(f"Cannot find BFRT root: {e}", file=sys.stderr)
        sys.exit(3)

    # table path used in interactive shell
    try:
        table = root.simple_forward.pipe.SwitchEgress.qdelay_reg
    except Exception:
        # try shorter path if program is named differently
        try:
            table = root.pipe.SwitchEgress.qdelay_reg
        except Exception as e:
            print(f"Cannot access qdelay_reg table: {e}", file=sys.stderr)
            sys.exit(3)

    # pick pipe: either provided or derived from index
    pipe = args.pipe if args.pipe is not None else ((idx >> 7) & 0x3)
    # some BFRT objects support set_pipe
    if hasattr(root, "set_pipe"):
        try:
            root.set_pipe(pipe)
        except Exception:
            pass

    # Prefer the convenience `get` callable if available
    try:
        ent = table.get(idx, from_hw=True, print_ents=False)
        val = _extract_int_from_entry_data(ent)
        if val is None:
            print("no_value", file=sys.stderr)
            sys.exit(6)
        print(val)
        sys.exit(0)
    except Exception:
        # fallback to entry_get with explicit Target
        import bfrt_grpc.client as gc
        tgt = gc.Target(device_id=0, pipe_id=pipe)
        try:
            resp = table.entry_get(tgt, [table.make_key([gc.KeyTuple('$REGISTER_INDEX', idx)])], {"from_hw": True})
            data, _ = next(resp)
            val = _extract_int_from_entry_data(data)
            if val is None:
                print("no_value", file=sys.stderr)
                sys.exit(6)
            print(val)
            sys.exit(0)
        except StopIteration:
            print("no_entry", file=sys.stderr)
            sys.exit(4)
        except Exception as e:
            print(f"entry_get failed: {e}", file=sys.stderr)
            sys.exit(5)



main()
