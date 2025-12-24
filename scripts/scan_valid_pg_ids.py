def main():
    pipe = 1
    root = globals().get("bfrt") or globals().get("simple_forward")
    if hasattr(root, "set_pipe"):
        root.set_pipe(pipe)
    tf1 = getattr(root, "tf1", globals().get("tf1"))
    
    print(f"Scanning valid pg_ids in Pipe {pipe}...")
    for pg_id in range(128):
        try:
            # Try to read queue 0
            ent = tf1.tm.counter.queue.get(pg_id=pg_id, pg_queue=0, from_hw=True, print_ents=False)
            print(f"pg_id {pg_id}: VALID")
        except Exception:
            pass

main()
