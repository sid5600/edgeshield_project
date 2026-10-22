"""EdgeShield DNS engine (Partner B).
UDP DNS resolver with four resolution paths, checked in this order:
1. SINKHOLE - blocked domains get 0.0.0.0 (A) or an empty NOERROR (other types)
2. LOCAL    - static zone records (*.lan) answered from memory
3. CACHE    - upstream answers cached until their TTL expires
4. UPSTREAM - unknown names forwarded to a public resolver, answer cached
Run:
    python3 dns_resolver.py
Options: EDGESHIELD_DNS_PORT (default 5300), EDGESHIELD_UPSTREAM (default 1.1.1.1:53)
Logs:    dns_log.csv (timestamp, client, qname, qtype, path, latency_ms)
"""
import csv
import os
import struct
import time
from socket import AF_INET, SOCK_DGRAM, socket

DNS_PORT = int(os.environ.get("EDGESHIELD_DNS_PORT", "5300"))
_up_host, _, _up_port = os.environ.get("EDGESHIELD_UPSTREAM", "1.1.1.1:53").partition(":")
UPSTREAM_DNS = (_up_host, int(_up_port or 53))
UPSTREAM_TIMEOUT = 2.0
LOG_FILE = "dns_log.csv"

LOCAL_ZONES = {
    "webserver.lan": "192.168.1.50",
    "gateway.lan":   "192.168.1.1",
    "proxy.lan":     "127.0.0.1",
}

SINKHOLE_LIST = {
    "adserver.tracker.com",
    "telemetry.analytics.net",
    "doubleclick.net",
}

QTYPE_A = 1

# cache key: (qname, qtype) -> (raw_response_bytes, expiry_epoch)
dns_cache = {}
stats = {"SINKHOLE": 0, "LOCAL": 0, "CACHE": 0, "UPSTREAM": 0, "FAIL": 0}


def parse_question(buf):
    """Return (qname_lowercase, qtype, question_bytes) from a query packet."""
    idx, labels = 12, []
    while idx < len(buf) and buf[idx] != 0:
        n = buf[idx]
        labels.append(buf[idx + 1: idx + 1 + n].decode("ascii", "ignore"))
        idx += 1 + n
    qtype = struct.unpack("!H", buf[idx + 1: idx + 3])[0]
    end = idx + 5  # zero byte + QTYPE(2) + QCLASS(2)
    return ".".join(labels).lower(), qtype, buf[12:end]


def build_response(tx_id, question, ip=None, rcode=0, ttl=60):
    """Build a response: one A record if ip is given, else an empty answer."""
    flags = 0x8180 | rcode  # QR=1, RD=1, RA=1
    header = tx_id + struct.pack("!HHHHH", flags, 1, 1 if ip else 0, 0, 0)
    if not ip:
        return header + question
    rr = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, ttl, 4)
    return header + question + rr + bytes(int(p) for p in ip.split("."))


def _skip_name(buf, off):
    while True:
        n = buf[off]
        if n == 0:
            return off + 1
        if n & 0xC0 == 0xC0:  # compression pointer
            return off + 2
        off += 1 + n


def min_answer_ttl(resp):
    """Smallest TTL among answer records (None if no answers)."""
    try:
        qd, an = struct.unpack("!HH", resp[4:8])
        off = 12
        for _ in range(qd):
            off = _skip_name(resp, off) + 4
        ttls = []
        for _ in range(an):
            off = _skip_name(resp, off)
            _, _, ttl, rdlen = struct.unpack("!HHIH", resp[off: off + 10])
            ttls.append(ttl)
            off += 10 + rdlen
        return min(ttls) if ttls else None
    except Exception:
        return None


def forward_upstream(data):
    s = socket(AF_INET, SOCK_DGRAM)
    s.settimeout(UPSTREAM_TIMEOUT)
    try:
        s.sendto(data, UPSTREAM_DNS)
        resp, _ = s.recvfrom(4096)
        return resp
    except OSError:
        return None
    finally:
        s.close()


def resolve(data):
    """Return (response_bytes, path_label) for one query packet."""
    tx_id = data[:2]
    qname, qtype, question = parse_question(data)

    if qname in SINKHOLE_LIST:
        stats["SINKHOLE"] += 1
        ip = "0.0.0.0" if qtype == QTYPE_A else None
        return build_response(tx_id, question, ip, ttl=300), "SINKHOLE"

    if qname in LOCAL_ZONES and qtype == QTYPE_A:
        stats["LOCAL"] += 1
        return build_response(tx_id, question, LOCAL_ZONES[qname]), "LOCAL"

    key, now = (qname, qtype), time.time()
    hit = dns_cache.get(key)
    if hit and hit[1] > now:
        stats["CACHE"] += 1
        return tx_id + hit[0][2:], "CACHE"  # reuse answer, keep client's tx id

    resp = forward_upstream(data)
    if resp is None:
        stats["FAIL"] += 1
        return build_response(tx_id, question, rcode=2), "FAIL"  # SERVFAIL

    stats["UPSTREAM"] += 1
    ttl = min_answer_ttl(resp)
    if ttl:
        dns_cache[key] = (resp, now + ttl)
    return resp, "UPSTREAM"


def main():
    sock = socket(AF_INET, SOCK_DGRAM)
    sock.bind(("0.0.0.0", DNS_PORT))
    new_log = not os.path.exists(LOG_FILE)
    log_f = open(LOG_FILE, "a", newline="")
    log = csv.writer(log_f)
    if new_log:
        log.writerow(["timestamp", "client", "qname", "qtype", "path", "latency_ms"])
    print(f"[*] EdgeShield DNS on UDP {DNS_PORT}, upstream {UPSTREAM_DNS[0]}:{UPSTREAM_DNS[1]}")
    try:
        while True:
            data, addr = sock.recvfrom(4096)
            if len(data) < 17:
                continue
            t0 = time.perf_counter()
            try:
                resp, path = resolve(data)
            except Exception as exc:  # malformed packet: never crash the server
                print(f"[DNS ERROR] {exc}")
                continue
            sock.sendto(resp, addr)
            ms = (time.perf_counter() - t0) * 1000
            qname, qtype, _ = parse_question(data)
            print(f"[DNS {path}] {qname} type={qtype} {ms:.2f} ms")
            log.writerow([time.time(), addr[0], qname, qtype, path, f"{ms:.3f}"])
            log_f.flush()
    except KeyboardInterrupt:
        print(f"\n[*] Stopped. Stats: {stats}")
    finally:
        log_f.close()
        sock.close()


if __name__ == "__main__":
    main()
