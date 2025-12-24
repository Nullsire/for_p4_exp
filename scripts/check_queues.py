import time


def main():
    pipe = 1
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
    
    print(f"Scanning tf1.tm.counter.eg_port for Pipe {pipe} (ports {pipe_start}-{pipe_end-1})...")
    print("Dev_Port\tDrop_Pkts\tUsage_Cells\tWatermark_Cells")
    
    found_ports = 0
    
    # Note: Error messages from invalid ports are filtered by the shell script
    for dp in range(pipe_start, pipe_end):
        try:
            ent = tf1.tm.counter.eg_port.get(dev_port=dp, from_hw=True, print_ents=False)
            data = ent.data
            drops = data.get(b'drop_count_packets') or data.get('drop_count_packets') or 0
            usage = data.get(b'usage_cells') or data.get('usage_cells') or 0
            wm = data.get(b'watermark_cells') or data.get('watermark_cells') or 0
            
            found_ports += 1
            if drops > 0 or usage > 0 or wm > 0:
                print(f"{dp}\t{drops}\t{usage}\t{wm}")
        except Exception:
            pass
    
    print(f"\n# Scanned {found_ports} valid ports in Pipe {pipe}")


main()
