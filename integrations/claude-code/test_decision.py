import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buddy_bridge as bb
import hook


class FakeSerial:
    def __init__(self, decision, echo=True):
        self.decision = decision
        self.echo = echo
        self.buf = b""
        self.writes = []

    def write(self, b):
        self.writes.append(b)
        try:
            obj = json.loads(b.decode().strip())
            if self.echo and "prompt" in obj:
                rid = obj["prompt"]["id"]
                self.buf += (json.dumps(
                    {"cmd": "permission", "id": rid, "decision": self.decision}
                ) + "\n").encode()
        except Exception:
            pass

    def flush(self):
        pass

    def read(self, n):
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def close(self):
        pass


def run(decision):
    fake = FakeSerial(decision)
    bb.open_port = lambda *a, **k: fake
    out = []
    hook._emit = lambda o: out.append(o)
    hook.handle_permission_request(
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/x"}})
    sent = [json.loads(w.decode()) for w in fake.writes]
    prompt_sent = any("prompt" in s for s in sent)
    cleared = any(s.get("waiting") == 0 for s in sent)
    behavior = out[0]["hookSpecificOutput"]["decision"]["behavior"] if out else None
    print("decision=%-5s -> behavior=%-5s prompt_sent=%s cleared=%s"
          % (decision, behavior, prompt_sent, cleared))


run("once")
run("deny")

fake = FakeSerial("once", echo=False)  # device never answers
bb.open_port = lambda *a, **k: fake
out = []
hook._emit = lambda o: out.append(o)
hook.DECISION_TIMEOUT_S = 0.3
hook.handle_permission_request(
    {"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}})
print("timeout      -> emitted=%s (should be [])" % out)
