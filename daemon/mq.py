# File: daemon/mq.py
import zmq
import threading
import time

class MessageQueueInterface:
    def __init__(self, port, tracker_url="tcp://127.0.0.1:80"):
        self.http_port = port
        self.zmq_port = port + 1000
        self.tracker_url = tracker_url
        self.context = zmq.Context()
        
        # Socket phát (PUB)
        self.pub_socket = self.context.socket(zmq.PUB)
        self.pub_socket.bind(f"tcp://*:{self.zmq_port}")
        
        # Socket nhận (SUB)
        self.sub_socket = self.context.socket(zmq.SUB)
        self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        
        self.connected_peers = set()
        self.callbacks = {}
        self.known_peers_list = [] # Lưu danh sách port để App làm Heartbeat

    def register_handler(self, topic, callback_func):
        self.callbacks[topic] = callback_func

    def send(self, topic, payload):
        # Đóng gói gói tin có chứa Topic
        self.pub_socket.send_json({"topic": topic, "payload": payload})

    def start(self):
        threading.Thread(target=self._tracker_sync_worker, daemon=True).start()
        threading.Thread(target=self._receive_worker, daemon=True).start()

    def _receive_worker(self):
        while True:
            try:
                msg = self.sub_socket.recv_json(flags=zmq.NOBLOCK)
                topic, payload = msg.get("topic"), msg.get("payload")
                if topic in self.callbacks:
                    self.callbacks[topic](payload)
            except zmq.error.Again:
                time.sleep(0.02)
            except: pass

    def _tracker_sync_worker(self):
        """Tự động kết nối P2P tới các Peer mới từ Tracker"""
        while True:
            req = self.context.socket(zmq.REQ)
            req.RCVTIMEO = 2000
            try:
                req.connect(self.tracker_url)
                req.send_json({
                    "action": "register", "peer_id": f"peer_{self.http_port}",
                    "ip": "127.0.0.1", "zmq_port": self.zmq_port
                })
                res = req.recv_json()
                peers = res.get("peers", {})
                
                ports = []
                for pid, info in peers.items():
                    p_port = info["zmq_port"] - 1000
                    ports.append(p_port)
                    if info["zmq_port"] != self.zmq_port:
                        url = f"tcp://{info['ip']}:{info['zmq_port']}"
                        if url not in self.connected_peers:
                            self.sub_socket.connect(url)
                            self.connected_peers.add(url)
                self.known_peers_list = ports
            except: pass
            finally: req.close()
            time.sleep(5)