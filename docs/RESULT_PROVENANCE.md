# Evaluation Result Provenance

This file separates historical measurements from results produced by the current code. Raw CSV files are immutable; corrected runs use new filename prefixes.

## Code chronology

| Result family | First result commit | Controller concurrent-dispatch fix (`7dcb083`) present? | Runtime persisted-dwell fix (`1b5a4f5`) present? | Status |
|---|---:|:---:|:---:|---|
| O1 B2/B3 latency | `e20738f` | No | No | Historical; retained |
| O2 E4 loss/reordering | `c6372c6` | No | No | Historical; current-code rerun available |
| O3 queue binding | `f8dc4d7` | No | No | Historical; queue-capacity rerun available |
| O4 E5 flow-table | `7dcb083` | Yes | No | Historical mixed-version result |
| O5 E6 oscillation | `1b5a4f5` | Yes | Yes | Current implementation, initially n=3 |
| O6 E1 violation duration | `7913f07` | Yes | Yes | Current implementation |
| O7 E7 admission scaling | `de7ec2a` | Yes | Yes | Current implementation |
| O8 E8 overhead | `c06435a` | Yes | Yes | Current implementation; CPU superseded by E8v2 |

## Current-code reruns

- `b3_current_closed_loop_*.csv` (n=10): detection mean 2115.940 ms, 95% CI [2108.734, 2123.145]; recovery mean 537.853 ms, 95% CI [446.416, 629.289]. These are the primary B3 latency results after both fixes.
- `e4current_b2_reconfig_*.csv` and `e4current_b3_reconfig_*.csv` (n=10 each): B2 loses 41.000 packets on average, 95% CI [39.455, 42.545]; B3 loses 0 and reorders 28. These supersede the historical E4 headline values where current-code behavior is required.
- `o3current_queue_bound_*.csv` (n=10): the intent obtains approximately 24.995 Mbit/s with zero loss using topology-derived queue ceilings.
- `e8v2_overhead_*.csv` (n=10 per mode): full-stack CPU supersedes the original Ryu-only CPU field.

Historical measurements remain valid evidence of the code revision that produced them, but must not be presented as current-code measurements without this qualification.
