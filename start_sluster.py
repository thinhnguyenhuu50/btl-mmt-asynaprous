import subprocess
import time
import sys

BACKEND_PORTS = [9000, 9001, 9002, 9003, 9004, 9005]
processes = []

print("🚀 Đang khởi động hệ thống Smart Cluster...")

try:
    print(" 🚦 Bật Proxy (Port 80)...")
    processes.append(subprocess.Popen([sys.executable, "start_proxy.py"]))
    time.sleep(1) 

    for port in BACKEND_PORTS:
        print(f" ⚙️ Bật Backend Node (Port {port})...")
        # Sử dụng tham số command line --server-port chuẩn chỉnh
        processes.append(subprocess.Popen([sys.executable, "start_chatapp.py", "--server-port", str(port)]))
        time.sleep(0.5)

    print("\n✅ Cụm 6 Backend và 1 Proxy đã lên sóng! Nhấn Ctrl+C để tắt toàn bộ.")
    
    while True: time.sleep(1)

except KeyboardInterrupt:
    print("\n🛑 Đang tắt toàn bộ hệ thống...")
    for p in processes: p.terminate()
    print("Đã dọn dẹp xong!")