import socket
import threading
import selectors
import asyncio
from .httpadapter import HttpAdapter

MODE = "callback" 

def handle_sync_client(conn, addr, routes):
    try:
        adapter = HttpAdapter(conn, addr, routes)
        adapter.handle_client()
    except Exception as e:
        print(f"[Backend] Error: {e}")
    finally:
        conn.close()

sel = selectors.DefaultSelector()

def accept_callback(sock, mask, routes):
    conn, addr = sock.accept()
    print(f"[Callback] Accepted from {addr}")
    conn.setblocking(False)
    sel.register(conn, selectors.EVENT_READ, lambda c, m: handle_callback_read(c, m, addr, routes))

def handle_callback_read(conn, mask, addr, routes):
    try:
        adapter = HttpAdapter(conn, addr, routes)
        adapter.handle_client()
    finally:
        sel.unregister(conn)
        conn.close()

async def handle_async_client(reader, writer, routes):
    addr = writer.get_extra_info('peername')
    print(f"[Coroutine] Accepted from {addr}")
    try:
        data = await reader.read(8192)
        if not data: return
        
        if b'\r\n\r\n' in data:
            headers_part, body_part = data.split(b'\r\n\r\n', 1)
            content_length = 0
            for line in headers_part.decode('utf-8', errors='ignore').split('\r\n'):
                if line.lower().startswith('content-length:'):
                    try: content_length = int(line.split(':')[1].strip())
                    except: pass
            
            while len(body_part) < content_length:
                chunk = await reader.read(8192)
                if not chunk: break
                body_part += chunk
                data += chunk

        class AsyncSocketMock:
            def __init__(self, full_data):
                self.full_data = full_data
                self.pos = 0
            def recv(self, size):
                chunk = self.full_data[self.pos : self.pos + size]
                self.pos += size
                return chunk
            def sendall(self, content): writer.write(content)
            def close(self): pass

        adapter = HttpAdapter(AsyncSocketMock(data), addr, routes)
        adapter.handle_client()
        await writer.drain()
    except Exception as e:
        print(f"[Coroutine Error] {e}")
    finally:
        writer.close()
    try:
        await writer.wait_closed()
    except (ConnectionResetError, OSError):
            # Client hoặc Proxy đã ngắt kết nối thô bạo (WinError 64/10054).
            # Chúng ta cứ lẳng lặng bỏ qua, không cho crash hệ thống.
        pass
def create_backend(ip, port, routes={}):
    print(f"🚀 [Backend] Đang khởi động chế độ: {MODE.upper()} tại {ip}:{port}")

    if MODE == "thread":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((ip, int(port)))
        server.listen(100)
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_sync_client, args=(conn, addr, routes), daemon=True).start()

    elif MODE == "callback":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((ip, int(port)))
        server.listen(100)
        server.setblocking(False)
        sel.register(server, selectors.EVENT_READ, lambda s, m: accept_callback(s, m, routes))
        while True:
            events = sel.select()
            for key, mask in events:
                callback = key.data
                callback(key.fileobj, mask)

    elif MODE == "coroutine":
        async def run_async_server():
            server = await asyncio.start_server(lambda r, w: handle_async_client(r, w, routes), ip, port)
            async with server:
                await server.serve_forever()
        asyncio.run(run_async_server())