#!/usr/bin/env python3
"""Drive code-impact-mcp via JSON-RPC. Usage: python3 drive_code_impact.py <repo_root> <rel_file>"""
import json, subprocess, sys, time

NODE_MODULES = "/tmp/opencode/compare/node_modules"

def rpc(proc, method, params, req_id=1):
    msg = json.dumps({"jsonrpc":"2.0","id":req_id,"method":method,"params":params})
    proc.stdin.write(msg+"\n"); proc.stdin.flush()
    deadline = time.time()+60
    while time.time()<deadline:
        line=proc.stdout.readline()
        if not line: time.sleep(0.05); continue
        try:
            resp=json.loads(line)
            if resp.get("id")==req_id: return resp
        except: pass
    return {"error":"timeout"}

def query(repo_root, rel_file):
    proc = subprocess.Popen(
        ["node", f"{NODE_MODULES}/@vk0/code-impact-mcp/dist/cli.js"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=repo_root)
    rpc(proc,"initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"bench","version":"1"}},req_id=0)
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"})+"\n"); proc.stdin.flush()
    refresh = rpc(proc,"tools/call",{"name":"refresh_graph","arguments":{"projectRoot":repo_root}},req_id=1)
    deps = rpc(proc,"tools/call",{"name":"get_dependencies","arguments":{"projectRoot":repo_root,"file":rel_file}},req_id=2)
    impact = rpc(proc,"tools/call",{"name":"analyze_impact","arguments":{"projectRoot":repo_root,"files":[rel_file]}},req_id=3)
    proc.stdin.close()
    try: proc.wait(timeout=10)
    except: proc.kill()
    return {"tool":"code-impact-mcp","version":"1.6.10","repo_root":repo_root,"file":rel_file,
            "refresh":refresh,"get_dependencies":deps,"analyze_impact":impact,"stderr":proc.stderr.read()[:500]}

if __name__ == "__main__":
    print(json.dumps(query(sys.argv[1], sys.argv[2]), indent=2))
