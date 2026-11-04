"""Functional profile checks, separate from E1-E8; run inside the SDN container."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.common import db
from src.common.models import IntentRecord
from src.enforcement.flowmod import cookie_for_intent
from src.intent_manager.profiles import build_intent, list_profiles
from src.pathing.compute import compute_path
from topology.topology_spec import build_graph

ROOT = Path(__file__).resolve().parents[2]


def http(path, data=None, port=8000):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, json.load(response)


def wait_until(check, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Timed out waiting for profile check readiness")


def check_profile(profile):
    name = profile["service_class"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "docs/demo_assets" / f"profile_{name}_{stamp}"
    output.mkdir(parents=True, exist_ok=False)
    transcript = (output / "output.txt").open("w", encoding="utf-8")
    record = {"service_class": name, "captured_utc": stamp, "kind": "functional, not E1-E8",
              "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in (Path(__file__), ROOT / "src/intent_manager/profiles.yaml",
                                             ROOT / "src/intent_manager/api.py")}}
    processes, handles = [], []
    net = None
    conn = None
    server = None

    def emit(label, value):
        text = f"{label}: {json.dumps(value)}\n"
        print(text, end="", flush=True)
        transcript.write(text)
        transcript.flush()

    with tempfile.TemporaryDirectory(prefix=f"team16-profile-{name}-") as temporary:
        environment = dict(os.environ, TEAM16_DB_PATH=f"{temporary}/state.db")

        def start(label, argv):
            handle = (output / f"{label}.txt").open("w", encoding="utf-8")
            handles.append(handle)
            emit("start argv", argv)
            process = subprocess.Popen(argv, env=environment, stdout=handle, stderr=subprocess.STDOUT)
            processes.append(process)

        try:
            conn = db.connect(Path(environment["TEAM16_DB_PATH"]))
            db.init_db(conn)
            document = json.loads(json.dumps(build_intent(
                name, "INT-920", f"live-{name.replace('_', '-')}",
                {"src": "10.0.0.1/32", "dst": "10.0.0.2/32",
                 "proto": "tcp" if name == "mmtc" else "udp",
                 "dport": 1883 if name == "mmtc" else 5001})))
            model_plan, _ = compute_path(IntentRecord.from_document(document), build_graph())
            if model_plan is not None:
                from mininet.net import Mininet
                from mininet.node import OVSSwitch, RemoteController
                from mininet.link import TCLink
                from topology.team16_topo import Team16Topo
                bridges = subprocess.check_output(["ovs-vsctl", "list-br"], text=True).strip()
                if bridges:
                    raise RuntimeError(f"Refusing to disturb existing bridges: {bridges}")
                start("ryu", ["ryu-manager", "--ofp-tcp-listen-port", "6653", "src/enforcement/controller.py"])
                net = Mininet(topo=Team16Topo(), switch=OVSSwitch, link=TCLink,
                              controller=None, autoSetMacs=True, autoStaticArp=True)
                net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
                net.start()
            start("api", ["python3.9", "-m", "uvicorn", "src.intent_manager.api:app",
                          "--host", "127.0.0.1", "--port", "8000"])
            wait_until(lambda: http("/profiles"))
            intent = document["intent"]
            parameters = {"service_class": name, "intent_id": intent["id"],
                          "tenant": intent["tenant"], "match": intent["match"]}
            emit("POST /intent/from-profile request", parameters)
            status, decision = http("/intent/from-profile", parameters)
            emit("HTTP response", {"status": status, "body": decision})
            record.update(http_status=status, decision=decision)
            if model_plan is None:
                assert decision["state"] == "rejected", decision
                assert "max_latency_ms" in decision["reasons"]["admission"]
                record["outcome"] = "explained refusal"
            else:
                assert decision["state"] == "admitted", decision
                wait_until(lambda: db.load_intent(conn, intent["id"]).state.value == "active")
                plan = db.current_path(conn, intent["id"])
                assert list(plan.switches) == decision["switches"]
                cookie = f"cookie=0x{cookie_for_intent(intent['id']):x}"
                for switch in plan.switches:
                    argv = ["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", switch]
                    flows = subprocess.check_output(argv, text=True)
                    emit("flow dump", {"argv": argv, "stdout": flows})
                    assert sum(cookie in line and "priority=100" in line for line in flows.splitlines()) == 2
                    if profile["min_bandwidth_mbps"] is not None and switch != plan.switches[-1]:
                        assert "set_queue:1" in flows
                tcp = name == "mmtc"
                kind = "SOCK_STREAM" if tcp else "SOCK_DGRAM"
                port = intent["match"]["dport"]
                server_code = (f"import socket; s=socket.socket(socket.AF_INET,socket.{kind});"
                               f"s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('0.0.0.0',{port}));")
                server_code += ("s.listen(1); c,a=s.accept();c.sendall(c.recv(128));c.close()" if tcp
                                else "data,a=s.recvfrom(128);s.sendto(data,a)")
                server = net.get("h2").popen(["python3.9", "-c", server_code])
                time.sleep(0.3)
                client_code = (f"import socket;s=socket.socket(socket.AF_INET,socket.{kind});s.settimeout(5);"
                               f"s.connect(('10.0.0.2',{port}));s.send(b'profile-check');"
                               "assert s.recv(128)==b'profile-check';print('matching packet echo succeeded')")
                client = net.get("h1").popen(["python3.9", "-c", client_code], stdout=subprocess.PIPE,
                                              stderr=subprocess.STDOUT, text=True)
                text, _ = client.communicate(timeout=10)
                emit("matching traffic", {"argv": shlex.join(["python3.9", "-c", client_code]),
                                           "exit_status": client.returncode, "stdout": text})
                assert client.returncode == 0, text
                start("dashboard", ["python3.9", "-m", "uvicorn", "src.dashboard.app:app",
                                    "--host", "127.0.0.1", "--port", "8081"])
                _, detail = wait_until(lambda: http(f"/api/intents/{intent['id']}", port=8081))
                assert detail["path"]["switches"] == decision["switches"]
                assert detail["telemetry_source"] == "none"
                emit("dashboard detail", detail)
                record.update(outcome="installed and matching packets forwarded", path=decision["switches"],
                              dashboard_source=detail["telemetry_source"])
            record["passed"] = True
            emit("PASS", record["outcome"])
        except Exception as exc:
            record.update(passed=False, error=repr(exc))
            emit("FAIL", record["error"])
            raise
        finally:
            if server is not None and server.poll() is None:
                server.terminate()
                server.wait(timeout=5)
            if net is not None:
                net.stop()
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if conn is not None:
                conn.close()
            for handle in handles:
                handle.close()
            transcript.close()
            (output / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def main():
    os.chdir(ROOT)
    for profile in list_profiles():
        check_profile(profile)
    print("All profile functional checks passed; E1-E8 were not rerun.")


if __name__ == "__main__":
    main()
