"""
This module implements an asynchronous, non-blocking proxy server.
It routes incoming HTTP requests to backend services based on hostname mappings.
"""

import asyncio

PROXY_PASS = {
    "localhost:8000": ('127.0.0.1', 9000),
    "app1.local": ('127.0.0.1', 9001),
    "app2.local": ('127.0.0.1', 9002)
}

RR_STATE = {}

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
        print(f"❌ [PROXY ERROR] Cannot forward to {host}:{port} - {e}")
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
    Parses the incoming HTTP request, applies Round-Robin load balancing,
    and delegates to the forwarding coroutine.
    """
    addr = writer.get_extra_info('peername')
    global RR_STATE
    
    try:
        request_bytes = await reader.read(8192)
        if not request_bytes: 
            return
        
        # Trích xuất Hostname
        headers_part = request_bytes.split(b'\r\n\r\n')[0]
        hostname = b"unknown"
        for line in headers_part.split(b'\r\n'):
            if line.lower().startswith(b'host:'):
                hostname = line.split(b':', 1)[1].strip()
        
        host_str = hostname.decode('utf-8', 'ignore')
        
        if not routes: 
            return

        target_config = routes.get(host_str, routes.get(list(routes.keys())[0]))
        
        backends = []
        if isinstance(target_config, tuple) and len(target_config) == 2:
            backends = target_config[0] if isinstance(target_config[0], list) else [target_config[0]]
        elif isinstance(target_config, list):
            backends = target_config
        else:
            backends = [target_config]

        # Áp dụng Round-Robin
        if host_str not in RR_STATE:
            RR_STATE[host_str] = 0
            
        current_index = RR_STATE[host_str]
        selected_backend = backends[current_index]
        RR_STATE[host_str] = (current_index + 1) % len(backends)

        print(f"📡 Proxy Dispatch | Target: {host_str} -> Backend: {selected_backend}")
        
        if isinstance(selected_backend, tuple):
            thost, tport = selected_backend
        else:
            clean_target = selected_backend.replace('http://', '').replace('https://', '').strip()
            thost, tport = clean_target.split(':')
            
        await forward_request(thost, tport, request_bytes, writer)
        
    except Exception as e:
        print(f"⚠️ Proxy Exception: {e}")
    finally:
        writer.close()
        await writer.wait_closed()

def create_proxy(ip, port, routes=PROXY_PASS):
    """
    Entry point for launching the asynchronous proxy server.
    """
    print("\n" + " ASYNC PROXY DAEMON STARTED ".center(60, "#"))
    print(f"🚀 Address: {ip}:{port}")
    print(f"📋 Loaded routes: {list(routes.keys())}")
    print("#".center(60, "#") + "\n")
    
    async def run_proxy():
        server = await asyncio.start_server(
            lambda r, w: handle_client_async(r, w, routes), ip, port
        )
        async with server:
            await server.serve_forever()
            
    asyncio.run(run_proxy())