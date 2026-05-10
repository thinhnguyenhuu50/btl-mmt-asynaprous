import zmq
import json
import time

class ZMQTracker:
    def __init__(self, port=8000):
        self.port = port
        self.active_peers = {}
        self.TIMEOUT = 60  # Tính bằng giây
        
        # Khởi tạo ZeroMQ Context và Socket loại REP (Reply)
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.bind(f"tcp://0.0.0.0:{self.port}")

    def run(self):
        print(f"🚀 [SERVER TRUNG TÂM ZMQ] Đang chạy tại tcp://0.0.0.0:{self.port}")
        print("Sẵn sàng nhận tín hiệu từ các Peer Node...")
        
        while True:
            try:
                # 1. Nhận yêu cầu từ ZMQ_REQ của các Peer
                message = self.socket.recv_string()
                data = json.loads(message)
                
                action = data.get('action')
                peer_port = data.get('port')
                peer_ip = data.get('ip', '127.0.0.1') # Mặc định localhost nếu không truyền
                
                now = time.time()
                
                # 2. Xử lý đăng ký / Heartbeat
                if action == 'register':
                    peer_address = f"{peer_ip}:{peer_port}"
                    
                    if peer_address not in self.active_peers:
                        print(f"📍 [Tracker] Node mới tham gia mạng: {peer_address}")
                    
                    # Cập nhật thời gian sống
                    self.active_peers[peer_address] = now
                
                # 3. Lọc danh sách các node còn sống (Ping trong vòng 60s qua)
                alive_peers = [p for p, t in self.active_peers.items() if now - t < self.TIMEOUT]
                
                # 4. Phản hồi lại danh sách cho Peer (Khớp với báo cáo LaTeX)
                response = json.dumps({"peers": alive_peers})
                self.socket.send_string(response)
                
            except Exception as e:
                print(f"⚠️ [Tracker Lỗi]: {e}")
                # ZMQ REP bắt buộc phải gửi phản hồi trước khi có thể nhận tiếp
                try:
                    self.socket.send_string(json.dumps({"error": str(e)}))
                except:
                    pass

if __name__ == '__main__':
    tracker = ZMQTracker(port=8000)
    tracker.run()