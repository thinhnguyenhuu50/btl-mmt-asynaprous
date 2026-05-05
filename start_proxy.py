import json
import urllib.request
import threading
import itertools
from daemon import AsynapRous

app = AsynapRous()

# Khởi tạo danh bạ
registered_peers = []
peer_cycle = None

def _decode_body(body):
    return body.decode('utf-8') if isinstance(body, bytes) else body

@app.route('/submit-info/', methods=['POST'])
def register_peer(headers, body, cookies=None):
    """Khi một Node (9000, 9001...) bật lên, nó sẽ báo danh về đây"""
    global registered_peers, peer_cycle
    try:
        data = json.loads(_decode_body(body))
        port = data.get('port')
        if port and port not in registered_peers:
            registered_peers.append(int(port))
            registered_peers.sort()
            peer_cycle = itertools.cycle(registered_peers)
            print(f" [Tracker] Peer {port} vừa gia nhập mạng lưới.")
        return json.dumps({"status": "success"})
    except:
        return json.dumps({"status": "error"})

@app.route('/get-list/', methods=['GET', 'POST'])
def get_peers(headers, body, cookies=None):
    """Trả về danh sách các Node đang sẵn sàng chat với nhau"""
    return json.dumps({"peers": registered_peers})

def get_target_backend(sender_port=None):
    global peer_cycle
    if not registered_peers: return None
    if sender_port:
        idx = int(sender_port) % len(registered_peers)
        return registered_peers[idx]
    return next(peer_cycle)

@app.route('/forward-broadcast/', methods=['POST'])
def forward_broadcast(headers, body, cookies=None):
    try:
        data = json.loads(_decode_body(body))
        data['from_proxy'] = True 
        sender_port = data.get('sender_port', 'Unknown')
        target_port = get_target_backend(sender_port)

        if not target_port: return json.dumps({"status": "error"})

        print(f" [Router] Định tuyến: Cổng {sender_port} -> Xử lý tại Backend {target_port}")
        payload = json.dumps(data).encode('utf-8')
        
        # Chạy ngầm để không block Peer
        def background_broadcast():
            for port in list(registered_peers):
                try:
                    req = urllib.request.Request(f"http://10.130.8.37:{port}/broadcast-peer/", 
                                               data=payload, headers={'Content-Type': 'application/json'}, method='POST')
                    urllib.request.urlopen(req, timeout=1.0)
                except: pass

        threading.Thread(target=background_broadcast, daemon=True).start()
        return json.dumps({"status": "ok"})
    except: return json.dumps({"status": "error"})

@app.route('/forward-dm/', methods=['POST'])
def forward_dm(headers, body, cookies=None):
    try:
        data = json.loads(_decode_body(body))
        data['from_proxy'] = True 
        payload = json.dumps(data).encode('utf-8')

        def background_dm():
            for port in list(registered_peers):
                try:
                    req = urllib.request.Request(f"http://10.130.8.37:{port}/send-peer/", 
                                               data=payload, headers={'Content-Type': 'application/json'}, method='POST')
                    urllib.request.urlopen(req, timeout=1.0)
                except: pass

        threading.Thread(target=background_dm, daemon=True).start()
        return json.dumps({"status": "ok"})
    except: return json.dumps({"status": "error"})

if __name__ == "__main__":
    print(" [Tracker Proxy] Đang chạy tại http://127.0.0.1:80 ...")
    app.prepare_address('10.130.8.37', 80)
    app.run()