"""
This module provides a backend object to manage and persist backend daemons.
It implements non-blocking mechanisms (Multi-thread, Callback, Coroutine) 
for handling incoming HTTP connections.
"""

import socket
import threading
import selectors
import asyncio
from .httpadapter import HttpAdapter

MODE = "coroutine"  # Sử dụng coroutine (async/await) theo xu hướng hiệu năng cao

sel = selectors.DefaultSelector()

def handle_sync_client(conn, addr, routes):
    """Handles client connection synchronously using threading."""
    try:
        adapter = HttpAdapter(conn, addr, routes)
        adapter.handle_client()
    except Exception as e:
        print(f"[Backend] Error: {e}")
    finally:
        conn.close()

async def handle_async_client(reader, writer, routes):
    """
    Handles client connection asynchronously using coroutines.
    Ensures safe reading of HTTP headers and body without blocking.
    """
    addr = writer.get_extra_info('peername')
    print(f"[Coroutine] Accepted connection from {addr}")
    try:
        # Đọc Header cẩn thận
        headers_data = bytearray()
        while b'\r\n\r\n' not in headers_data:
            chunk = await reader.read(4096)
            if not chunk:
                break
            headers_data.extend(chunk)
            
        if not headers_data:
            return

        headers_part, body_part = headers_data.split(b'\r\n\r\n', 1)
        
        # Xác định độ dài Content-Length
        content_length = 0
        for line in headers_part.decode('utf-8', errors='ignore').split('\r\n'):
            if line.lower().startswith('content-length:'):
                try: 
                    content_length = int(line.split(':')[1].strip())
                except ValueError: 
                    pass
        
        # Đọc đủ Body nếu có
        while len(body_part) < content_length:
            chunk = await reader.read(8192)
            if not chunk: 
                break
            body_part.extend(chunk)

        full_request_data = headers_part + b'\r\n\r\n' + body_part

        # Tạo một Mock Socket để tương thích với HttpAdapter cũ
        class AsyncSocketMock:
            def __init__(self, full_data):
                self.full_data = full_data
                self.pos = 0
            def recv(self, size):
                chunk = self.full_data[self.pos : self.pos + size]
                self.pos += size
                return chunk
            def sendall(self, content): 
                writer.write(content)
            def close(self): 
                pass

        adapter = HttpAdapter(AsyncSocketMock(full_request_data), addr, routes)
        adapter.handle_client()
        await writer.drain()
        
    except Exception as e:
        print(f"[Coroutine Error] {e}")
    finally:
        writer.close()
        await writer.wait_closed()

def create_backend(ip, port, routes=None):
    """
    Entry point for creating and running the backend server.
    """
    if routes is None:
        routes = {}
        
    print(f"🚀 [Backend] Starting in mode: {MODE.upper()} at {ip}:{port}")

    if MODE == "thread":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((ip, int(port)))
        server.listen(100)
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_sync_client, args=(conn, addr, routes), daemon=True).start()

    elif MODE == "coroutine":
        async def run_async_server():
            server = await asyncio.start_server(
                lambda r, w: handle_async_client(r, w, routes), ip, port
            )
            async with server:
                await server.serve_forever()
        asyncio.run(run_async_server())