import argparse
import sys
import time
from datetime import datetime


class TeeWriter:
    """Write output to both stdout and a log file."""
    
    def __init__(self, log_file=None, append=False):
        self.log_file = None
        self.log_path = log_file
        if log_file:
            mode = "a" if append else "w"
            self.log_file = open(log_file, mode, encoding="utf-8", buffering=1)
            # Write header with timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.log_file.write(f"# Log started at {timestamp}
")
            self.log_file.write(f"# Log file: {log_file}
")
    
    def write(self, msg):
        """Write message to both stdout and log file."""
        print(msg)
        if self.log_file:
            self.log_file.write(msg + "
")
            self.log_file.flush()
    
    def close(self):
        """Close log file and write footer."""
        if self.log_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.log_file.write(f"# Log ended at {timestamp}
")
            self.log_file.close()
            self.log_file = None


# Global writer instance
_writer: TeeWriter | None = None


def _output(msg: str):
    """Output message using the global writer."""
    global _writer
    if _writer:
        _writer.write(msg)
    else:
        print(msg)


def _get_root():
    root = globals().get("bfrt") or globals().get("simple_forward")
    if root is None:
        raise RuntimeError("Cannot find BFRT root object (`bfrt` or `simple_forward`).")
    return root


def _get_counter(table, **keys) -> dict[str, int]:
    ent = table.get(from_hw=True, print_ents=False, **keys)
    data: dict[str, int] = {}
    for k, v in ent.data.items():
        data[k.decode("utf-8")] = int(v)
    return data


def _get_port_stat(port_stat_table, dev_port: int) -> dict[str, int]:
    # port.port_stat key is $DEV_PORT and must be positional.
    ent = port_stat_table.get(dev_port, from_hw=True, print_ents=False)
    data: dict[str, int] = {}
    for k, v in ent.data.items():
        data[k.decode("utf-8")] = int(v)
    return data


def _rate_to_tm_units_bps(rate_bps: int) -> int:
    # Empirically on this platform/SDE, `unit == "BPS"` is encoded in 1kbps units.
    # Example: default max_rate ~= 10,003,999 corresponds to ~10Gbps.
    return max(0, int(rate_bps // 1_000))


def _entry_raw(entry):
    raw = getattr(entry, "raw", None)
    return raw() if callable(raw) else raw


def _get_pg_mapping(tf1, dev_port: int) -> tuple[int, int, list[int]]:
    ent = tf1.tm.port.cfg.get(dev_port=dev_port, from_hw=True, print_ents=False)
    data = ent.data

    def _get(name: str, default):
        bname = name.encode("utf-8")
        return data.get(bname, default)

    pg_id = int(_get("pg_id", -1))
    pg_port_nr = int(_get("pg_port_nr", -1))
    egress_qids = list(_get("egress_qid_queues", []))
    return pg_id, pg_port_nr, egress_qids


def _map_queue_key(local_queue: int, egress_qids: list[int]) -> int:
    """Map a logical queue index (0-7) to the TM queue key used by tm.counter.queue.

    On some SDE builds, the queue counter key is not a simple 0..7. We prefer
    using `egress_qid_queues` from `tf1.tm.port.cfg` when available.
    """
    if not egress_qids:
        return local_queue
    if 0 <= local_queue < len(egress_qids):
        try:
            return int(egress_qids[local_queue])
        except Exception:
            return local_queue
    return local_queue


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure Tofino1 TM queue shaping and watch counters via bfshell/bfrt_python"
    )
    parser.add_argument(
        "--scope",
        choices=["port", "queue"],
        default="port",
        help="Apply shaping at TM port level (recommended) or TM queue level",
    )
    parser.add_argument("--dev-port", type=int, required=False, default=None)
    parser.add_argument("--queue", type=int, default=0)
    parser.add_argument("--mode", choices=["apply", "reset", "watch"], default="watch")
    parser.add_argument(
        "--all-queues",
        action="store_true",
        help="Watch all 8 queues (0-7) for this port group instead of only --queue",
    )
    parser.add_argument(
        "--clear-counters",
        action="store_true",
        help="Clear TM counters once before watching (if supported by this SDE)",
    )
    parser.add_argument("--max-gbps", type=float, default=None)
    parser.add_argument("--max-mbps", type=float, default=None)
    parser.add_argument("--max-bps", type=int, default=None)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Path to save output log file. If not specified, output goes to stdout only.",
    )
    parser.add_argument(
        "--log-append",
        action="store_true",
        help="Append to log file instead of overwriting (only effective with --log-file)",
    )
    args = parser.parse_args()

    # Initialize global writer for logging
    global _writer
    _writer = TeeWriter(log_file=args.log_file, append=args.log_append)

    dev_port = args.dev_port
    pg_queue = args.queue
    mode = args.mode
    scope = args.scope

    # For reset mode without dev_port, we reset all ports
    if mode == "reset" and dev_port is None:
        _output("Resetting shaping for ALL ports (Pipe 0: 0-127, Pipe 1: 128-255)...")
        
        root = _get_root()
        tf1 = getattr(root, "tf1", globals().get("tf1"))
        if tf1 is None:
            raise RuntimeError("Cannot resolve `tf1` node.")
        
        port_sched_cfg = tf1.tm.port.sched_cfg
        queue_sched_cfg = tf1.tm.queue.sched_cfg
        
        reset_count = 0
        skipped_count = 0
        
        # Instead of scanning all 256 ports and checking each one (which causes error messages),
        # we only reset ports that are known to be valid based on typical Tofino port configurations.
        # Common valid dev_ports: front panel ports are usually in specific ranges.
        # We'll try to reset each port's shaping directly and silently skip failures.
        
        for dp in range(0, 256):
            pipe = dp // 128
            try:
                if hasattr(root, "set_pipe"):
                    root.set_pipe(pipe)
                
                # Try to reset port-level shaping directly (this usually doesn't print errors)
                if scope == "port":
                    try:
                        port_sched_cfg.mod(dev_port=dp, max_rate_enable=False)
                    except Exception:
                        skipped_count += 1
                        continue
                
                # If port-level reset succeeded, try to get pg_id for queue operations
                # Use print_ents=False to suppress output
                try:
                    ent = tf1.tm.port.cfg.get(dev_port=dp, from_hw=True, print_ents=False)
                    data = ent.data
                    pg_id = int(data.get(b"pg_id", -1))
                    egress_qids = list(data.get(b"egress_qid_queues", []))
                except Exception:
                    # Port doesn't exist or not configured
                    if scope == "port":
                        reset_count += 1  # Port shaping was reset successfully above
                    else:
                        skipped_count += 1
                    continue
                
                if pg_id < 0:
                    if scope == "port":
                        reset_count += 1
                    else:
                        skipped_count += 1
                    continue
                
                if scope == "queue":
                    # Reset queue-level shaping for all 8 queues
                    for q in range(8):
                        try:
                            qkey = _map_queue_key(q, egress_qids)
                            queue_sched_cfg.mod(
                                pg_id=pg_id,
                                pg_queue=qkey,
                                # Do NOT touch scheduler configuration (priority/algorithm).
                                # Only disable shaping so we don't override settings from the C control plane.
                                max_rate_enable=False,
                            )
                        except Exception:
                            pass
                
                reset_count += 1
            except Exception:
                skipped_count += 1
                continue
        
        _output(f"Reset completed: {reset_count} ports processed, {skipped_count} ports skipped (inactive)")
        _writer.close()
        return

    # For apply/watch/reset with specific port, dev_port is required
    if dev_port is None:
        raise SystemExit("--dev-port is required for apply/watch mode, or reset with specific port")

    pipe = dev_port // 128

    # Log command line info
    if args.log_file:
        _output(f"# Command: mode={mode}, dev_port={dev_port}, queue={pg_queue}, scope={scope}")

    root = _get_root()
    if hasattr(root, "set_pipe"):
        root.set_pipe(pipe)

    tf1 = getattr(root, "tf1", globals().get("tf1"))
    port = getattr(root, "port", globals().get("port"))
    if tf1 is None or port is None:
        raise RuntimeError("Cannot resolve `tf1`/`port` nodes.")

    pg_id, pg_port_nr, egress_qids = _get_pg_mapping(tf1, dev_port)
    if pg_id < 0:
        raise RuntimeError(f"Failed to resolve pg_id for dev_port={dev_port}")

    eg_port_counter = tf1.tm.counter.eg_port
    queue_counter = tf1.tm.counter.queue
    port_sched_cfg = tf1.tm.port.sched_cfg
    port_sched_shaping = tf1.tm.port.sched_shaping
    queue_sched_cfg = tf1.tm.queue.sched_cfg
    queue_sched_shaping = tf1.tm.queue.sched_shaping
    port_stat = port.port_stat

    if mode == "apply":
        max_bps = args.max_bps
        if max_bps is None:
            if args.max_gbps is not None:
                max_bps = int(args.max_gbps * 1_000_000_000)
            elif args.max_mbps is not None:
                max_bps = int(args.max_mbps * 1_000_000)
        if max_bps is None:
            raise SystemExit("--mode apply requires --max-gbps or --max-mbps or --max-bps")

        max_rate_units = _rate_to_tm_units_bps(max_bps)

        if scope == "port":
            cur_cfg = _entry_raw(port_sched_cfg.get(dev_port=dev_port, from_hw=True, print_ents=False))
            cur_shaping = _entry_raw(
                port_sched_shaping.get(dev_port=dev_port, from_hw=True, print_ents=False)
            )
        else:
            cur_cfg = _entry_raw(queue_sched_cfg.get(pg_id=pg_id, pg_queue=pg_queue, from_hw=True, print_ents=False))
            cur_shaping = _entry_raw(
                queue_sched_shaping.get(pg_id=pg_id, pg_queue=pg_queue, from_hw=True, print_ents=False)
            )

        _output(
            f"Applying shaping scope={scope} on dev_port={dev_port} (pipe={pipe}, pg_id={pg_id}, pg_port_nr={pg_port_nr}) queue={pg_queue}"
        )
        if egress_qids:
            _output(f"Egress qid map (qid for queue 0-7): {egress_qids[:8]}")
        _output(f"Target max_rate: {max_bps} bps (tm units={max_rate_units})")
        _output(f"Current sched_cfg: {cur_cfg}")
        _output(f"Current sched_shaping: {cur_shaping}")

        if scope == "port":
            port_sched_cfg.mod(dev_port=dev_port, max_rate_enable=True)
            port_sched_shaping.mod(
                dev_port=dev_port,
                unit="BPS",
                provisioning="UPPER",
                max_rate=max_rate_units,
            )
        else:
            queue_sched_cfg.mod(
                pg_id=pg_id,
                pg_queue=pg_queue,
                # Do NOT touch scheduler configuration (priority/algorithm).
                # Only enable shaping so we don't override settings from the C control plane.
                max_rate_enable=True,
            )
            queue_sched_shaping.mod(
                pg_id=pg_id,
                pg_queue=pg_queue,
                unit="BPS",
                provisioning="UPPER",
                max_rate=max_rate_units,
            )

        if scope == "port":
            new_cfg = _entry_raw(port_sched_cfg.get(dev_port=dev_port, from_hw=True, print_ents=False))
            new_shaping = _entry_raw(
                port_sched_shaping.get(dev_port=dev_port, from_hw=True, print_ents=False)
            )
        else:
            new_cfg = _entry_raw(queue_sched_cfg.get(pg_id=pg_id, pg_queue=pg_queue, from_hw=True, print_ents=False))
            new_shaping = _entry_raw(
                queue_sched_shaping.get(pg_id=pg_id, pg_queue=pg_queue, from_hw=True, print_ents=False)
            )
        _output(f"New sched_cfg: {new_cfg}")
        _output(f"New sched_shaping: {new_shaping}")
        _writer.close()
        return

    if mode == "reset":
        _output(
            f"Resetting shaping scope={scope} on dev_port={dev_port} (pipe={pipe}, pg_id={pg_id}, pg_port_nr={pg_port_nr}) queue={pg_queue}"
        )
        
        if scope == "port":
            port_sched_cfg.mod(dev_port=dev_port, max_rate_enable=False)
            new_cfg = _entry_raw(port_sched_cfg.get(dev_port=dev_port, from_hw=True, print_ents=False))
        else:
            qkey = _map_queue_key(pg_queue, egress_qids)
            queue_sched_cfg.mod(
                pg_id=pg_id,
                pg_queue=qkey,
                # Do NOT touch scheduler configuration (priority/algorithm).
                # Only disable shaping so we don't override settings from the C control plane.
                max_rate_enable=False,
            )
            new_cfg = _entry_raw(queue_sched_cfg.get(pg_id=pg_id, pg_queue=qkey, from_hw=True, print_ents=False))
        
        _output(f"New sched_cfg: {new_cfg}")
        _writer.close()
        return

    interval = args.interval
    duration = args.duration
    iterations = args.iterations
    # If duration and iterations are None, run indefinitely (Ctrl+C to stop)

    if args.clear_counters:
        clear_fn = getattr(tf1.tm.counter, "clear", None)
        if callable(clear_fn):
            clear_fn()
            time.sleep(0.1)

    if args.all_queues:
        # Print mapping once to avoid confusion about queue counter keys.
        if egress_qids:
            mapped = [_map_queue_key(i, egress_qids) for i in range(8)]
            _output(f"# egress_qid_queues (logical 0-7 -> tm key): {mapped}")
        _output(
            "time	dev_port	"
            "egress_drop	d_egress_drop	egress_usage	egress_wm	"
            "rx_rate	tx_rate	"
            "q_drop[0-7]	d_q_drop[0-7]	sum_d_q_drop	d_unattributed	"
            "q_usage[0-7]	q_wm[0-7]"
        )
    else:
        _output(
            "time	dev_port	queue	"
            "egress_drop	d_egress_drop	egress_usage	egress_wm	"
            "queue_drop	d_queue_drop	queue_usage	queue_wm	"
            "rx_rate	tx_rate"
        )

    start = time.time()
    i = 0
    prev_eg_drop: int | None = None
    prev_q_drops: list[int] | None = None
    while True:
        now = time.time()
        if duration is not None and (now - start) >= duration:
            break
        if iterations is not None and i >= iterations:
            break

        eg = _get_counter(eg_port_counter, dev_port=dev_port)
        ps = _get_port_stat(port_stat, dev_port)

        eg_drop = eg.get("drop_count_packets", 0)
        d_eg_drop = 0 if prev_eg_drop is None else max(0, eg_drop - prev_eg_drop)
        prev_eg_drop = eg_drop

        if args.all_queues:
            q_drops: list[int] = []
            q_usage: list[int] = []
            q_wm: list[int] = []
            for qid in range(8):
                qkey = _map_queue_key(qid, egress_qids)
                q = _get_counter(queue_counter, pg_id=pg_id, pg_queue=qkey)
                q_drops.append(q.get("drop_count_packets", 0))
                q_usage.append(q.get("usage_cells", 0))
                q_wm.append(q.get("watermark_cells", 0))

            if prev_q_drops is None:
                d_q_drops = [0] * 8
            else:
                d_q_drops = [max(0, a - b) for a, b in zip(q_drops, prev_q_drops)]
            prev_q_drops = q_drops[:]

            sum_d_q = int(sum(d_q_drops))
            d_unattributed = max(0, int(d_eg_drop) - sum_d_q)

            _output(
                f"{now:.3f}	{dev_port}	"
                f"{eg_drop}	{d_eg_drop}	{eg.get('usage_cells', 0)}	{eg.get('watermark_cells', 0)}	"
                f"{ps.get('$RX_RATE', 0)}	{ps.get('$TX_RATE', 0)}	"
                f"[{','.join(str(x) for x in q_drops)}]	"
                f"[{','.join(str(x) for x in d_q_drops)}]	"
                f"{sum_d_q}	{d_unattributed}	"
                f"[{','.join(str(x) for x in q_usage)}]	"
                f"[{','.join(str(x) for x in q_wm)}]"
            )
        else:
            qkey = _map_queue_key(pg_queue, egress_qids)
            q = _get_counter(queue_counter, pg_id=pg_id, pg_queue=qkey)
            q_drop = q.get("drop_count_packets", 0)
            d_q_drop = 0
            if prev_q_drops is None:
                prev_q_drops = [q_drop]
            else:
                d_q_drop = max(0, q_drop - prev_q_drops[0])
                prev_q_drops = [q_drop]
            _output(
                f"{now:.3f}	{dev_port}	{pg_queue}	"
                f"{eg_drop}	{d_eg_drop}	{eg.get('usage_cells', 0)}	{eg.get('watermark_cells', 0)}	"
                f"{q_drop}	{d_q_drop}	{q.get('usage_cells', 0)}	{q.get('watermark_cells', 0)}	"
                f"{ps.get('$RX_RATE', 0)}	{ps.get('$TX_RATE', 0)}"
            )

        i += 1
        time.sleep(interval)

    # Close log file when watch loop ends
    _writer.close()


main()
