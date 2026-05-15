# # File: daemon/mq.py
# import zmq
# import threading
# import time

# MODE = "coroutine"  # Hỗ trợ: "thread", "callback", "coroutine"

# class MessageQueueInterface:
#     def __init__(self, port, tracker_url="tcp://127.0.0.1:80"):
#         self.http_port = port
#         self.zmq_port = port + 1000
#         self.tracker_url = tracker_url
#         self.context = zmq.Context()
        
#         # Socket phát (PUB)
#         self.pub_socket = self.context.socket(zmq.PUB)
#         self.pub_socket.bind(f"tcp://*:{self.zmq_port}")
        
#         # Socket nhận (SUB)
#         self.sub_socket = self.context.socket(zmq.SUB)
#         self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        
#         self.connected_peers = set()
#         self.callbacks = {}
#         self.known_peers_list = [] # Lưu danh sách port để App làm Heartbeat
        
#         # Poller - Tương đương với select.select dùng cho ZeroMQ
#         self.poller = zmq.Poller()
#         self.poller.register(self.sub_socket, zmq.POLLIN)

#     def register_handler(self, topic, callback_func):
#         self.callbacks[topic] = callback_func

#     def send(self, topic, payload):
#         # Đóng gói gói tin có chứa Topic
#         self.pub_socket.send_json({"topic": topic, "payload": payload})

#     def start(self):
#         # Tracker luôn chạy ngầm để lấy danh bạ
#         threading.Thread(target=self._tracker_sync_worker, daemon=True).start()
        
#         print(f" [MQ] Đang chạy Message Queue với MODE = {MODE.upper()}")
        
#         # Chạy Event Loop theo cấu hình MODE
#         if MODE == "thread":
#             threading.Thread(target=self._receive_thread, daemon=True).start()
#         elif MODE == "callback":
#             threading.Thread(target=self._receive_callback, daemon=True).start()
#         elif MODE == "coroutine":
#             threading.Thread(target=self._receive_coroutine, daemon=True).start()

#     def _process_message(self):
#         """Hàm dùng chung để đọc và gọi logic ứng dụng khi có tin nhắn"""
#         msg = self.sub_socket.recv_json(flags=zmq.NOBLOCK)
#         topic, payload = msg.get("topic"), msg.get("payload")
#         if topic in self.callbacks:
#             self.callbacks[topic](payload)

#     # ==========================================
#     # CƠ CHẾ 1: THREAD (Vòng lặp sleep chủ động)
#     # ==========================================
#     def _receive_thread(self):
#         while True:
#             try:
#                 self._process_message()
#             except zmq.error.Again:
#                 time.sleep(0.02)
#             except Exception:
#                 pass

#     # ==========================================
#     # CƠ CHẾ 2: CALLBACK (Event Loop thủ công)
#     # ==========================================
#     def _receive_callback(self):
#         callback_readers = {}
        
#         # Đăng ký hàm sẽ chạy khi socket có dữ liệu
#         callback_readers[self.sub_socket] = lambda: self._process_message()

#         while True:
#             # Tương tự select.select()
#             socks = dict(self.poller.poll(timeout=1000))
            
#             for sock, state in socks.items():
#                 if state == zmq.POLLIN and sock in callback_readers:
#                     try:
#                         callback_readers[sock]() # Kích hoạt callback
#                     except: pass

#     # ==========================================
#     # CƠ CHẾ 3: COROUTINE (Generator Yield thủ công)
#     # ==========================================
#     def _receive_coroutine(self):
#         tasks = []
#         coro_readers = {}

#         # Hàm Generator Yield
#         def receiver_task():
#             while True:
#                 yield 'read', self.sub_socket
#                 try:
#                     self._process_message()
#                 except: pass

#         tasks.append(receiver_task())

#         # Vòng lặp điều phối Coroutine (Giống hệt backend.py)
#         while tasks or coro_readers:
#             while tasks:
#                 task = tasks.pop(0)
#                 try:
#                     op, sock = next(task)
#                     if op == 'read':
#                         coro_readers[sock] = task # Tạm dừng, chờ có dữ liệu
#                 except StopIteration:
#                     pass
            
#             if not coro_readers: break
            
#             # Chờ sự kiện từ ZMQ (thay vì select.select)
#             socks = dict(self.poller.poll(timeout=1000))
            
#             for sock, state in socks.items():
#                 if state == zmq.POLLIN and sock in coro_readers:
#                     # Có dữ liệu -> Đánh thức Coroutine tiếp tục chạy
#                     tasks.append(coro_readers.pop(sock))

#     # ==========================================
#     # TRACKER SYNC (Giữ nguyên)
#     # ==========================================
#     def _tracker_sync_worker(self):
#         """Tự động kết nối P2P tới các Peer mới từ Tracker"""
#         while True:
#             req = self.context.socket(zmq.REQ)
#             req.RCVTIMEO = 2000
#             try:
#                 req.connect(self.tracker_url)
#                 req.send_json({
#                     "action": "register", "peer_id": f"peer_{self.http_port}",
#                     "ip": "127.0.0.1", "zmq_port": self.zmq_port
#                 })
#                 res = req.recv_json()
#                 peers = res.get("peers", {})
                
#                 ports = []
#                 for pid, info in peers.items():
#                     p_port = info["zmq_port"] - 1000
#                     ports.append(p_port)
#                     if info["zmq_port"] != self.zmq_port:
#                         url = f"tcp://{info['ip']}:{info['zmq_port']}"
#                         if url not in self.connected_peers:
#                             self.sub_socket.connect(url)
#                             self.connected_peers.add(url)
#                 self.known_peers_list = ports
#             except: pass
#             finally: req.close()
#             time.sleep(5)