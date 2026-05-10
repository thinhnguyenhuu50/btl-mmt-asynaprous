import socket
import threading
import select  
from .httpadapter import HttpAdapter

MODE = "callback" 


def handle_sync_client(conn, addr, routes):
    try:
        adapter = HttpAdapter(conn, addr, routes)
        adapter.handle_client()
    except Exception as e:
        pass
    finally:
        conn.close()


callback_readers = {} 

def accept_callback(server_sock, routes):
    conn, addr = server_sock.accept()
    print(f"[Callback Manual] Accepted from {addr}")
    conn.setblocking(False)
    callback_readers[conn] = lambda c=conn: handle_callback_read(c, addr, routes)

def handle_callback_read(conn, addr, routes):
    try:
        adapter = HttpAdapter(conn, addr, routes)
        adapter.handle_client()
    finally:
        if conn in callback_readers:
            del callback_readers[conn]
        conn.close()


tasks = []         
coro_readers = {}   

def accept_coroutine(server_sock, routes):
    while True:
        yield 'read', server_sock
        conn, addr = server_sock.accept()
        print(f"[Coroutine Manual] Accepted from {addr}")
        conn.setblocking(False)
        tasks.append(handle_client_coroutine(conn, addr, routes))

def handle_client_coroutine(conn, addr, routes):
    data = b''
    while True:
        yield 'read', conn
        try:
            chunk = conn.recv(8192)
            if not chunk: break
            data += chunk
            
            if b'\r\n\r\n' in data:
                headers_part, body_part = data.split(b'\r\n\r\n', 1)
                content_length = 0
                for line in headers_part.decode('utf-8', errors='ignore').split('\r\n'):
                    if line.lower().startswith('content-length:'):
                        try: content_length = int(line.split(':')[1].strip())
                        except: pass
                
                if len(body_part) >= content_length:
                    break
        except BlockingIOError:
            continue
        except Exception:
            break

    if data:
        class SyncSocketMock:
            def __init__(self, full_data, real_conn):
                self.full_data = full_data
                self.pos = 0
                self.real_conn = real_conn
            def recv(self, size):
                chunk = self.full_data[self.pos : self.pos + size]
                self.pos += size
                return chunk
            def sendall(self, content): 
                self.real_conn.sendall(content)
            def close(self): pass

        try:
            adapter = HttpAdapter(SyncSocketMock(data, conn), addr, routes)
            adapter.handle_client()
        except Exception as e:
            print(f"[Coroutine Error] {e}")

    conn.close()

def create_backend(ip, port, routes={}):
    print(f" [Backend] Đang chạy {MODE.upper()} bằng Event Loop Thủ Công tại {ip}:{port}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((ip, int(port)))
    server.listen(100)

    if MODE == "thread":
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_sync_client, args=(conn, addr, routes), daemon=True).start()

    elif MODE == "callback":
        server.setblocking(False)
        callback_readers[server] = lambda: accept_callback(server, routes)
        
        while True:
            if not callback_readers: break
            r, _, _ = select.select(callback_readers.keys(), [], [])
            for sock in r:
                callback_readers[sock]() 

    elif MODE == "coroutine":
        server.setblocking(False)
        tasks.append(accept_coroutine(server, routes))
        
      
        while tasks or coro_readers:
            while tasks:
                task = tasks.pop(0)
                try:
                    op, sock = next(task)
                    if op == 'read':
                        coro_readers[sock] = task # Đưa vào danh sách chờ
                except StopIteration:
                    pass # Hàm đã chạy xong thì bỏ qua
            
            if not coro_readers: break
            
            r, _, _ = select.select(coro_readers.keys(), [], [])
            
            for sock in r:
                tasks.append(coro_readers.pop(sock))