import zmq
import time
import json
import urllib.request
import threading
import statistics
import matplotlib.pyplot as plt # Import thư viện vẽ biểu đồ

# Cấu hình test
PORT = 8001
HTTP_URL = f"http://127.0.0.1:{PORT}/broadcast-peer/"
ZMQ_PUB_URL = f"tcp://127.0.0.1:{PORT + 1000}"
NUM_MESSAGES = 1000

latencies = []
session_cookie = ""
# Sử dụng Event để báo hiệu cho luồng chính khi đã nhận đủ tin nhắn
done_event = threading.Event()

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
    
    # === TÍNH TOÁN THỐNG KÊ ===
    avg_latency = statistics.mean(latencies)
    median_latency = statistics.median(latencies)
    min_latency = min(latencies)
    max_latency = max(latencies)
    
    # === IN BÁO CÁO ===
    print(f"\n{'='*50}")
    print(f"📊 KẾT QUẢ BENCHMARK 'ZERO DELAY' (Event Loop)")
    print(f"{'='*50}")
    print(f"Tổng số tin nhắn dồn dập : {NUM_MESSAGES} messages")
    print(f"Độ trễ trung bình (Avg)  : {avg_latency:.3f} ms")
    print(f"Độ trễ trung vị (Median) : {median_latency:.3f} ms")
    print(f"Độ trễ thấp nhất (Min)   : {min_latency:.3f} ms")
    print(f"Độ trễ cao nhất (Max)    : {max_latency:.3f} ms")
    print(f"{'='*50}")
    
    if avg_latency < 5.0:
        print("✅ KẾT LUẬN CỦA HỆ THỐNG:")
        print("Hệ thống đạt chuẩn ZERO DELAY. Khoảng thời gian < 5ms chỉ là")
        print("thời gian Hệ điều hành (OS) luân chuyển gói tin qua TCP Stack.")
        print("Tầng Application (Event Loop của bạn) hoàn toàn không bị Blocking!")
    else:
        print("❌ Hệ thống có độ trễ cao, có thể code đang dùng sleep() hoặc bị block.")
        
    # Phát tín hiệu báo luồng nhận đã hoàn thành nhiệm vụ
    done_event.set()

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

def plot_benchmark_results():
    """Hàm vẽ biểu đồ dựa trên dữ liệu độ trễ đã thu thập"""
    if not latencies:
        print("Không có dữ liệu để vẽ biểu đồ.")
        return

    avg_latency = statistics.mean(latencies)
    median_latency = statistics.median(latencies)
    min_latency = min(latencies)
    max_latency = max(latencies)

    # Khởi tạo khung biểu đồ
    plt.figure(figsize=(12, 6))
    
    # Vẽ đường biểu diễn độ trễ của từng tin nhắn
    plt.plot(latencies, label='Độ trễ từng tin (ms)', color='dodgerblue', alpha=0.7, linewidth=1.5)

    # Vẽ các đường ngang thể hiện các giá trị thống kê
    plt.axhline(avg_latency, color='green', linestyle='--', linewidth=2, label=f'Trung bình (Avg): {avg_latency:.3f} ms')
    plt.axhline(median_latency, color='orange', linestyle='-.', linewidth=2, label=f'Trung vị (Median): {median_latency:.3f} ms')
    plt.axhline(max_latency, color='red', linestyle=':', linewidth=2, label=f'Cao nhất (Max): {max_latency:.3f} ms')
    plt.axhline(min_latency, color='purple', linestyle=':', linewidth=2, label=f'Thấp nhất (Min): {min_latency:.3f} ms')

    # Định dạng và trang trí
    plt.title('Phân tích độ trễ bản tin mạng (Zero Delay Benchmark)', fontsize=15, fontweight='bold', pad=15)
    plt.xlabel('Thứ tự gói tin được nhận', fontsize=12)
    plt.ylabel('Thời gian trễ (Milliseconds)', fontsize=12)
    
    # Di chuyển bảng chú thích (legend) ra vị trí phù hợp
    plt.legend(loc='upper right', bbox_to_anchor=(1.15, 1))
    
    # Kẻ lưới để dễ nhìn giá trị
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout() # Tự động căn chỉnh lề tránh bị cắt chữ

    # Lưu lại biểu đồ làm tài liệu (Rất hữu ích để đưa vào báo cáo/đồ án)
    filename = 'benchmark_latency_chart.png'
    plt.savefig(filename, dpi=300)
    print(f"\n 📈 Đã lưu biểu đồ thành file '{filename}'")
    
    # Hiển thị cửa sổ biểu đồ
    plt.show()

if __name__ == "__main__":
    cookie = login_and_get_cookie()
    if cookie:
        # Chạy receiver trên một luồng riêng biệt
        receiver_thread = threading.Thread(target=receiver_worker, daemon=True)
        receiver_thread.start()
        
        # Chạy sender trên luồng chính
        sender_worker(cookie)
        
        # Luồng chính sẽ dừng lại chờ (tối đa 10s) cho đến khi receiver báo đã xử lý xong
        print("\nĐang chờ xử lý và vẽ biểu đồ...")
        done_event.wait(timeout=10.0) 
        
        # Tiến hành vẽ biểu đồ trên luồng chính
        plot_benchmark_results()