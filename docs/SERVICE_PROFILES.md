# Standards-derived service profiles

Profiles generate ordinary project intents without changing the frozen grammar.
They are not 5G QoS-flow implementations or compliance certificates. A 5QI defines
QoS characteristics; it is not a slice type. Application mappings are project policy.

## Pinned sources

- [S1: ETSI TS 123 501 V17.9.0 (2023-07), TS 23.501 Release 17](https://www.etsi.org/deliver/etsi_ts/123500_123599/123501/17.09.00_60/ts_123501v170900p.pdf): clauses 5.7.3.4/5.7.3.5, Table 5.7.4-1, printed pages 170-174. Used rows occur on PDF pages 172-173; Notes 4/5/13 on PDF pages 174-175.
- [S2: ETSI TS 122 261 V17.10.0 (2022-05), TS 22.261 Release 17](https://www.etsi.org/deliver/etsi_ts/122200_122299/122261/17.10.00_60/ts_122261v171000p.pdf): Tables 7.1-1 and 7.2.3.2-1.
- [S3: ITU-R M.2410-0 (11/2017)](https://www.itu.int/dms_pub/itu-r/opb/rep/R-REP-M.2410-2017-PDF-E.pdf): clauses 4.7.1, 4.8, 4.10.

These are pinned extraction versions, not the newest releases. For example,
[Release 18 exists](https://www.etsi.org/deliver/etsi_TS/123500_123599/123501/18.05.00_60/ts_123501v180500p.pdf).
Values were checked against the local PDFs in ignored `docs/specs/`; never commit
those PDFs. Source metadata remains outside the frozen intent document.

## Verified characteristics

All rows are from S1 Table 5.7.4-1. PDB and CN PDB are one-way milliseconds; PER
is a probability. 3GPP priority is separate from the project's 1-5 priority scale.

| 5QI | Resource type | 3GPP priority | PDB ms | CN PDB ms / note | PER | MDBV bytes / example |
|---|---|---|---|---|---|---|
| 82 | Delay-critical GBR | 19 | 10 | 1 / 4 | 0.0001 | 255 / discrete automation |
| 85 | Delay-critical GBR | 21 | 5 | 2 / 5 | 0.00001 | 255 / high-voltage distribution |
| 86 | Delay-critical GBR | 18 | 5 | 2 / 5 | 0.0001 | 1354 / advanced-driving V2X |
| 2 | GBR | 40 | 150 | 20 / 13 | 0.001 | N/A / conversational live video |
| 3 | GBR | 30 | 50 | 20 / 13 | 0.001 | N/A / medium-voltage distribution, process monitoring |
| 9 | Non-GBR | 90 | 300 | 20 / 13 | 0.000001 | N/A / buffered video and TCP traffic |

## Application mappings

- `urllc`: 5QI 82 is a **proxy mapping for remote surgery**. Release 17 has no
  dedicated remote-surgery 5QI in this table. The actual example is discrete
  automation; this proxy establishes no clinical requirement or guarantee.
  `demo_011_remote_surgery.yaml` retains illustrative values.
- `v2x`: 5QI 86 references collision avoidance and platooning with high automation.
- `smart_grid`: 5QI 85 references **high-voltage protection**, a delay-critical
  class, not mMTC. 5QI 3 is a separate medium-voltage/monitoring reference.
  `demo_013_smart_grid.yaml` retains illustrative values.
- `embb`: 5QI 2 supplies a conversational/live-video reference, not a definition
  of every eMBB service.
- `mmtc`: exactly 5QI 9, **project choice: no dedicated massive-IoT 5QI in TS
  23.501 Release 17**. Non-GBR fits this example of delay-tolerant buffered/TCP
  sensor traffic. It is not appropriate for every IoT application, and this
  profile requests no minimum bandwidth.

## Distinctions and limitations

S2 Table 7.2.3.2-1 describes wireless ITS road-side **infrastructure backhaul**:
30 ms maximum end-to-end latency, 100 ms survival time, 99.9999% availability,
99.999% reliability and 10 Mbit/s. Note 7 identifies example values. These are not
collision-avoidance requirements; reliability and availability are not PER.

S2 Table 7.1-1 gives experienced downlink targets of 50 Mbit/s for urban/rural
macro and 300 Mbit/s for dense urban, and uplink targets of 25-50 Mbit/s. Note 5
identifies targets, not strict requirements. Note 3's interactive audio/video
example gives 2-4 ms two-way end-to-end latency and up to 300 Mbit/s for 8K 3D
video. These are not universal telemedicine requirements.

S3's 4 ms eMBB and 1 ms URLLC user-plane latency concern the **radio interface**,
unloaded and with small packets. Clause 4.10 concerns success probability
1 - 0.00001 for a 32-byte layer-2 PDU within 1 ms. Clause 4.8 gives 1,000,000
devices/km2. These are context only, not inputs to transport budgets or measured
achievements of this prototype.

S1 PER concerns non-congestion link-layer errors, not IP probe loss. Table Note 1
excludes late packets from PER for the applicable ordinary GBR/non-GBR rows;
delay-critical GBR has distinct delay/error handling in clause 5.7.3.5.
Multiplying PER by 100 converts probability to percent but does not equate these
metrics. Generated loss bounds are explicitly project proxies. Planning and PDB
are one-way; live echo probes measure RTT. Profiles do not hide or fix that gap.
