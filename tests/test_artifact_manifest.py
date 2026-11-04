"""Protect portable result integrity across Windows and Linux checkouts."""
from experiments.artifact_manifest import artifact_digest


def test_line_endings_do_not_invalidate_the_same_measurements(tmp_path):
    """Windows checkout conversion must not falsely label retained results corrupt."""
    windows = tmp_path / "windows.csv"
    linux = tmp_path / "linux.csv"
    windows.write_bytes(b"metric,value\r\nthroughput,20\r\n")
    linux.write_bytes(b"metric,value\nthroughput,20\n")
    assert artifact_digest(windows) == artifact_digest(linux)
    linux.write_bytes(b"metric,value\nthroughput,21\n")
    assert artifact_digest(windows) != artifact_digest(linux)


def test_binary_figures_are_never_text_normalized(tmp_path):
    """Changing figure bytes must be detected even when they resemble line endings."""
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\n")
    second.write_bytes(b"\x89PNG\n\x1a\n")
    assert artifact_digest(first) != artifact_digest(second)
