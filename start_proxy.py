import socket, threading, json

REGISTERED_PEERS = []
STICKY_MAP = {}  #  Client (Port 8000, 8001...) -> Backend (9000, 9001...)
rr_idx = 0
_lock = threading.Lock()

def get_sticky_backend(request_bytes):
    """Proxy đọc HTTP Header để chia tải và Gắn chặt Client với Backend"""
    global rr_idx
    with _lock:
        if not REGISTERED_PEERS: return None
        
        # 1. Trích xuất Host (Ví dụ: 127.0.0.1:8000) từ gói tin HTTP
        host_str = "unknown_client"
        try:
            headers = request_bytes.split(b'\r\n\r\n')[0]
            for line in headers.split(b'\r\n'):
                if line.lower().startswith(b'host:'):
                    host_str = line.split(b':', 1)[1].strip().decode('utf-8')
                    break
        except: pass
        
        # 2. Nếu Client này đã được ghi sổ và Backend đó vẫn còn sống
        if host_str in STICKY_MAP and STICKY_MAP[host_str] in REGISTERED_PEERS:
            return STICKY_MAP[host_str]
        
        # 3. Nếu Client mới tinh: Áp dụng Round-Robin và Ghi vào sổ
        target = REGISTERED_PEERS[rr_idx % len(REGISTERED_PEERS)]
        rr_idx += 1
        STICKY_MAP[host_str] = target
        print(f"🔀 [Proxy LB] Khách mới từ '{host_str}' -> Gán chặt vào Node {target}")
        return target

def handle_proxy_request(client_sock):
    try:
        request_bytes = client_sock.recv(8192)
        if not request_bytes: return

        # Proxy tự quyết định đường đi
        target_port = get_sticky_backend(request_bytes)
        if not target_port:
            client_sock.sendall(b"HTTP/1.1 503 Service Unavailable\r\n\r\n503: Khong co Backend nao hoat dong!")
            return

        # Kết nối tới Backend đã chọn
        backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend.settimeout(1.0)
        backend.connect(('127.0.0.1', target_port))
        backend.settimeout(10.0)
        backend.sendall(request_bytes)
        
        # Nhận và trả dữ liệu
        response = b""
        while True:
            try:
                chunk = backend.recv(8192)
                if not chunk: break
                response += chunk
            except socket.timeout: break
        backend.close()
        
        client_sock.sendall(response)
    except: pass
    finally: client_sock.close()

def run_lb():
    lb = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lb.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lb.bind(('127.0.0.1', 81))
    lb.listen(100)
    print("🔄 [Proxy] Load Balancer đang chạy tại Port 81")
    while True:
        client_sock, _ = lb.accept()
        threading.Thread(target=handle_proxy_request, args=(client_sock,), daemon=True).start()

if __name__ == "__main__":
    from daemon import AsynapRous
    tracker = AsynapRous()
    @tracker.route('/register', methods=['POST'])
    def reg(h, b, c):
        p = json.loads(b.decode('utf-8') if isinstance(b, bytes) else b)['port']
        if p not in REGISTERED_PEERS: REGISTERED_PEERS.append(p)
        print(f"✅ [Tracker] Node {p} đã online! Danh sách Backend: {REGISTERED_PEERS}")
        return '{"status":"ok"}'
        
    @tracker.route('/peers', methods=['GET'])
    def peers(h, b, c): return json.dumps({"peers": REGISTERED_PEERS})
    
    # Chạy Proxy luồng nền
    threading.Thread(target=run_lb, daemon=True).start()
    
    # Chạy Tracker luồng chính
    print("🧭 [Tracker] Discovery Service đang chạy tại Port 80")
    tracker.prepare_address('127.0.0.1', 80)
    tracker.run()