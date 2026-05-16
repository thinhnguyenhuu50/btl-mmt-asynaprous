# File: daemon/backend.py
import socket
import threading
import zmq
import time
from .httpadapter import HttpAdapter

MODE = "thread"

# ============================================================
# BIẾN TOÀN CỤC ĐỂ CHATAPP GIAO TIẾP VỚI MESSAGE QUEUE
# ============================================================
pub_socket = None
mq_callbacks = {}
known_peers_list = []

def register_mq_handler(topic, callback_func):
    """API để đăng ký hàm xử lý sự kiện P2P từ ChatApp"""
    mq_callbacks[topic] = callback_func

def send_p2p(topic, payload):
    """API để bắn tin nhắn P2P trực tiếp ra mạng lưới không qua broker"""
    if pub_socket:
        pub_socket.send_json({"topic": topic, "payload": payload})

# ============================================================
# CẬP NHẬT DANH BẠ TỪ TRACKER 
# ============================================================
def _tracker_sync_worker(context, http_port, zmq_port, sub_socket, tracker_url="tcp://127.0.0.1:80"):
    global known_peers_list
    connected_peers = set()
    while True:
        req = context.socket(zmq.REQ)
        req.RCVTIMEO = 2000
        try:
            req.connect(tracker_url)
            req.send_json({
                "action": "register",
                "peer_id": f"peer_{http_port}",
                "ip": "127.0.0.1",
                "zmq_port": zmq_port
            })
            res = req.recv_json()
            peers = res.get("peers", {})
            
            ports = []
            for pid, info in peers.items():
                p_port = info["zmq_port"] - 1000
                ports.append(p_port)
                if info["zmq_port"] != zmq_port:
                    url = f"tcp://{info['ip']}:{info['zmq_port']}"
                    if url not in connected_peers:
                        sub_socket.connect(url)
                        connected_peers.add(url)
            known_peers_list = ports
        except Exception:
            pass
        finally:
            req.close()
        time.sleep(5)


# ============================================================
# MOCK SOCKET CHUYỂN ĐỔI DATA ĐỌC ĐỒNG BỘ CHO HTTPADAPTER
# ============================================================
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


# ============================================================
# PHÂN TÍCH GÓI TIN HTTP CHUNG CHO CHẾ ĐỘ NON-BLOCKING
# ============================================================
def _parse_http_chunk(conn, current_data):
    try:
        chunk = conn.recv(8192)
        if not chunk:
            return None, True # Ngắt kết nối
        current_data += chunk
        
        if b'\r\n\r\n' in current_data:
            headers_part, body_part = current_data.split(b'\r\n\r\n', 1)
            content_length = 0
            for line in headers_part.decode('utf-8', errors='ignore').split('\r\n'):
                if line.lower().startswith('content-length:'):
                    try: content_length = int(line.split(':')[1].strip())
                    except: pass
            if len(body_part) >= content_length:
                return current_data, True # Đã đọc đủ gói
        return current_data, False # Chưa đủ gói dữ liệu
    except BlockingIOError:
        return current_data, False
    except Exception:
        return None, True


# ============================================================
# CHẾ ĐỘ 1: THREADING (ĐA LUỒNG TRUYỀN THỐNG)
# ============================================================
def _handle_http_client_thread(conn, addr, routes):
    data = b''
    while True:
        data, is_done = _parse_http_chunk(conn, data)
        if is_done: break
    if data:
        try:
            adapter = HttpAdapter(SyncSocketMock(data, conn), addr, routes)
            adapter.handle_client()
        except Exception as e: print(f"[HTTP Thread Error] {e}")
    conn.close()

def _run_thread_loop(server, routes, sub_socket):
    # Luồng độc lập nhận tin nhắn ZeroMQ
    def zmq_reader():
        while True:
            try:
                msg = sub_socket.recv_json()
                topic, payload = msg.get("topic"), msg.get("payload")
                if topic in mq_callbacks:
                    mq_callbacks[topic](payload)
            except Exception: pass

    threading.Thread(target=zmq_reader, daemon=True).start()

    # Luồng chính lặp accept kết nối HTTP
    while True:
        try:
            conn, addr = server.accept()
            conn.setblocking(False)
            threading.Thread(target=_handle_http_client_thread, args=(conn, addr, routes), daemon=True).start()
        except BlockingIOError:
            time.sleep(0.01)


