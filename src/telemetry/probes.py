"""Active probe parsing that remains testable without Mininet or root."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from src.common.models import Measurement


def parse_ping(text: str) -> Tuple[Optional[float], float]:
    """Return average round-trip delay in milliseconds and packet loss percent."""
    loss_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s+packet loss", text)
    loss = float(loss_match.group(1)) if loss_match else 100.0
    rtt_match = re.search(
        r"(?:rtt|round-trip) min/avg/max/(?:mdev|stddev) = "
        r"[0-9.]+/([0-9.]+)/[0-9.]+/[0-9.]+",
        text,
    )
    delay = float(rtt_match.group(1)) if rtt_match else None
    return delay, loss


class ActiveProbeSource:
    """Convert real ping output into timestamped SLA measurements."""

    def __init__(self) -> None:
        self._delays: Dict[str, List[float]] = defaultdict(list)

    def measurement(self, intent_id: str, at: float, ping_output: str) -> Measurement:
        """Build one measurement and derive jitter from consecutive probe delays."""
        delay, loss = parse_ping(ping_output)
        return self.observation(intent_id, at, delay, loss)

    def observation(
        self, intent_id: str, at: float, delay: Optional[float], loss: float
    ) -> Measurement:
        """Build a sample from an active probe's measured delay and loss."""
        jitter = None
        if delay is not None:
            history = self._delays[intent_id]
            if history:
                jitter = abs(delay - history[-1])
            history.append(delay)
        return Measurement(intent_id, float(at), delay, jitter, float(loss))
