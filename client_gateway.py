import socket, threading, sys, json, urllib.request, time

CACHED_BACKENDS = []
FALLBACK_NODE = None
GATEWAY_PORT = 8000
PROXY_ALIVE = True  # Cờ trạng thái sinh tồn
_lock = threading.Lock()

def background_tasks():
    """Radar chạy ngầm: Học danh bạ & check khỏe Proxy liên tục"""
    global CACHED_BACKENDS, PROXY_ALIVE
    while True:
        # 1. Học danh bạ P2P
        try:
            req = urllib.request.Request("http://127.0.0.1:80/peers")
            with urllib.request.urlopen(req, timeout=1.0) as res:
                data = json.loads(res.read().decode())
                if data.get("peers"):
                     with _lock: CACHED_BACKENDS = sorted(data["peers"]) # Dùng để chia tải chuẩn
        except: pass
        
        # 2. Khám sức khỏe Proxy (Cổng 81)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(('127.0.0.1', 81))
            s.close()
            if not PROXY_ALIVE:
                print(" [Radar] Proxy 81 sống lại! Trả quyền ưu tiên cho Proxy.")
            PROXY_ALIVE = True
        except:
            if PROXY_ALIVE:
                print(" [Radar] Proxy 81 mất tín hiệu! Kích hoạt chế độ sinh tồn P2P.")
            PROXY_ALIVE = False
        time.sleep(3)

def fix_headers(request_bytes, response_bytes):
    try:
        req_line = request_bytes.split(b'\r\n')[0].decode('utf-8', 'ignore')
        path = req_line.split(' ')[1]
        
        mime_type = "text/html" 
        if path.endswith('.css'): mime_type = "text/css"
        elif path.endswith('.js'): mime_type = "application/javascript"
        elif path.endswith('.png'): mime_type = "image/png"
        
        # [FIXED 1]: Bổ sung đầy đủ các endpoint liên quan đến P2P và Sync
        elif any(ep in path for ep in ['/login', '/channels', '/messages', '/broadcast-peer', '/send-peer', '/create-channel', '/get-list', '/submit-info', '/sync-user']):
            mime_type = "application/json"
            
        if b'\r\n\r\n' in response_bytes:
            headers_part, body_part = response_bytes.split(b'\r\n\r\n', 1)
            new_headers = [line for line in headers_part.split(b'\r\n') if not line.lower().startswith(b'content-type:')]
            new_headers.append(f"Content-Type: {mime_type}; charset=utf-8".encode('utf-8'))
            return b'\r\n'.join(new_headers) + b'\r\n\r\n' + body_part
    except: pass
    return response_bytes

def forward_to(port, request_bytes):
    backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend.settimeout(1.0) 
    backend.connect(('127.0.0.1', port))
    backend.settimeout(10.0) 
    backend.sendall(request_bytes)
    
    response = b""
    while True:
        try:
            chunk = backend.recv(8192)
            if not chunk: break
            response += chunk
        except socket.timeout: break
    backend.close()
    return response

def handle_browser_request(client_sock):
    global CACHED_BACKENDS, FALLBACK_NODE, GATEWAY_PORT, PROXY_ALIVE
    try:
        request_bytes = client_sock.recv(8192)
        if not request_bytes: return
        
        # [FIXED 2]: Đảm bảo đọc đủ Payload Body (tránh chặn Request tại Adapter Backend)
        if b'\r\n\r\n' in request_bytes:
            headers_part, body_part = request_bytes.split(b'\r\n\r\n', 1)
            content_length = 0
            for line in headers_part.split(b'\r\n'):
                if line.lower().startswith(b'content-length:'):
                    try: content_length = int(line.split(b':')[1].strip())
                    except: pass
            while len(body_part) < content_length:
                chunk = client_sock.recv(8192)
                if not chunk: break
                body_part += chunk
                request_bytes += chunk

        raw_response = b""
        
        if PROXY_ALIVE:
            # Nếu Radar báo Proxy sống -> Gắn Proxy
            try:
                raw_response = forward_to(81, request_bytes)
                FALLBACK_NODE = None 
            except Exception as e:
                # TUYỆT ĐỐI KHÔNG RETRY! Nặng giữa chừng, bỏ qua để tránh nhận 2 tin nhắn
                pass 
        else:
            # Nếu Radar báo Proxy chết -> Bám chặt 1 Node dự phòng (P2P)
            with _lock:
                if not FALLBACK_NODE or FALLBACK_NODE not in CACHED_BACKENDS:
                    if CACHED_BACKENDS:
                        index = GATEWAY_PORT % len(CACHED_BACKENDS)
                        FALLBACK_NODE = CACHED_BACKENDS[index]
                        
            if FALLBACK_NODE:
                try:
                     raw_response = forward_to(FALLBACK_NODE, request_bytes)
                except Exception as ex:
                     FALLBACK_NODE = None
                     
        if raw_response:
            final_response = fix_headers(request_bytes, raw_response)
            client_sock.sendall(final_response)
        else:
            client_sock.sendall(b"HTTP/1.1 503 Service Unavailable\r\n\r\n")
            
    except: pass
    finally: client_sock.close()

def run_gateway(my_port):
    global GATEWAY_PORT
    GATEWAY_PORT = my_port
    
    # Bật Radar ngầm
    threading.Thread(target=background_tasks, daemon=True).start()
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', my_port))
    server.listen(100)
    print(f" [Client Gateway] Đang mở tại http://127.0.0.1:{my_port}")
    
    while True:
        client_sock, _ = server.accept()
        threading.Thread(target=handle_browser_request, args=(client_sock,), daemon=True).start()

if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_gateway(p)