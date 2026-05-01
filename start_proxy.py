# Tên file: start_proxy.py (hoặc tên file proxy của bạn)
import json
from daemon import AsynapRous

app = AsynapRous()

# Khởi tạo danh bạ mặc định
registered_peers = set()

def _decode_body(body):
    return body.decode('utf-8') if isinstance(body, bytes) else body

@app.route('/register', methods=['POST'])
def register_peer(headers, body, cookies=None):
    """Khi một Node (9000, 9001...) bật lên, nó sẽ tự động báo danh vào đây"""
    try:
        data = json.loads(_decode_body(body))
        port = data.get('port')
        if port:
            registered_peers.add(int(port))
            print(f"📡 [Tracker] Node {port} vừa gia nhập mạng lưới.")
        return json.dumps({"status": "success"})
    except:
        return json.dumps({"status": "error"})

@app.route('/peers', methods=['GET'])
def get_peers(headers, body, cookies=None):
    """Trả về danh sách các Node đang sống để các máy tự chat với nhau"""
    return json.dumps({"peers": list(registered_peers)})

if __name__ == "__main__":
    print("🧭 [Tracker Proxy] Đang chạy tại http://127.0.0.1:80 ...")
    app.prepare_address('127.0.0.1', 80)
    app.run()