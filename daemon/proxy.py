import socket, threading

PROXY_PASS = {
    "localhost:8000": ('127.0.0.1', 9000),
    "localhost:8001": ('127.0.0.1', 9001)
}

RR_STATE = {}

def forward_request(host, port, request_bytes):
    backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        backend.connect((host, int(port)))
        backend.sendall(request_bytes)
        response = b""
        while True:
            chunk = backend.recv(8192)
            if not chunk: break
            response += chunk
        return response
    except Exception as e:
        print(f"   [LỖI KẾT NỐI] Không thể forward tới Backend {host}:{port}")
        return b"HTTP/1.1 502 Bad Gateway\r\n\r\n502 Bad Gateway"
    finally:
        backend.close()

def handle_client(conn, addr, routes):
    global RR_STATE
    try:
        request_bytes = conn.recv(8192)
        if not request_bytes: return
        
        # 1. Trích xuất Hostname từ HTTP Header
        headers_part = request_bytes.split(b'\r\n\r\n')[0]
        hostname = b"unknown"
        for line in headers_part.split(b'\r\n'):
            if line.lower().startswith(b'host:'):
                hostname = line.split(b':', 1)[1].strip()
        
        host_str = hostname.decode('utf-8', 'ignore')
        
        if not routes: return

        # 2. Xác định danh sách Backend cho Host này
        target_config = routes.get(host_str, routes.get(list(routes.keys())[0]))
        
        backends = []
        if isinstance(target_config, tuple) and len(target_config) == 2:
            backends = target_config[0] if isinstance(target_config[0], list) else [target_config[0]]
        elif isinstance(target_config, list):
            backends = target_config
        else:
            backends = [target_config]

        # 3. THỰC THI ROUND ROBIN
        if host_str not in RR_STATE:
            RR_STATE[host_str] = 0
            
        current_index = RR_STATE[host_str]
        selected_backend = backends[current_index]
        
        # Cập nhật index cho lần gọi sau
        RR_STATE[host_str] = (current_index + 1) % len(backends)

        print("\n" + " DISPATCHING REQUEST ".center(60, "="))
        print(f"Nguồn (Client) : {addr[0]}:{addr[1]}")
        print(f"Tên miền ảo    : {host_str}")
        print(f"Thuật toán     : Round-Robin")
        print(f"Trạng thái     : Đang chọn Backend thứ {current_index + 1} trên tổng số {len(backends)}")
        
        visual_rr = ""
        for i in range(len(backends)):
            if i == current_index:
                visual_rr += f" [👉 {backends[i]}] "
            else:
                visual_rr += f"  {backends[i]}  "
        print(f"Vòng xoay      :{visual_rr}")
        print("".center(60, "="))

        #  Xử lý IP/Port và Forward
        if isinstance(selected_backend, tuple):
            thost, tport = selected_backend
        else:
            clean_target = selected_backend.replace('http://', '').replace('https://', '').replace(';', '').strip()
            thost, tport = clean_target.split(':')
            
        response = forward_request(thost, tport, request_bytes)
        conn.sendall(response)
        
    except Exception as e:
        print(f"Proxy Error: {e}")
    finally:
        conn.close()

def create_proxy(ip, port, routes=PROXY_PASS):
    proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    proxy.bind((ip, port))
    proxy.listen(100)
    
    print("\n" + " PROXY DAEMON STARTED ".center(60, "#"))
    print(f"Địa chỉ: {ip}:{port}")
    print(f"Routes nạp thành công: {list(routes.keys())}")
    print("#".center(60, "#") + "\n")
    
    while True:
        conn, addr = proxy.accept()
        threading.Thread(target=handle_client, args=(conn, addr, routes), daemon=True).start()