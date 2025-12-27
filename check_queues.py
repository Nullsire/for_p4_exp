import sys
import time


def _entry_raw(entry):
    """Get raw entry data."""
    raw = getattr(entry, "raw", None)
    return raw() if callable(raw) else raw


def _get_pg_mapping(tf1, dev_port):
    """Get port group mapping."""
    ent = tf1.tm.port.cfg.get(dev_port=dev_port, from_hw=True, print_ents=False)
    data = ent.data
    
    def _get(name, default):
        bname = name.encode("utf-8")
        return data.get(bname, default)
    
    pg_id = int(_get("pg_id", -1))
    pg_port_nr = int(_get("pg_port_nr", -1))
    egress_qids = list(_get("egress_qid_queues", []))
    return pg_id, pg_port_nr, egress_qids


def _map_queue_key(local_queue, egress_qids):
    """Map logical queue index to TM queue key."""
    if not egress_qids:
        return local_queue
    if 0 <= local_queue < len(egress_qids):
        try:
            return int(egress_qids[local_queue])
        except Exception:
            return local_queue
    return local_queue


def main():
    # Parse command line arguments
    pipe = 1
    dev_port = None
    
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--pipe' and i + 1 < len(sys.argv):
            pipe = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == '--dev-port' and i + 1 < len(sys.argv):
            dev_port = int(sys.argv[i + 1])
            i += 2
        else:
            i += 1
    
    if dev_port is not None:
        # Query specific port - override pipe calculation
        pipe = dev_port // 128
    
    pipe_start = pipe * 128
    pipe_end = pipe_start + 128
    
    # Setup root
    root = globals().get("bfrt") or globals().get("simple_forward")
    if root is None:
        print("Error: BFRT root not found")
        return
    
    if hasattr(root, "set_pipe"):
        root.set_pipe(pipe)
    
    tf1 = getattr(root, "tf1", globals().get("tf1"))
    if tf1 is None:
        print("Error: tf1 node not found")
        return
    
    if dev_port is not None:
        print(f"Querying specific dev_port: {dev_port}")
    else:
        print(f"Scanning Pipe {pipe} (ports {pipe_start}-{pipe_end-1})...")
    print("=" * 120)
    
    found_ports = 0
    
    # Note: Error messages from invalid ports are filtered by shell script
    ports_to_check = [dev_port] if dev_port is not None else range(pipe_start, pipe_end)
    for dp in ports_to_check:
        try:
            # Get egress port counters
            ent = tf1.tm.counter.eg_port.get(dev_port=dp, from_hw=True, print_ents=False)
            data = ent.data
            drops = data.get(b'drop_count_packets') or data.get('drop_count_packets') or 0
            usage = data.get(b'usage_cells') or data.get('usage_cells') or 0
            wm = data.get(b'watermark_cells') or data.get('watermark_cells') or 0
            
            # Get port group mapping
            pg_id, pg_port_nr, egress_qids = _get_pg_mapping(tf1, dp)
            
            # Get port shaping configuration
            port_sched_cfg = _entry_raw(tf1.tm.port.sched_cfg.get(dev_port=dp, from_hw=True, print_ents=False))
            port_sched_shaping = _entry_raw(tf1.tm.port.sched_shaping.get(dev_port=dp, from_hw=True, print_ents=False))
            
            found_ports += 1
            
            # Check if port should be displayed:
            # When querying specific port (--dev-port), always show it
            # When scanning all ports, only show if:
            # 1. Has drops, usage, or watermark (activity)
            # 2. Has shaping enabled (max_rate_enable=True)
            has_activity = drops > 0 or usage > 0 or wm > 0
            has_shaping = port_sched_cfg.get('max_rate_enable', False) if port_sched_cfg else False
            
            # Always show port when --dev-port is specified, otherwise use criteria
            should_show = (dev_port is not None) or (has_activity or has_shaping)
            
            if should_show:
                # Build status string to show why this port is displayed
                status_flags = []
                if has_activity:
                    status_flags.append("ACTIVE")
                if has_shaping:
                    status_flags.append("SHAPING")
                status_str = " ".join(status_flags)
                
                print(f"\nDev_Port: {dp} (pg_id={pg_id}, pg_port_nr={pg_port_nr}) [{status_str}]")
                print("-" * 120)
                print(f"  Counters:")
                print(f"    Drop_Pkts:     {drops}")
                print(f"    Usage_Cells:   {usage}")
                print(f"    Watermark_Cells: {wm}")
                print(f"  Port Shaping:")
                print(f"    sched_cfg:     {port_sched_cfg}")
                print(f"    sched_shaping: {port_sched_shaping}")
                if egress_qids:
                    print(f"  Egress QID Map: {egress_qids[:8]}")
        except Exception:
            pass
    
    print("\n" + "=" * 120)
    if dev_port is not None:
        print(f"# Queried 1 port")
    else:
        print(f"# Scanned {found_ports} valid ports in Pipe {pipe}")


main()
