#!/usr/bin/env bfrt_python
"""Explore all available BFRT API interfaces for Tofino switch.

This script scans the BFRT object tree and lists:
- All available tables
- Table fields and their types
- Table methods (get, add, mod, del, etc.)
- Counter tables
- Register tables

Usage: bfrt_python bfrt_explore.py [--filter PATTERN]
"""

import sys
from typing import Any


def _get_root():
    """Get BFRT root object."""
    root = globals().get("bfrt") or globals().get("simple_forward")
    if root is None:
        raise RuntimeError("Cannot find BFRT root object (`bfrt` or `simple_forward`).")
    return root


def _format_type(type_str: str) -> str:
    """Format type string for better readability."""
    type_map = {
        "uint8": "u8",
        "uint16": "u16",
        "uint32": "u32",
        "uint64": "u64",
        "int8": "i8",
        "int16": "i16",
        "int32": "i32",
        "int64": "i64",
        "bool": "bool",
        "bytes": "bytes",
        "string": "str",
    }
    return type_map.get(type_str, type_str)


def _get_table_methods(table_obj: Any) -> list[str]:
    """Get list of available methods for a table object."""
    methods = []
    for attr in dir(table_obj):
        if not attr.startswith("_"):
            try:
                obj = getattr(table_obj, attr)
                if callable(obj):
                    methods.append(attr)
            except Exception:
                pass
    return sorted(methods)


def _is_leaf_table(obj: Any) -> bool:
    """Check if an object is a leaf table (has table methods but no child nodes)."""
    type_name = type(obj).__name__
    if type_name != "BFLeaf":
        return False
    return True


def _is_container_node(obj: Any) -> bool:
    """Check if an object is a container node (BFNode)."""
    type_name = type(obj).__name__
    return type_name == "BFNode"


def _get_child_names(obj: Any) -> list[str]:
    """Get list of child attribute names that are BFNode or BFLeaf."""
    children = []
    for attr in dir(obj):
        if attr.startswith("_"):
            continue
        try:
            child = getattr(obj, attr)
            child_type = type(child).__name__
            if child_type in ("BFNode", "BFLeaf"):
                children.append(attr)
        except Exception:
            pass
    return sorted(children)


def _explore_tree(obj: Any, path: str, filter_pattern: str, max_depth: int, visited: set) -> None:
    """Recursively explore BFRT object tree."""
    if max_depth <= 0:
        return
    
    obj_id = id(obj)
    if obj_id in visited:
        return
    visited.add(obj_id)
    
    type_name = type(obj).__name__
    depth = path.count(".") if path else 0
    indent = "  " * depth
    
    # Check if matches filter
    matches_filter = (not filter_pattern) or (filter_pattern.lower() in path.lower())
    
    if type_name == "BFLeaf":
        # This is a table
        if matches_filter:
            methods = _get_table_methods(obj)
            # Filter to show only important methods
            important_methods = [m for m in methods if m in 
                ("add", "delete", "mod", "get", "dump", "info", "clear", 
                 "entry", "entry_add", "entry_del", "entry_mod", "entry_get",
                 "add_with_normal", "add_with_coalescing", "mod_with_normal", "mod_with_coalescing",
                 "mod_inc")]
            
            print(f"{indent}[TABLE] {path}")
            if important_methods:
                print(f"{indent}  Methods: {', '.join(important_methods)}")
    
    elif type_name == "BFNode":
        # This is a container node
        children = _get_child_names(obj)
        if children:
            if matches_filter and path:  # Don't print root
                print(f"{indent}[NODE] {path}")
            
            # Explore children
            for child_name in children:
                try:
                    child = getattr(obj, child_name)
                    child_path = f"{path}.{child_name}" if path else child_name
                    _explore_tree(child, child_path, filter_pattern, max_depth - 1, visited)
                except Exception as e:
                    pass


def main() -> None:
    import argparse
    
    # Skip first argument (script name) to avoid duplicate parsing
    if len(sys.argv) > 1 and sys.argv[0].endswith('.py'):
        sys.argv = [sys.argv[0]] + sys.argv[1:]
    
    parser = argparse.ArgumentParser(
        description="Explore all available BFRT API interfaces for Tofino switch"
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Filter results by pattern (e.g., 'tm', 'port', 'queue')"
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=10,
        help="Maximum recursion depth (default: 10)"
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="List all tables only"
    )
    args = parser.parse_args()
    
    try:
        root = _get_root()
    except Exception as e:
        print(f"Error: Cannot find BFRT root: {e}", file=sys.stderr)
        sys.exit(1)
    
    print("=" * 80)
    print("BFRT API Explorer for Tofino Switch")
    print("=" * 80)
    print(f"Root object type: {type(root).__name__}")
    print(f"Filter pattern: {args.filter if args.filter else 'none'}")
    print(f"Max depth: {args.max_depth}")
    print()
    
    # Explore root object
    visited = set()
    _explore_tree(root, "", args.filter, args.max_depth, visited)
    
    print()
    print("=" * 80)
    print("Exploration complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