# ============================================================
# CHẾ ĐỘ 2: CALLBACK (EVENT LOOP VỚI ĐĂNG KÝ HÀM SỰ KIỆN)
# ============================================================
def _run_callback_loop(server, routes, sub_socket, poller):
    callback_readers = {}
    http_buffers = {}

    # Đăng ký sự kiện accept HTTP
    def handle_accept():
        try:
            conn, addr = server.accept()
            conn.setblocking(False)
            fd = conn.fileno()
            poller.register(fd, zmq.POLLIN)
            http_buffers[fd] = b''
            
            # Đăng ký hàm đọc dữ liệu cho client này
            callback_readers[fd] = lambda: handle_http_read(conn, addr, fd)
        except BlockingIOError: pass

    # Đăng ký sự kiện đọc HTTP Client
    def handle_http_read(conn, addr, fd):
        buf = http_buffers.get(fd, b'')
        buf, is_done = _parse_http_chunk(conn, buf)
        http_buffers[fd] = buf
        
        if is_done:
            if buf:
                try:
                    adapter = HttpAdapter(SyncSocketMock(buf, conn), addr, routes)
                    adapter.handle_client()
                except Exception as e: print(f"[HTTP Callback Error] {e}")
            poller.unregister(fd)
            conn.close()
            callback_readers.pop(fd, None)
            http_buffers.pop(fd, None)

    # Đăng ký sự kiện đọc ZeroMQ Message
    def handle_zmq_read():
        try:
            msg = sub_socket.recv_json(flags=zmq.NOBLOCK)
            topic, payload = msg.get("topic"), msg.get("payload")
            if topic in mq_callbacks:
                mq_callbacks[topic](payload)
        except zmq.error.Again: pass

    # Đăng ký gốc ban đầu vào bảng điều phối
    callback_readers[server.fileno()] = handle_accept
    callback_readers[sub_socket] = handle_zmq_read

    while True:
        events = dict(poller.poll(timeout=100))
        for sock_obj, state in events.items():
            if state & zmq.POLLIN and sock_obj in callback_readers:
                callback_readers[sock_obj]()


# ============================================================
# CHẾ ĐỘ 3: COROUTINE 
# ============================================================
def handle_client_coroutine(conn, addr, routes, poller):
    data = b''
    fd = conn.fileno()
    while True:
        yield 'read', fd
        data, is_done = _parse_http_chunk(conn, data)
        if is_done: break

    if data:
        try:
            adapter = HttpAdapter(SyncSocketMock(data, conn), addr, routes)
            adapter.handle_client()
        except Exception as e: print(f"[HTTP Coroutine Error] {e}")
    poller.unregister(fd)
    conn.close()

def accept_coroutine(server_sock, routes, poller):
    while True:
        yield 'read', server_sock.fileno()
        try:
            conn, addr = server_sock.accept()
            conn.setblocking(False)
            poller.register(conn.fileno(), zmq.POLLIN)
            yield 'new_task', handle_client_coroutine(conn, addr, routes, poller)
        except BlockingIOError: pass

def receive_zmq_coroutine(sub_socket):
    while True:
        yield 'read', sub_socket
        try:
            msg = sub_socket.recv_json(flags=zmq.NOBLOCK)
            topic, payload = msg.get("topic"), msg.get("payload")
            if topic in mq_callbacks:
                mq_callbacks[topic](payload)
        except zmq.error.Again: pass


def _run_coroutine_loop(server, routes, sub_socket, poller):
    tasks = []
    coro_readers = {}

    tasks.append(accept_coroutine(server, routes, poller))
    tasks.append(receive_zmq_coroutine(sub_socket))

    while tasks or coro_readers:
        while tasks:
            task = tasks.pop(0)
            try:
                op, val = next(task)
                if op == 'read':
                    coro_readers[val] = task 
                elif op == 'new_task':
                    tasks.append(val)
                    tasks.append(task)
            except StopIteration: pass
        
        if not coro_readers: break
        
        events = poller.poll(timeout=100)
        for obj, state in events:
            if state & zmq.POLLIN and obj in coro_readers:
                tasks.append(coro_readers.pop(obj))


# ============================================================
# ENTRY POINT CHÍNH CỦA BACKEND KHỞI ĐỘNG HỆ THỐNG
# ============================================================
def create_backend(ip, port, routes={}):
    global pub_socket
    print(f"\n{'='*55}")
    print(f"🚀 KHỞI ĐỘNG ASYNAPROUS BROKERLESS BACKEND")
    print(f"⚙️  CHẾ ĐỘ ĐỒNG THỜI HIỆN TẠI (MODE): {MODE.upper()}")
    print(f"🌐 HTTP Web Server đang lắng nghe tại  : {ip}:{port}")
    
    # 1. Khởi tạo TCP Socket HTTP Server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((ip, int(port)))
    server.listen(100)
    server.setblocking(False)

    # 2. Khởi tạo ZeroMQ Sockets (Brokerless P2P Architecture)
    zmq_port = int(port) + 1000
    context = zmq.Context()
    pub_socket = context.socket(zmq.PUB)
    pub_socket.bind(f"tcp://*:{zmq_port}")
    print(f"⚡ Kênh Chat P2P (ZMQ) sẵn sàng tại cổng : {zmq_port}")
    print(f"{'='*55}\n")
    
    sub_socket = context.socket(zmq.SUB)
    sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")

    # 3. Kích hoạt luồng định danh danh bạ P2P (Service Discovery)
    threading.Thread(target=_tracker_sync_worker, args=(context, port, zmq_port, sub_socket), daemon=True).start()

    # 4. Cấu hình Poller cho cấu trúc Không đồng bộ (Callback và Coroutine)
    poller = zmq.Poller()
    poller.register(server.fileno(), zmq.POLLIN)
    poller.register(sub_socket, zmq.POLLIN)

    # 5. Rẽ nhánh luồng chạy Event Loop theo MODE
    if MODE == "thread":
        # Khi chuyển sang thread thuần, cho server chạy ở chế độ blocking để ổn định kết nối cơ bản
        server.setblocking(True) 
        _run_thread_loop(server, routes, sub_socket)
    elif MODE == "callback":
        _run_callback_loop(server, routes, sub_socket, poller)
    elif MODE == "coroutine":
        _run_coroutine_loop(server, routes, sub_socket, poller)