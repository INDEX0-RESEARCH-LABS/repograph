#!/usr/bin/env python3
"""Run all three tools on all selected files. Save raw output to benchmarks/compare/raw/."""
import json, os, subprocess, sys, time
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
SELECTED = json.loads((Path(__file__).parent.parent / "selected_files.json").read_text())
REPOS = {"django":"/tmp/opencode/compare/repos/django","esbuild":"/tmp/opencode/compare/repos/esbuild","koa":"/tmp/opencode/compare/repos/koa"}
SCRIPTS = {"repograph": str(Path(__file__).parent/"drive_repograph.py"),
           "code_impact": str(Path(__file__).parent/"drive_code_impact.py"),
           "trace": str(Path(__file__).parent/"drive_trace.py")}

def run_script(script, repo_root, rel_file, timeout=120):
    t0 = time.perf_counter()
    try:
        r = subprocess.run([sys.executable, script, repo_root, rel_file],
                          capture_output=True, text=True, timeout=timeout)
        d = json.loads(r.stdout) if r.stdout.strip() else {"error":f"exit {r.returncode}","stderr":r.stderr[:200]}
        d["_meta"] = {"repo":repo_root.split("/")[-1],"file":rel_file,"tool":script.split("/")[-1].replace("drive_","").replace(".py",""),"wall_s":round(time.perf_counter()-t0,1)}
        return d
    except subprocess.TimeoutExpired: return {"error":f"timeout>{timeout}s"}
    except Exception as e: return {"error":str(e)}

done=0; total=sum(len(v) for v in SELECTED.values())
for repo, files in SELECTED.items():
    for rel_file in files:
        done+=1; safe=rel_file.replace("/","__")
        print(f"[{done}/{total}] {repo}/{rel_file}")
        for tool, script in SCRIPTS.items():
            out_path = RAW_DIR/f"{repo}__{safe}__{tool}.json"
            if out_path.exists(): print(f"  {tool}: skip"); continue
            result = run_script(script, REPOS[repo], rel_file, timeout=90 if tool=="trace" else 60)
            out_path.write_text(json.dumps(result, indent=2))
            status = "ERROR" if "error" in result else "ok"
            print(f"  {tool}: {status} ({result.get('_meta',{}).get('wall_s',0):.1f}s)")
print(f"\nDone. Raw outputs in {RAW_DIR}")
