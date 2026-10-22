"""Generate report figures from results_http.csv and results_dns.csv.
python3 plot_results.py --link-mbps 15 --lan-mbps 100 --rtt-ms 50
Outputs fig1_latency.png, fig2_dns_latency.png, fig3_delay_model.png
"""
import argparse
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--link-mbps", type=float, default=15.0)
    ap.add_argument("--lan-mbps", type=float, default=100.0)
    ap.add_argument("--rtt-ms", type=float, default=50.0)
    a = ap.parse_args()

    http = [r for r in load("results_http.csv") if r["latency_ms"]]
    fig, ax = plt.subplots(figsize=(7, 4))
    for mode, color in (("direct", "#c0392b"), ("proxy", "#2471a3")):
        pts = [(int(r["request"]), float(r["latency_ms"])) for r in http if r["mode"] == mode]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", ms=3, label=mode,
                color=color)
    ax.set_xlabel("Request number")
    ax.set_ylabel("Response time (ms)")
    ax.set_title("Figure 1: HTTP latency, direct vs EdgeShield")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("fig1_latency.png", dpi=200)

    dns = [r for r in load("results_dns.csv") if r["rcode"] == "0"]
    names = sorted({r["qname"] for r in dns})
    means = [sum(float(r["latency_ms"]) for r in dns if r["qname"] == n) /
             max(1, sum(1 for r in dns if r["qname"] == n)) for n in names]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(names, means, color="#2471a3")
    ax.set_ylabel("Mean DNS latency (ms)")
    ax.set_title("Figure 2: DNS latency by name (local / sinkhole / upstream+cache)")
    plt.setp(ax.get_xticklabels(), rotation=15)
    fig.tight_layout()
    fig.savefig("fig2_dns_latency.png", dpi=200)

    size = max(int(r["bytes"]) for r in http if r["mode"] == "direct")
    bits = size * 8
    parts = {
        "Direct (throttled link)":      (bits / (a.link_mbps * 1e6) * 1000, a.rtt_ms),
        "EdgeShield cache hit (LAN)":   (bits / (a.lan_mbps * 1e6) * 1000, 0.0),
    }
    fig, ax = plt.subplots(figsize=(7, 4))
    labels = list(parts)
    trans = [parts[k][0] for k in labels]
    prop  = [parts[k][1] for k in labels]
    ax.bar(labels, trans, label="d_trans = L/R", color="#2471a3")
    ax.bar(labels, prop, bottom=trans, label="d_prop (RTT)", color="#e67e22")
    ax.set_ylabel("Delay (ms)")
    ax.set_title(f"Figure 3: Delay model for a {size} B object (computed, not measured)")
    ax.legend()
    fig.tight_layout()
    fig.savefig("fig3_delay_model.png", dpi=200)
    print("Saved fig1_latency.png, fig2_dns_latency.png, fig3_delay_model.png")


if __name__ == "__main__":
    main()
