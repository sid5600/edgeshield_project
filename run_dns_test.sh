#!/usr/bin/env bash
set -e
cd /home/siddhant-kumar-singh/Siddhant/study_Materials/something/cn_casestudy/edgeshield_project

pkill -f dns_resolver.py 2>/dev/null || true
sleep 1
rm -f dns_log.csv

export EDGESHIELD_UPSTREAM=127.0.0.53:53
python3 dns_resolver.py > /home/siddhant-kumar-singh/Siddhant/study_Materials/something/cn_casestudy/edgeshield_project/dns_resolver_console.txt 2>&1 &
DNS_PID=$!
echo "Resolver PID=$DNS_PID"
sleep 3

echo "--- dig webserver.lan ---"
dig @127.0.0.1 -p 5300 webserver.lan A +short

sleep 0.5
echo "--- dig doubleclick.net ---"
dig @127.0.0.1 -p 5300 doubleclick.net A +short

sleep 0.5
echo "--- dig google.com [1st] ---"
dig @127.0.0.1 -p 5300 google.com A +short

sleep 0.5
echo "--- dig google.com [2nd] ---"
dig @127.0.0.1 -p 5300 google.com A +short

sleep 1

echo ""
echo "=== Resolver console output ==="
cat /home/siddhant-kumar-singh/Siddhant/study_Materials/something/cn_casestudy/edgeshield_project/dns_resolver_console.txt

echo ""
echo "=== dns_log.csv ==="
cat dns_log.csv

kill $DNS_PID 2>/dev/null || true
echo "Done."
