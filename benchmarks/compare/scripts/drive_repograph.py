#!/usr/bin/env python3
"""Query repograph impact for a file. Usage: python3 drive_repograph.py <repo_root> <rel_file>"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, "/home/darion-dev/repograph/src")
from repograph.config import load_settings
from repograph.impact import analyze_impact
from repograph.store import Store

def query_repograph(repo_root, rel_file):
    root = Path(repo_root)
    with Store(load_settings(root)) as store:
        t0 = time.perf_counter()
        result = analyze_impact(store, root, paths=[rel_file], depth=3, include_tests=True)
        result["_query_time_ms"] = round((time.perf_counter()-t0)*1000, 1)
    return result

if __name__ == "__main__":
    print(json.dumps(query_repograph(sys.argv[1], sys.argv[2]), indent=2))
