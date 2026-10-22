#!/usr/bin/env bash
# Task 3: Baseline benchmark (no throttling)
# Starts dns_resolver + proxy, runs benchmark in run_baseline/, then stops both.

PROJECT=/home/siddhant-kumar-singh/Siddhant/study_Materials/something/cn_casestudy/edgeshield_project
cd "$PROJECT"

# Kill any stale processes
pkill -f dns_resolver.py 2>/dev/null || true
pkill -f edgeshield_proxy.py 2>/dev/null || true
sleep 1

# Start DNS resolver (upstream via systemd-resolved stub)
export EDGESHIELD_UPSTREAM=127.0.0.53:53
python3 dns_resolver.py > "$PROJECT/dns_resolver_console.txt" 2>&1 &
DNS_PID=$!
echo "[*] dns_resolver.py started  PID=$DNS_PID"

# Start proxy
python3 edgeshield_proxy.py > "$PROJECT/proxy_console.txt" 2>&1 &
PROXY_PID=$!
echo "[*] edgeshield_proxy.py started PID=$PROXY_PID"

sleep 3

# Create run_baseline and run benchmark from inside it
mkdir -p "$PROJECT/run_baseline"
cd "$PROJECT/run_baseline"

echo ""
echo "[*] Running benchmark (n=50) ..."
python3 ../benchmark.py --url http://example.com/ --n 50

echo ""
echo "=== results_http.csv (first 5 + last 5 rows) ==="
head -6 results_http.csv
echo "..."
tail -5 results_http.csv
echo ""
echo "Total rows in results_http.csv (excluding header):"
tail -n +2 results_http.csv | wc -l

echo ""
echo "=== results_dns.csv (first 5 + last 5 rows) ==="
head -6 results_dns.csv
echo "..."
tail -5 results_dns.csv
echo ""
echo "Total rows in results_dns.csv (excluding header):"
tail -n +2 results_dns.csv | wc -l

echo ""
echo "=== ERR count in results_http.csv ==="
grep -c "ERR" results_http.csv || echo "0 ERR rows"

# Stop services
kill $DNS_PID $PROXY_PID 2>/dev/null || true
wait $DNS_PID $PROXY_PID 2>/dev/null || true
echo ""
echo "[*] Services stopped. Done."
