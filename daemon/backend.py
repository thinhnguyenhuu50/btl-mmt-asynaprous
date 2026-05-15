# File: daemon/backend.py
import socket
import threading
import zmq
import time
from .httpadapter import HttpAdapter

MODE = "coroutine"

# ============================================================
# BIẾN TOÀN CỤC ĐỂ CHATAPP GIAO TIẾP VỚI MESSAGE QUEUE
# ============================================================
pub_socket = None
mq_callbacks = {}
known_peers_list = []

def register_mq_handler(topic, callback_func):
    """API để đăng ký hàm xử lý sự kiện P2P"""
    mq_callbacks[topic] = callback_func

def send_p2p(topic, payload):
    """API để bắn tin nhắn P2P ra mạng lưới"""
    if pub_socket:
        pub_socket.send_json({"topic": topic, "payload": payload})

# ============================================================
# CƠ CHẾ DISCOVERY (CẬP NHẬT DANH BẠ TỪ TRACKER)
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
                # Chỉ kết nối tới Peer khác mình
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
# CÁC HÀM COROUTINE XỬ LÝ I/O
# ============================================================
def handle_client_coroutine(conn, addr, routes, poller):
    """Coroutine đọc dữ liệu HTTP (TCP Thuần)"""
    data = b''
    fd = conn.fileno()
    while True:
        yield 'read', fd
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
            print(f"[HTTP Error] {e}")

    # Xong việc, gỡ theo dõi khỏi Poller và đóng kết nối
    poller.unregister(fd)
    conn.close()

def accept_coroutine(server_sock, routes, poller):
    """Coroutine chờ kết nối HTTP mới"""
    while True:
        yield 'read', server_sock.fileno()
        try:
            conn, addr = server_sock.accept()
            conn.setblocking(False)
            poller.register(conn.fileno(), zmq.POLLIN)
            # Yêu cầu Event Loop thêm task mới
            yield 'new_task', handle_client_coroutine(conn, addr, routes, poller)
        except BlockingIOError:
            pass

def receive_zmq_coroutine(sub_socket):
    """Coroutine chờ tin nhắn ZMQ P2P mới"""
    while True:
        yield 'read', sub_socket
        try:
            msg = sub_socket.recv_json(flags=zmq.NOBLOCK)
            topic, payload = msg.get("topic"), msg.get("payload")
            if topic in mq_callbacks:
                mq_callbacks[topic](payload)
        except zmq.error.Again:
            pass
        except Exception:
            pass

# ============================================================
# ENTRY POINT CỦA BACKEND
# ============================================================
def create_backend(ip, port, routes={}):
    global pub_socket
    print(f"\n{'='*55}")
    print(f"🚀 KHỞI ĐỘNG ASYNAPROUS BROKERLESS BACKEND (UNIFIED)")
    print(f"🌐 HTTP Web Server đang lắng nghe tại  : {ip}:{port}")
    
    # 1. Khởi tạo HTTP Server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((ip, int(port)))
    server.listen(100)
    server.setblocking(False)

    # 2. Khởi tạo ZeroMQ P2P
    zmq_port = int(port) + 1000
    context = zmq.Context()
    pub_socket = context.socket(zmq.PUB)
    pub_socket.bind(f"tcp://*:{zmq_port}")
    print(f"⚡ Kênh Chat P2P (ZMQ) sẵn sàng tại cổng : {zmq_port}")
    print(f"{'='*55}\n")
    
    sub_socket = context.socket(zmq.SUB)
    sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")

    # 3. Kích hoạt luồng Sync Danh bạ P2P ngầm
    threading.Thread(target=_tracker_sync_worker, args=(context, port, zmq_port, sub_socket), daemon=True).start()

    # 4. Thiết lập Unified Poller (Giám sát đồng thời Web & ZMQ)
    poller = zmq.Poller()
    poller.register(server.fileno(), zmq.POLLIN)
    poller.register(sub_socket, zmq.POLLIN)

    tasks = []
    coro_readers = {}

    # Nạp 2 Coroutine chính yếu vào Event Loop
    tasks.append(accept_coroutine(server, routes, poller))
    tasks.append(receive_zmq_coroutine(sub_socket))

    # 5. VÒNG LẶP SỰ KIỆN TRUNG TÂM
    while tasks or coro_readers:
        while tasks:
            task = tasks.pop(0)
            try:
                op, val = next(task)
                if op == 'read':
                    coro_readers[val] = task 
                elif op == 'new_task':
                    # Đẩy task xử lý client mới vào danh sách, đồng thời đưa task accept quay lại
                    tasks.append(val)
                    tasks.append(task)
            except StopIteration:
                pass
        
        if not coro_readers: break
        
        # ZMQ Poller phát huy sức mạnh: Chờ cả Web và Chat
        events = poller.poll(timeout=100)
        
        for obj, state in events:
            if state & zmq.POLLIN:
                # obj có thể là fileno (int) của socket TCP, hoặc là sub_socket của ZMQ
                if obj in coro_readers:
                    tasks.append(coro_readers.pop(obj))