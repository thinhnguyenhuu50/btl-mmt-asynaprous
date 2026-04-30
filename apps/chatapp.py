"""
This module implements the hybrid chat application based on AsynapRous.
It supports both Client-Server paradigm (Tracker for peer registration) 
and Peer-to-Peer paradigm (Direct chatting).
"""
import os
import json
import time
import urllib.request
import threading
import uuid
from daemon.asynaprous import AsynapRous

# Giả định bạn có module auth.py hỗ trợ xác thực.
# Nếu bạn chưa tạo file này, bạn có thể comment lại và dùng hàm mock bên dưới
from daemon.auth import authenticate, create_session 

app = AsynapRous()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRACKER_FILE = os.path.join(BASE_DIR, "tracker_peers.json")
DB_DIR = os.path.join(BASE_DIR, "user_databases")

if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)

# Khởi tạo một Database tạm trên RAM để UI có thể lấy dữ liệu hiển thị
channels_db = {
    "general": {"members": [], "messages": []}
}

def _decode_body(body):
    """Decodes the HTTP request body from bytes to string."""
    return body.decode('utf-8') if isinstance(body, bytes) else body

def _json_response(data, status="success"):
    """Formats a successful JSON response."""
    return json.dumps({"status": status, "data": data})

def _error_response(message):
    """Formats an error JSON response."""
    return json.dumps({"status": "error", "message": message})

