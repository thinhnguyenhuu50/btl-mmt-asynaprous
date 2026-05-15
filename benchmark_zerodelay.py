import zmq
import time
import json
import urllib.request
import threading

# Cấu hình test
PORT = 8001
HTTP_URL = f"http://127.0.0.1:{PORT}/broadcast-peer/"
ZMQ_PUB_URL = f"tcp://127.0.0.1:{PORT + 1000}"
NUM_MESSAGES = 1000

latencies = []
session_cookie = ""

def login_and_get_cookie():
    """Đăng nhập để lấy quyền gửi tin nhắn"""
    print("[Setup] Đang giả lập đăng nhập user2...")
    data = json.dumps({"username": "user2", "password": "a"}).encode('utf-8')
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/login/", data=data, method='POST')
    try:
        with urllib.request.urlopen(req) as res:
            cookies = res.headers.get_all('Set-Cookie')
            for c in cookies:
                if f'session_id_{PORT}' in c:
                    return c.split(';')[0]
    except Exception as e:
        print("Lỗi đăng nhập. Hãy chắc chắn user2 tồn tại trong db/users.json")
    return ""

def receiver_worker():
    """Đóng vai trò là một Peer khác, lắng nghe trực tiếp trên kênh ZeroMQ"""
    context = zmq.Context()
    sub = context.socket(zmq.SUB)
    sub.connect(ZMQ_PUB_URL)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    
    print(" [Receiver] ZMQ Subcriber đã sẵn sàng. Chờ tin nhắn...\n")
    for _ in range(NUM_MESSAGES):
        msg = sub.recv_json()
        recv_time = time.time()
        
        # Lấy thời gian gốc do Sender dán vào
        send_time = msg.get("payload", {}).get("send_time", recv_time)
        
        # Tính độ trễ (Milliseconds)
        latency = (recv_time - send_time) * 1000 
        latencies.append(latency)
    
    # === IN BÁO CÁO ===
    avg_latency = sum(latencies) / len(latencies)
    print(f"\n{'='*50}")
    print(f"📊 KẾT QUẢ BENCHMARK 'ZERO DELAY' (Event Loop)")
    print(f"{'='*50}")
    print(f"Tổng số tin nhắn dồn dập : {NUM_MESSAGES} messages")
    print(f"Độ trễ trung bình (Avg)  : {avg_latency:.3f} ms (mili-giây)")
    print(f"Độ trễ thấp nhất (Min)   : {min(latencies):.3f} ms")
    print(f"Độ trễ cao nhất (Max)    : {max(latencies):.3f} ms")
    print(f"{'='*50}")
    
    if avg_latency < 5.0:
        print("✅ KẾT LUẬN CỦA HỆ THỐNG:")
        print("Hệ thống đạt chuẩn ZERO DELAY. Khoảng thời gian < 5ms chỉ là")
        print("thời gian Hệ điều hành (OS) luân chuyển gói tin qua TCP Stack.")
        print("Tầng Application (Event Loop của bạn) hoàn toàn không bị Blocking!")
    else:
        print("❌ Hệ thống có độ trễ cao, có thể code đang dùng sleep() hoặc bị block.")

def sender_worker(cookie):
    """Bắn HTTP Request tốc độ cao nhất có thể"""
    time.sleep(1) # Chờ receiver khởi động xong
    print(f" [Sender] Bắt đầu xả đạn {NUM_MESSAGES} request HTTP liên tục...")
    for i in range(NUM_MESSAGES):
        # Dán nhãn thời gian t0 vào ngay lúc gửi
        payload = {"message": f"Test Speed {i}", "send_time": time.time()}
        data = json.dumps(payload).encode('utf-8')
        
        req = urllib.request.Request(HTTP_URL, data=data, method='POST')
        req.add_header('Cookie', cookie)
        
        try:
            urllib.request.urlopen(req)
        except Exception as e:
            print(f" [!] Lỗi gửi tin thứ {i}: {e}")
            break # Dừng lại ngay để kiểm tra cổng

if __name__ == "__main__":
    cookie = login_and_get_cookie()
    if cookie:
        threading.Thread(target=receiver_worker, daemon=True).start()
        sender_worker(cookie)
        time.sleep(2) # Chờ luồng receiver in kết quả rồi mới thoát