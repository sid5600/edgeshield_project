# EdgeShield — Edge Caching Proxy + DNS Engine

A Computer Networks case-study project demonstrating how an **edge proxy cache** and a **custom DNS resolver** reduce access-link traffic and response latency for an institutional LAN.

---

## Table of Contents
1. [What is EdgeShield?](#1-what-is-edgeshield)
2. [Architecture Overview](#2-architecture-overview)
3. [File Structure](#3-file-structure)
4. [How Each Component Works](#4-how-each-component-works)
5. [Quick Start](#5-quick-start)
6. [Running the Full Experiment](#6-running-the-full-experiment)
7. [Throttling the Link (Linux)](#7-throttling-the-link-linux)
8. [Understanding the Results](#8-understanding-the-results)
9. [Networking Theory Behind It](#9-networking-theory-behind-it)
10. [Limitations](#10-limitations)

---

## 1. What is EdgeShield?

EdgeShield sits at the **edge of an institutional LAN** (e.g. a university campus) between internal clients and the shared internet access link.

```
  [Client Browser]
        |
        |  (LAN — 100 Mbps, fast)
        |
  ┌─────────────────────┐
  │   EdgeShield Edge   │
  │                     │
  │  ┌───────────────┐  │
  │  │ DNS Resolver  │  │  ← port 5300 UDP
  │  └───────────────┘  │
  │  ┌───────────────┐  │
  │  │  HTTP Proxy   │  │  ← port 8888 TCP
  │  └───────────────┘  │
  └─────────────────────┘
        |
        |  (Access Link — 15 Mbps, bottleneck)
        |
  [Internet / Origin Servers]
```

**The core idea:** The access link is the bottleneck. Every byte saved there reduces queuing delay for everyone on the LAN. EdgeShield saves bytes two ways:
- The **proxy** serves repeat HTTP requests from local disk — no WAN fetch.
- The **DNS resolver** answers local names instantly and blocks ad domains — no query crosses the WAN for those.

---

## 2. Architecture Overview

```
Client Request
    │
    ▼
DNS Resolver (UDP :5300)
    ├── SINKHOLE  → return 0.0.0.0 immediately (ad/tracker domains)
    ├── LOCAL     → return IP from static zone (*.lan names)
    ├── CACHE     → return cached upstream answer (TTL not expired)
    └── UPSTREAM  → forward to 1.1.1.1:53, cache the reply by TTL

HTTP Proxy (TCP :8888)
    ├── PURE CACHE HIT  → serve from disk, 0 WAN bytes (< 30 s old)
    ├── CONDITIONAL GET → send If-Modified-Since; if 304, serve from disk
    └── CACHE MISS      → full fetch from origin, save to ./edge_storage
```

> The DNS resolver and proxy are **independent services** — not integrated. The proxy uses the OS resolver.

---

## 3. File Structure

```
edgeshield_project/
│
├── edgeshield_proxy.py      # Partner A — TCP HTTP caching proxy (DO NOT EDIT)
├── dns_resolver.py          # Partner B — UDP DNS engine with 4 resolution paths
├── benchmark.py             # Partner B — measures HTTP and DNS latency, writes CSVs
├── plot_results.py          # Partner B — generates 3 PNG figures from the CSVs
│
├── edge_storage/            # Proxy cache directory (auto-created)
│   ├── example.com.cache    # Cached HTTP response body
│   └── example.com.meta     # Stores Last-Modified date for If-Modified-Since
│
├── run_baseline/            # Created during Task 3 (no throttle)
│   ├── results_http.csv     # 100 rows: 50 direct + 50 proxy HTTP timings
│   └── results_dns.csv      # 40 rows: 4 names × 10 queries each
│
├── run_throttled/           # Created during Task 5 (15 Mbps link emulation)
│   ├── results_http.csv
│   ├── results_dns.csv
│   ├── fig1_latency.png     # HTTP latency: direct vs proxy over time
│   ├── fig2_dns_latency.png # Mean DNS latency per name (bar chart)
│   └── fig3_delay_model.png # Computed delay model — NOT a measurement
│
├── dns_log.csv              # DNS resolver query log (one row per query)
└── README.md                # This file
```

---

## 4. How Each Component Works

### 4.1 TCP Caching Proxy (`edgeshield_proxy.py`)
**Port:** `127.0.0.1:8888 TCP` | **Author:** Partner A

| Case | Condition | Action | WAN cost |
|------|-----------|--------|----------|
| **A — Pure hit** | Cache exists AND age < 30 s | Serve from disk immediately | **0 bytes** |
| **B — Stale revalidation** | Cache exists AND age ≥ 30 s | Send `If-Modified-Since`; if `304`, serve from disk | **~200 B headers only** |
| **C — Cold miss** | No cache file | Full fetch, save to `edge_storage/` | **Full response** |

Each URL → two files: `<name>.cache` (raw response) + `<name>.meta` (Last-Modified date).  
LRU eviction kicks in when cache exceeds 50 MB.

---

### 4.2 DNS Resolver (`dns_resolver.py`)
**Port:** `0.0.0.0:5300 UDP` | **Author:** Partner B

Implements a from-scratch UDP DNS server using Python's `struct` module to parse and build wire-format DNS packets.

**Resolution order:**

| Priority | Path | Example | Result |
|----------|------|---------|--------|
| 1 | **SINKHOLE** | `doubleclick.net` | `0.0.0.0`, TTL 300 s — client connects to nothing |
| 2 | **LOCAL** | `webserver.lan` | `192.168.1.50` from static zone table |
| 3 | **CACHE** | `google.com` (2nd query) | Cached bytes, client's tx-id swapped in |
| 4 | **UPSTREAM** | `google.com` (1st query) | Forwarded to `1.1.1.1:53`, answer cached by TTL |

**12-byte DNS header format:**
```
[TX-ID 2B] [Flags 2B] [QDCOUNT 2B] [ANCOUNT 2B] [NSCOUNT 2B] [ARCOUNT 2B]
```
Response flags `0x8180` = QR=1 (response), RD=1, RA=1, RCODE=0 (no error).

**Every query is logged to `dns_log.csv`:**
```
timestamp, client_ip, qname, qtype, path, latency_ms
```

---

### 4.3 Benchmark Harness (`benchmark.py`)
**Author:** Partner B

```bash
python3 benchmark.py --url http://example.com/ --n 50
```

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | `http://example.com/` | URL to benchmark |
| `--n` | 50 | Number of HTTP requests per mode |
| `--proxy` | `127.0.0.1:8888` | Proxy address |
| `--dns` | `127.0.0.1:5300` | DNS server address |
| `--dns-repeats` | 10 | Queries per DNS name |
| `--skip-http` | — | Skip HTTP test |
| `--skip-dns` | — | Skip DNS test |

**DNS bench:** 10 queries × 4 names → `results_dns.csv` (40 rows)  
**HTTP bench:** 50 direct + 50 proxy requests → `results_http.csv` (100 rows)  
All requests include `Connection: close` to prevent proxy hang.

---

### 4.4 Plotter (`plot_results.py`)
**Author:** Partner B

```bash
python3 plot_results.py --link-mbps 15 --lan-mbps 100 --rtt-ms 50
```

| Output | What it shows |
|--------|---------------|
| `fig1_latency.png` | HTTP response time per request — direct (red) vs proxy (blue) |
| `fig2_dns_latency.png` | Mean DNS latency per name (bar chart) |
| `fig3_delay_model.png` | **Computed model** of d_trans + d_prop — labelled "not measured" |

---

## 5. Quick Start

```bash
# Prerequisites
pip install matplotlib
sudo apt install dnsutils   # for the dig command

# Terminal 1 — start proxy
cd edgeshield_project
python3 edgeshield_proxy.py

# Terminal 2 — start DNS resolver
# (use 127.0.0.53 if 1.1.1.1:53 is blocked by your network)
EDGESHIELD_UPSTREAM=127.0.0.53:53 python3 dns_resolver.py

# Test proxy
curl -i -H "Connection: close" -x http://127.0.0.1:8888 http://example.com/

# Test DNS
dig @127.0.0.1 -p 5300 webserver.lan A      # → 192.168.1.50  LOCAL
dig @127.0.0.1 -p 5300 doubleclick.net A    # → 0.0.0.0       SINKHOLE
dig @127.0.0.1 -p 5300 google.com A         # → real IP       UPSTREAM
dig @127.0.0.1 -p 5300 google.com A         # → same IP       CACHE

# Run baseline benchmark
mkdir -p run_baseline && cd run_baseline
python3 ../benchmark.py --url http://example.com/ --n 50
cd ..
```

---

## 6. Running the Full Experiment

| Task | What happens | Done when |
|------|-------------|-----------|
| 1 | Compatibility check + curl test | `HTTP 200` returned |
| 2 | DNS functional test | All 4 paths logged in `dns_log.csv` |
| 3 | Baseline benchmark (`run_baseline/`) | 100 HTTP rows, 40 DNS rows, 0 ERR |
| 4 | Enable link throttle | `ping example.com` ~50 ms added; `ping 127.0.0.1` < 1 ms |
| 5 | Throttled benchmark (`run_throttled/`) + figures | 3 PNG files produced |
| 6 | Results tables from CSVs | Mean/median/p95/min/max per mode |
| 7 | Wireshark captures | 5 annotated screenshots |
| 8 | Report + viva prep | All numbers from CSVs, no placeholders |

---

## 7. Throttling the Link (Linux `tc`)

### Enable (interface: `wlp1s0`)
```bash
# Step 1 — create IFB device for inbound shaping
sudo modprobe ifb
sudo ip link add ifb0 type ifb
sudo ip link set ifb0 up

# Step 2 — outbound: 2 Mbps up + 25 ms delay
sudo tc qdisc add dev wlp1s0 root handle 1: tbf rate 2mbit burst 32kbit latency 400ms
sudo tc qdisc add dev wlp1s0 parent 1:1 handle 10: netem delay 25ms

# Step 3 — inbound: mirror to ifb0, then 15 Mbps + 25 ms
sudo tc qdisc add dev wlp1s0 ingress
sudo tc filter add dev wlp1s0 parent ffff: protocol ip u32 match u32 0 0 \
     action mirred egress redirect dev ifb0
sudo tc qdisc add dev ifb0 root handle 1: tbf rate 15mbit burst 32kbit latency 400ms
sudo tc qdisc add dev ifb0 parent 1:1 handle 10: netem delay 25ms
```

### Verify
```bash
ping -c 5 example.com   # ~50 ms extra added
ping -c 5 127.0.0.1     # still < 1 ms (loopback unaffected)
```

### Remove throttle ⚠️ Always run this when done
```bash
sudo tc qdisc del dev wlp1s0 root
sudo tc qdisc del dev wlp1s0 ingress
sudo tc qdisc del dev ifb0 root
sudo ip link set ifb0 down
```

---

## 8. Understanding the Results

### HTTP latency — run_baseline (real measured values)

| Mode | Mean | Median | p95 | Min | Max |
|------|------|--------|-----|-----|-----|
| Direct | 110.63 ms | 106.59 ms | 156.46 ms | 70.61 ms | 236.21 ms |
| Proxy — 1st request (miss) | 124.11 ms | — | — | — | — |
| Proxy — requests 2–50 (hits) | **0.93 ms** | 0.91 ms | 1.32 ms | 0.60 ms | 1.65 ms |

**Cache speedup: 118.80×** (mean direct ÷ mean proxy hit)

### DNS latency — run_baseline (real measured values)

| Name | Path | Mean | Notes |
|------|------|------|-------|
| `webserver.lan` | LOCAL | 0.21 ms | Static zone, zero WAN |
| `doubleclick.net` | SINKHOLE | 0.33 ms | Blocked, zero WAN bytes |
| `example.com` | UPSTREAM → CACHE | 5.67 ms avg | 54.81 ms first; 0.20 ms cached |
| `example.org` | UPSTREAM → CACHE | 3.64 ms avg | 34.24 ms first; 0.24 ms cached |

---

## 9. Networking Theory Behind It

### Nodal delay model
```
d_nodal = d_proc + d_queue + d_trans + d_prop
```

| Term | Direct (throttled) | Proxy cache hit |
|------|--------------------|-----------------|
| d_proc | ~1 ms | ~0.1 ms |
| d_queue | Grows as I → 1 | ~0 ms (LAN, lightly loaded) |
| d_trans | L/R = bits / 15 Mbps | L/R on LAN ≈ 0 |
| d_prop | RTT/2 ≈ 25 ms | 0 ms (same machine) |

### Traffic intensity
```
I = La / R
```
- **L** = object size (bits), **a** = request rate (req/s), **R** = link capacity (15 Mbps)
- As **I → 1**, queuing delay → ∞
- The proxy reduces **La** by serving cache hits locally → keeps I ≪ 1

### DNS sinkholing
Returning `0.0.0.0` for ad domains means no TCP connection is ever made to the ad server → **zero** bytes cross the access link for those domains → reduces both **La** and link noise.

---

## 10. Limitations

| Limitation | Detail |
|------------|--------|
| HTTP only | No HTTPS support — all test URLs must be `http://` |
| Single client | No concurrency; one object tested |
| Loopback LAN | Proxy and client on same machine — true LAN delay is 0 |
| DNS not integrated | Proxy uses OS resolver, not EdgeShield DNS |
| Cache correctness | Depends on origin sending `Last-Modified` header |
| Figure 3 is a model | `fig3_delay_model.png` is computed, not measured |
| tc emulation | `netem` adds fixed delay; doesn't model competing traffic or real congestion |

---

## Partner Responsibilities

| Partner | Owns |
|---------|------|
| **Partner A** | `edgeshield_proxy.py` — TCP caching proxy, If-Modified-Since, LRU eviction |
| **Partner B** | `dns_resolver.py`, `benchmark.py`, `plot_results.py`, throttled-link experiment, Wireshark evidence, figures, report section |