def get_tracker_peers():
    """Retrieves the list of active peers from the tracker."""
    try:
        if os.path.exists(TRACKER_FILE):
            with open(TRACKER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_tracker_peers(peers):
    """Saves the list of active peers to the tracker file."""
    try:
        with open(TRACKER_FILE, 'w', encoding='utf-8') as f:
            json.dump(peers, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[Tracker] Error saving peers: {e}")

def fire_and_forget_p2p(req):
    """Thực thi request P2P trong luồng chạy ngầm để không block tiến trình chính"""
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass  # Bỏ qua lỗi nếu peer kia offline để không làm sập server

# ==========================================
# PHASE 1: CLIENT-SERVER PARADIGM (TRACKER)
# ==========================================

@app.route('/login/', methods=['GET', 'POST'])
def login(headers="guest", body="anonymous", cookies=None):
    """Handles user authentication and session creation."""
    try:
        data = json.loads(_decode_body(body)) if body != "anonymous" else {}
        username = data.get('username', '')
        password = data.get('password', '')
        
        if authenticate(username, password):
            session_id = create_session(username)
            return (_json_response({
                "username": username,
                "message": "Login successful"
            }), [f"session_id={session_id}; Path=/; HttpOnly"])
        return _error_response("Invalid credentials")
    except Exception as e:
        return _error_response(str(e))

@app.route('/submit-info/', methods=['POST'])
def submit_info(headers="guest", body="anonymous", cookies=None):
    """Registers a new peer's IP and port to the centralized tracker."""
    try:
        data = json.loads(_decode_body(body))
        username = data.get('username')
        ip = data.get('ip')
        port = data.get('port')
        
        if not all([username, ip, port]):
            return _error_response("Missing peer information")
            
        peers = get_tracker_peers()
        peers[username] = {"ip": ip, "port": port, "last_seen": time.time()}
        save_tracker_peers(peers)
        
        return _json_response({"message": "Peer registered successfully"})
    except Exception as e:
        return _error_response(str(e))

@app.route('/get-list/', methods=['GET', 'POST'])
def get_list(headers="guest", body="anonymous", cookies=None):
    """Allows peers to discover other active peers from the tracker."""
    peers_dict = get_tracker_peers()
    # Chuyển đổi từ dictionary sang dạng mảng JSON cho phía Frontend
    peers_list = [{"username": k, "ip": v["ip"], "port": v["port"]} for k, v in peers_dict.items()]
    return _json_response({"peers": peers_list})

# ==========================================
# CÁC API PHỤC VỤ HIỂN THỊ LÊN GIAO DIỆN CHAT
# ==========================================

@app.route('/channels/', methods=['GET', 'POST'])
def list_channels(headers="guest", body="anonymous", cookies=None):
    # Lấy tên user đang request danh sách kênh từ frontend
    data = json.loads(_decode_body(body)) if body != "anonymous" else {}
    current_user = data.get('username')

    ch_list = []
    for k, v in channels_db.items():
        if k.startswith("dm:"):
            # Nếu là kênh chat cá nhân, tách tên 2 người ra từ chuỗi (vd: user3<->user4)
            participants = k.replace("dm:", "").split("<->")
            # Nếu user hiện tại không nằm trong cuộc hội thoại này -> Bỏ qua
            if current_user and current_user not in participants:
                continue
                
        ch_list.append({
            "name": k, 
            "message_count": len(v["messages"]), 
            "is_dm": k.startswith("dm:")
        })
        
    return _json_response({"channels": ch_list})

@app.route('/messages/', methods=['POST'])
def fetch_messages(headers="guest", body="anonymous", cookies=None):
    data = json.loads(_decode_body(body))
    channel = data.get('channel', 'general')
    since = float(data.get('since', 0))
    msgs = channels_db.get(channel, {}).get("messages", [])
    return _json_response({"messages": [m for m in msgs if m.get("timestamp", 0) > since]})

@app.route('/create-channel/', methods=['POST'])
def create_channel(headers="guest", body="anonymous", cookies=None):
    name = json.loads(_decode_body(body)).get('name')
    if name and name not in channels_db:
        channels_db[name] = {"members": [], "messages": []}
    return _json_response({"channel": name})

# ==========================================
# PHASE 2: PEER-TO-PEER PARADIGM (CHATTING)
# ==========================================

@app.route('/connect-peer/', methods=['POST'])
def connect_peer(headers="guest", body="anonymous", cookies=None):
    """Initializes a direct P2P connection handshake between peers."""
    try:
        data = json.loads(_decode_body(body))
        from_peer = data.get('from_peer')
        return _json_response({"message": f"Connection accepted from {from_peer}"})
    except Exception as e:
        return _error_response(str(e))

@app.route('/send-peer/', methods=['POST'])
def send_peer(headers="guest", body="anonymous", cookies=None):
    """Receives a direct message from another peer without central routing."""
    try:
        data = json.loads(_decode_body(body))
        from_user, to_user, message = data.get('from'), data.get('to'), data.get('message')

        # Tạo ID duy nhất cho tin nhắn để chống trùng lặp
        msg_id = data.get('msg_id')
        if not msg_id:
            msg_id = str(uuid.uuid4())
            data['msg_id'] = msg_id
            
        timestamp = data.get('timestamp') or time.time()
        data['timestamp'] = timestamp

        print(f"[P2P Direct] Received message from {from_user}: {message}")

        # 1. Lưu tin nhắn vào RAM để hiển thị lên UI
        dm_id = f"dm:{'<->'.join(sorted([from_user, to_user]))}"
        if dm_id not in channels_db:
            channels_db[dm_id] = {"members": [from_user, to_user], "messages": []}
        
        # Chỉ thêm tin nhắn nếu nó chưa tồn tại (Chống lặp tin)
        existing_msgs = channels_db[dm_id]["messages"]
        if not any(m.get('msg_id') == msg_id for m in existing_msgs):
            msg_data = {"msg_id": msg_id, "from": from_user, "text": message, "timestamp": timestamp}
            channels_db[dm_id]["messages"].append(msg_data)

        # 2. Logic P2P: Bắn Request ngầm sang IP/Port của Peer khác
        if not data.get("is_forwarded"):
            target = get_tracker_peers().get(to_user)
            if target:
                url = f"http://{target['ip']}:{target['port']}/send-peer/"
                data["is_forwarded"] = True
                req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
                # Dùng Threading để không chặn luồng chính (Non-blocking)
                threading.Thread(target=fire_and_forget_p2p, args=(req,), daemon=True).start()

        return _json_response({"message": "Delivered successfully"})
    except Exception as e:
        return _error_response(str(e))

@app.route('/broadcast-peer/', methods=['POST'])
def broadcast_peer(headers="guest", body="anonymous", cookies=None):
    """Receives a broadcast message from a peer and forwards to others."""
    try:
        data = json.loads(_decode_body(body))
        from_user = data.get('from')
        message = data.get('message')
        channel = data.get('channel', 'general')

        # Tạo ID duy nhất để chống lặp
        msg_id = data.get('msg_id')
        if not msg_id:
            msg_id = str(uuid.uuid4())
            data['msg_id'] = msg_id
            
        timestamp = data.get('timestamp') or time.time()
        data['timestamp'] = timestamp

        print(f"[P2P Broadcast] {from_user} broadcasted: {message} in {channel}")

        # 1. Lưu tin nhắn vào RAM
        if channel not in channels_db:
            channels_db[channel] = {"members": [], "messages": []}
            
        # Kiểm tra trùng lặp trước khi thêm
        existing_msgs = channels_db[channel]["messages"]
        if not any(m.get('msg_id') == msg_id for m in existing_msgs):
            msg_data = {"msg_id": msg_id, "from": from_user, "text": message, "timestamp": timestamp}
            channels_db[channel]["messages"].append(msg_data)

        # 2. Logic P2P: Phát (Broadcast) ngầm
        if not data.get("is_forwarded"):
            data["is_forwarded"] = True 
            encoded_data = json.dumps(data).encode('utf-8')
            active_peers = get_tracker_peers()
            
            for peer_username, target in active_peers.items():
                if peer_username != from_user:
                    url = f"http://{target['ip']}:{target['port']}/broadcast-peer/"
                    req = urllib.request.Request(url, data=encoded_data, headers={'Content-Type': 'application/json'})
                    # Chạy ngầm việc gửi đi để đảm bảo hiệu suất cho người dùng hiện tại
                    threading.Thread(target=fire_and_forget_p2p, args=(req,), daemon=True).start()

        return _json_response({"message": "Broadcast received & forwarded"})
    except Exception as e:
        return _error_response(str(e))

def create_chatapp(ip, port):
    """Initializes and runs the Chat Application."""
    app.prepare_address(ip, port)
    app.run()