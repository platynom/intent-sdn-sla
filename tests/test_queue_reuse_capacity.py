"""Verify that reused QoS records keep the actual egress-link ceiling."""
from types import SimpleNamespace

from src.enforcement import queues


def test_reused_qos_root_ceiling_is_refreshed_from_topology(monkeypatch):
    """A stale root ceiling can invalidate bandwidth admission after port reuse."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout="existing-qos\n" if "get" in argv else "")

    monkeypatch.setattr(queues.subprocess, "run", fake_run)
    queues.ensure_queue("s1", "s1-eth4", 20, egress_peer="s6")
    update = next(argv for argv in calls if "set" in argv and "qos" in argv)
    qos_index = update.index("qos")
    root_fields = update[qos_index + 2:update.index("--", qos_index)]
    assert "other-config:max-rate=40000000" in root_fields
    assert not any("create" in argv and "qos" in argv[argv.index("create"):] for argv in calls)
