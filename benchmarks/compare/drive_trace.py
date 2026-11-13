#!/usr/bin/env python3
"""Drive trace-mcp via JSON-RPC with correct parameter names."""
import json, os, subprocess, sys, time, select

NODE22 = "/home/darion-dev/.config/nvm/versions/node/v22.23.5/bin/node"

def query_trace(repo_root, rel_file):
    env = os.environ.copy()
    env["TRACE_MCP_NO_DAEMON"] = "1"
    env["TRACE_MCP_TELEMETRY"] = "off"
    proc = subprocess.Popen(
        [NODE22, "/tmp/opencode/compare/node_modules/trace-mcp/dist/cli.js"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=repo_root, env=env,
    )
    time.sleep(6)
    if proc.poll() is not None:
        return {"error": f"crash on startup (exit {proc.returncode})",
                "stderr": proc.stderr.read()[:500]}

    def send(d):
        try: proc.stdin.write(json.dumps(d)+"\n"); proc.stdin.flush()
        except BrokenPipeError: pass

    def recv(req_id, timeout=45):
        deadline = time.time()+timeout
        while time.time()<deadline:
            if proc.poll() is not None: return {"error":f"exit {proc.returncode}"}
            r,_,_ = select.select([proc.stdout],[],[],0.5)
            if r:
                line=proc.stdout.readline()
                if not line: continue
                try:
                    resp=json.loads(line)
                    if isinstance(resp,dict) and resp.get("id")==req_id: return resp
                except: pass
        return {"error":"timeout"}

    send({"jsonrpc":"2.0","id":0,"method":"initialize",
          "params":{"protocolVersion":"2024-11-05","capabilities":{},
                    "clientInfo":{"name":"bench","version":"1.0"}}})
    init=recv(0,15)
    if "error" in init:
        return {"error":init["error"],"stderr":proc.stderr.read()[:500]}
    send({"jsonrpc":"2.0","method":"notifications/initialized"})

    send({"jsonrpc":"2.0","id":1,"method":"tools/call",
          "params":{"name":"get_change_impact","arguments":{"file_path":rel_file,"depth":3}}})
    impact=recv(1,45)

    send({"jsonrpc":"2.0","id":2,"method":"tools/call",
          "params":{"name":"find_usages","arguments":{"file_path":rel_file,"limit":200}}})
    usage=recv(2,45)

    try: proc.stdin.close()
    except: pass
    try: proc.wait(timeout=10)
    except subprocess.TimeoutExpired: proc.kill()
    stderr=proc.stderr.read()

    return {"tool":"trace-mcp","version":"3.44.0","repo_root":repo_root,"file":rel_file,
            "get_change_impact":impact,"find_usages":usage,"stderr":stderr[:500]}

if __name__=="__main__":
    r=query_trace(sys.argv[1],sys.argv[2])
    print(json.dumps(r,indent=2))
