"""
This module implements an asynchronous, non-blocking proxy server.
It routes incoming HTTP requests to backend services based on hostname mappings.
Upgraded with Sticky Session (IP Hash / Port Hash) for stateful real-time chat.
"""

import asyncio

PROXY_PASS = {
    "localhost:8000": ('127.0.0.1', 9000),
    "app1.local": ('127.0.0.1', 9001),
    "app2.local": ('127.0.0.1', 9002)
}

# Thay thế RR_STATE bằng STICKY_MAP để nhớ khách cũ
RR_STATE = {}
STICKY_MAP = {} 

async def forward_request(host, port, request_bytes, client_writer):
    """
    Asynchronously forwards the client request to the target backend 
    and streams the response back to the client.
    """
    try:
        backend_reader, backend_writer = await asyncio.open_connection(host, int(port))
        
        # Gửi request tới Backend
        backend_writer.write(request_bytes)
        await backend_writer.drain()
        
        # Đọc response từ Backend và trả về thẳng Client
        while True:
            chunk = await backend_reader.read(8192)
            if not chunk:
                break
            client_writer.write(chunk)
            await client_writer.drain()
            
    except Exception as e:
        print(f" [PROXY ERROR] Cannot forward to {host}:{port} - {e}")
        error_msg = b"HTTP/1.1 502 Bad Gateway\r\n\r\n502 Bad Gateway"
        client_writer.write(error_msg)
        await client_writer.drain()
    finally:
        try:
            backend_writer.close()
            await backend_writer.wait_closed()
        except Exception:
            pass

async def handle_client_async(reader, writer, routes):
    """
    Parses the incoming HTTP request, applies Load Balancing with Sticky Session,
    and delegates to the forwarding coroutine.
    """
    addr = writer.get_extra_info('peername')
    client_identity = f"{addr[0]}:{addr[1]}" # Nhận diện IP:Port của trình duyệt
    global RR_STATE, STICKY_MAP
    
    try:
        request_bytes = await reader.read(8192)
        if not request_bytes: 
            return
        
        # 1. Trích xuất Hostname
        headers_part = request_bytes.split(b'\r\n\r\n')[0]
        hostname = b"unknown"
        for line in headers_part.split(b'\r\n'):
            if line.lower().startswith(b'host:'):
                hostname = line.split(b':', 1)[1].strip()
        
        host_str = hostname.decode('utf-8', 'ignore')
        if not routes: return

        # 2. Xác định danh sách Backend cho Hostname này
        target_config = routes.get(host_str, routes.get(list(routes.keys())[0]))
        backends = []
        if isinstance(target_config, tuple) and len(target_config) == 2:
            backends = target_config[0] if isinstance(target_config[0], list) else [target_config[0]]
        elif isinstance(target_config, list):
            backends = target_config
        else:
            backends = [target_config]

        selected_backend = None
        
        # Khách cũ -> Trả về Node cũ đã ghim
        if client_identity in STICKY_MAP and STICKY_MAP[client_identity] in backends:
            selected_backend = STICKY_MAP[client_identity]
            print(f" [Sticky] Khách cũ {client_identity} -> Ghim cứng vào Node {selected_backend}")
        else:
            # Khách mới -> Xoay vòng Round-Robin và GHI SỔ
            if host_str not in RR_STATE:
                RR_STATE[host_str] = 0
                
            current_index = RR_STATE[host_str]
            selected_backend = backends[current_index]
            RR_STATE[host_str] = (current_index + 1) % len(backends)
            
            STICKY_MAP[client_identity] = selected_backend 
            print(f"🔀 [Round-Robin] Khách mới {client_identity} -> Chốt cứng Node {selected_backend}")

        # 4. Forward bất đồng bộ
        if isinstance(selected_backend, tuple):
            thost, tport = selected_backend
        else:
            clean_target = selected_backend.replace('http://', '').replace('https://', '').replace(';', '').strip()
            thost, tport = clean_target.split(':')
            
        await forward_request(thost, tport, request_bytes, writer)
        
    except Exception as e:
        print(f"Proxy Exception: {e}")
    finally:
        writer.close()
        await writer.wait_closed()

def create_proxy(ip, port, routes=PROXY_PASS):
    """
    Entry point for launching the asynchronous proxy server.
    """
    print("\n" + " ASYNC PROXY DAEMON STARTED ".center(60, "#"))
    print(f" Address: {ip}:{port}")
    print(f" Loaded routes: {list(routes.keys())}")
    print("#".center(60, "#") + "\n")
    
    async def run_proxy():
        server = await asyncio.start_server(
            lambda r, w: handle_client_async(r, w, routes), ip, port
        )
        async with server:
            await server.serve_forever()
            
    asyncio.run(run_proxy())