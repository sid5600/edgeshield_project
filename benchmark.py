"""EdgeShield benchmark harness (Partner B).
Measures (1) HTTP latency direct vs through the caching proxy and (2) DNS
latency per resolution path. Writes results_http.csv and results_dns.csv.
Usage (start dns_resolver.py and Partner A's proxy first):
    python3 benchmark.py --url http://example.com/ --n 50
    python3 benchmark.py --skip-http   # DNS only
    python3 benchmark.py --skip-dns    # HTTP only
"""
import argparse
import csv
import random
import statistics
import struct
import time
from socket import AF_INET, SOCK_DGRAM, SOCK_STREAM, socket
from urllib.parse import urlparse


def http_get(url, proxy=None, timeout=60):
    """One GET. proxy=(host, port) sends an absolute-URI request via the proxy."""
    u = urlparse(url)
    host, port = u.hostname, u.port or 80
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    target = proxy if proxy else (host, port)
    line = f"GET {url} HTTP/1.1" if proxy else f"GET {path} HTTP/1.1"
    req = f"{line}\r\nHost: {host}\r\nUser-Agent: edgeshield-bench\r\nConnection: close\r\n\r\n"

    t0 = time.perf_counter()
    s = socket(AF_INET, SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(target)
        s.sendall(req.encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    ms = (time.perf_counter() - t0) * 1000
    first = buf.split(b"\r\n", 1)[0].decode("latin1", "ignore")
    status = first.split(" ")[1] if first.startswith("HTTP/") and " " in first else "ERR"
    return ms, len(buf), status


def dns_query(name, server, qtype=1, timeout=3):
    """Send one DNS query, return (ms, rcode, answer_count, first_ipv4_or_empty)."""
    qid = random.randint(0, 65535)
    q = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    for label in name.split("."):
        q += bytes([len(label)]) + label.encode()
    q += b"\x00" + struct.pack("!HH", qtype, 1)
    s = socket(AF_INET, SOCK_DGRAM)
    s.settimeout(timeout)
    t0 = time.perf_counter()
    try:
        s.sendto(q, server)
        resp, _ = s.recvfrom(4096)
    except OSError:
        return (time.perf_counter() - t0) * 1000, -1, 0, ""
    finally:
        s.close()
    ms = (time.perf_counter() - t0) * 1000
    rcode = struct.unpack("!H", resp[2:4])[0] & 0x000F
    an = struct.unpack("!H", resp[6:8])[0]
    ip = ".".join(str(b) for b in resp[-4:]) if an and qtype == 1 else ""
    return ms, rcode, an, ip


def summary(label, vals):
    vals = sorted(vals)
    p95 = vals[max(0, int(len(vals) * 0.95) - 1)]
    print(f"  {label:<22} mean={statistics.mean(vals):9.2f} median={statistics.median(vals):9.2f}"
          f" p95={p95:9.2f} min={vals[0]:9.2f} max={vals[-1]:9.2f} ms")


def bench_http(args):
    rows = []
    px = args.proxy.split(":")
    proxy = (px[0], int(px[1]))
    for mode, p in (("direct", None), ("proxy", proxy)):
        print(f"\n[HTTP] mode={mode} n={args.n} url={args.url}")
        for i in range(1, args.n + 1):
            try:
                ms, size, status = http_get(args.url, p)
            except OSError as exc:
                print(f"  req {i:03d}: ERROR {exc}")
                rows.append([mode, i, "", 0, "ERR"])
                continue
            rows.append([mode, i, f"{ms:.3f}", size, status])
            print(f"  req {i:03d}: {ms:9.2f} ms {size:8d} B status={status}")
    with open("results_http.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "request", "latency_ms", "bytes", "status"])
        w.writerows(rows)
    print("\n---- HTTP summary ----")
    for mode in ("direct", "proxy"):
        ok = [float(r[2]) for r in rows if r[0] == mode and r[2] != ""]
        if ok:
            summary(mode + " (all)", ok)
        if mode == "proxy" and len(ok) > 1:
            summary("proxy (cached, 2..n)", ok[1:])
    d = [float(r[2]) for r in rows if r[0] == "direct" and r[2] != ""]
    p = [float(r[2]) for r in rows if r[0] == "proxy" and r[2] != ""]
    if d and len(p) > 1:
        print(f"  speedup (mean direct / mean proxy-cached): "
              f"{statistics.mean(d) / statistics.mean(p[1:]):.2f}x")


def bench_dns(args):
    dh = args.dns.split(":")
    server = (dh[0], int(dh[1]))
    names = ["webserver.lan", "doubleclick.net", "example.com", "example.org"]
    rows = []
    print(f"\n[DNS] server={args.dns} {args.dns_repeats} queries per name")
    for name in names:
        for i in range(1, args.dns_repeats + 1):
            ms, rcode, an, ip = dns_query(name, server)
            rows.append([name, i, f"{ms:.3f}", rcode, an, ip])
            print(f"  {name:<18} #{i:02d} {ms:8.2f} ms rcode={rcode} answers={an} {ip}")
    with open("results_dns.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qname", "query", "latency_ms", "rcode", "answers", "ip"])
        w.writerows(rows)
    print("\n---- DNS summary ----")
    for name in names:
        v = [float(r[2]) for r in rows if r[0] == name and r[3] == 0]
        if v:
            summary(name, v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://example.com/")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--proxy", default="127.0.0.1:8888")
    ap.add_argument("--dns", default="127.0.0.1:5300")
    ap.add_argument("--dns-repeats", type=int, default=10)
    ap.add_argument("--skip-http", action="store_true")
    ap.add_argument("--skip-dns", action="store_true")
    args = ap.parse_args()
    if not args.skip_dns:
        bench_dns(args)
    if not args.skip_http:
        bench_http(args)


if __name__ == "__main__":
    main()
