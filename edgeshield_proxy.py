import os
import time
import email.utils
from socket import *
import threading

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8888
CACHE_DIR = "./edge_storage"
MAX_CACHE_BYTES = 50 * 1024 * 1024  # 50 MB
FRESHNESS_TTL = 30  # Fresh for 30s: serve locally in 0 ms without touching WAN

os.makedirs(CACHE_DIR, exist_ok=True)
cache_lock = threading.Lock()

def get_cache_filenames(url):
    safe_name = url.replace("http://", "").replace("https://", "").replace("/", "_").strip("_")
    if not safe_name:
        safe_name = "default_index"
    return os.path.join(CACHE_DIR, safe_name + ".cache"), os.path.join(CACHE_DIR, safe_name + ".meta")

def enforce_lru_cache():
    with cache_lock:
        total_size = sum(os.path.getsize(os.path.join(CACHE_DIR, f)) 
                         for f in os.listdir(CACHE_DIR) if os.path.isfile(os.path.join(CACHE_DIR, f)))
        if total_size <= MAX_CACHE_BYTES:
            return

        files = [(os.path.join(CACHE_DIR, f), os.path.getatime(os.path.join(CACHE_DIR, f))) 
                 for f in os.listdir(CACHE_DIR)]
        files.sort(key=lambda x: x[1])
        for file_path, _ in files:
            if total_size <= MAX_CACHE_BYTES:
                break
            sz = os.path.getsize(file_path)
            os.remove(file_path)
            total_size -= sz

def handle_client(client_socket, client_addr):
    t_start = time.perf_counter()
    try:
        request_data = client_socket.recv(4096)
        if not request_data:
            return

        request_text = request_data.decode("utf-8", errors="ignore")
        lines = request_text.split("\r\n")
        if len(lines) < 1 or len(lines[0].split()) < 3:
            return

        method, url, version = lines[0].split()[:3]
        host, port = "", 80
        for line in lines[1:]:
            lower_line = line.lower()
            if lower_line.startswith("host:"):
                h_val = line.split(":", 1)[1].strip()
                host, port = (h_val.split(":")[0], int(h_val.split(":")[1])) if ":" in h_val else (h_val, 80)
                break

        if not host:
            return

        cache_file, meta_file = get_cache_filenames(url)

        # Check if cache exists
        if os.path.exists(cache_file) and os.path.exists(meta_file):
            cache_age = time.time() - os.path.getmtime(cache_file)
            
            # CASE A: Fresh in local cache -> Zero WAN delay
            if cache_age < FRESHNESS_TTL:
                with open(cache_file, "rb") as cf:
                    client_socket.sendall(cf.read())
                elapsed = (time.perf_counter() - t_start) * 1000
                print(f"  [PURE CACHE HIT] Served locally (Age: {cache_age:.1f}s) in {elapsed:.2f} ms")
                return

            # CASE B: Stale -> Perform Upstream Conditional GET
            with open(meta_file, "r") as mf:
                last_modified = mf.read().strip()

            cond_req = (
                f"GET {url} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"If-Modified-Since: {last_modified}\r\n"
                f"Connection: close\r\n\r\n"
            )

            origin_sock = socket(AF_INET, SOCK_STREAM)
            origin_sock.connect((host, port))
            origin_sock.sendall(cond_req.encode("utf-8"))

            origin_resp = b""
            while True:
                chunk = origin_sock.recv(4096)
                if not chunk:
                    break
                origin_resp += chunk
            origin_sock.close()

            if b"304 Not Modified" in origin_resp:
                with open(cache_file, "rb") as cf:
                    client_socket.sendall(cf.read())
                # Touch file to reset local freshness
                os.utime(cache_file, None)
                elapsed = (time.perf_counter() - t_start) * 1000
                print(f"  [STATUS 304 HIT] Revalidated upstream in {elapsed:.2f} ms")
            else:
                client_socket.sendall(origin_resp)
                with open(cache_file, "wb") as cf:
                    cf.write(origin_resp)
                with open(meta_file, "w") as mf:
                    mf.write(email.utils.formatdate(timeval=None, localtime=False, usegmt=True))
                elapsed = (time.perf_counter() - t_start) * 1000
                print(f"  [STATUS 200 REFRESH] Updated from origin in {elapsed:.2f} ms")

        else:
            # CASE C: Cold Cache Miss -> Fetch full payload over WAN
            origin_sock = socket(AF_INET, SOCK_STREAM)
            origin_sock.connect((host, port))
            origin_sock.sendall(request_data)

            full_resp = b""
            while True:
                chunk = origin_sock.recv(4096)
                if not chunk:
                    break
                full_resp += chunk
                client_socket.sendall(chunk)
            origin_sock.close()

            with open(cache_file, "wb") as cf:
                cf.write(full_resp)
            with open(meta_file, "w") as mf:
                mf.write(email.utils.formatdate(timeval=None, localtime=False, usegmt=True))

            enforce_lru_cache()
            elapsed = (time.perf_counter() - t_start) * 1000
            print(f"  [CACHE MISS] Cold fetch from WAN in {elapsed:.2f} ms")

    except Exception as e:
        print(f"  [PROXY ERROR] {e}")
    finally:
        client_socket.close()

def main():
    welcome_socket = socket(AF_INET, SOCK_STREAM)
    welcome_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    welcome_socket.bind((PROXY_HOST, PROXY_PORT))
    welcome_socket.listen(20)
    print(f"[*] EdgeShield Proxy with TTL Freshness Cache running on {PROXY_HOST}:{PROXY_PORT}\n")

    while True:
        client_sock, client_addr = welcome_socket.accept()
        t = threading.Thread(target=handle_client, args=(client_sock, client_addr), daemon=True)
        t.start()

if __name__ == "__main__":
    main()
