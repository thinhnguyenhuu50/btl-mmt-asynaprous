import zmq

def run_tracker(port=80):
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    
    try:
        socket.bind(f"tcp://*:{port}")
        print(f"[*] ZMQ Tracker (Danh bạ) đang chạy tại cổng {port}...")
        print("[*] Tắt tracker này đi thì các Peer đã kết nối vẫn chat được trực tiếp (P2P)!\n")
    except zmq.error.ZMQError as e:
        print(f"[!] Lỗi: Không thể chạy trên cổng {port}. Hãy chắc chắn bạn đã tắt start_proxy.py cũ đi nhé!")
        return

    peers = {} # Cấu trúc: { "peer_id": {"ip": "127.0.0.1", "zmq_port": 9001} }

    while True:
        try:
            # Lắng nghe yêu cầu đăng ký từ các App
            message = socket.recv_json()
            action = message.get("action")

            if action == "register":
                peer_id = message.get("peer_id")
                peers[peer_id] = {
                    "ip": message.get("ip"),
                    "zmq_port": message.get("zmq_port")
                }
                print(f"[Tracker] Peer mới đăng ký: {peer_id} | ZMQ Port nội bộ: {message.get('zmq_port')}")
                
                # Trả về toàn bộ danh bạ cho người vừa đăng ký
                socket.send_json({"status": "ok", "peers": peers})

            elif action == "get_peers":
                # Trả về danh bạ khi được hỏi
                socket.send_json({"status": "ok", "peers": peers})
        
        except KeyboardInterrupt:
            print("\nĐang tắt Tracker...")
            break
        except Exception as e:
            print(f"Lỗi xử lý tin nhắn: {e}")
            socket.send_json({"status": "error"})

if __name__ == "__main__":
    run_tracker()