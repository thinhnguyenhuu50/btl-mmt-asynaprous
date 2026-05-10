import sys
import os
import json
import time
import socket
import threading
import uuid
import urllib.request
import hashlib
import zmq  # <-- THƯ VIỆN ZEROMQ

from daemon import AsynapRous
from daemon.auth import (
    authenticate, create_session, validate_session,
    get_session_username, build_auth_challenge
)

app = AsynapRous()
CURRENT_PORT = 9000 
CURRENT_USERNAME = None  

TRACKER_URL = "http://127.0.0.1:80"

active_peers_cache = [] 
last_tracker_sync = 0
online_status_cache = {} 
channel_states = {} 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# LỚP MẠNG ZEROMQ (BROKERLESS P2P MESH LAYER)
# ============================================================
class ZMQNetworkManager:
    def __init__(self, port):
        self.context = zmq.Context()
        self.http_port = port
        self.pub_port = port + 1000  # Cổng phát sóng ZMQ
        
        # Socket PUB: Phát dữ liệu (zero-delay) cho toàn mạng
        self.pub_socket = self.context.socket(zmq.PUB)
        self.pub_socket.bind(f"tcp://0.0.0.0:{self.pub_port}")
        
        # Socket SUB: Lắng nghe mọi tin nhắn từ các Peer khác
        self.sub_socket = self.context.socket(zmq.SUB)
        self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        
        self.poller = zmq.Poller()
        self.poller.register(self.sub_socket, zmq.POLLIN)
        self.connected_peers = set()

    def update_peers(self, active_ports):
        """Tự động kết nối Socket SUB tới các node mới xuất hiện"""
        for p in active_ports:
            if p != self.http_port and p not in self.connected_peers:
                target_pub_port = p + 1000
                self.sub_socket.connect(f"tcp://127.0.0.1:{target_pub_port}")
                self.connected_peers.add(p)
                print(f" [ZMQ Mesh] Đã thiết lập luồng trực tiếp với Node Port: {target_pub_port}")

    def broadcast(self, endpoint, data):
        """Đẩy bản tin trạng thái xuống tầng mạng P2P"""
        msg = json.dumps({"endpoint": endpoint, "data": data})
        self.pub_socket.send_string(msg)

    def listen_loop(self):
        print(f" [ZMQ] Backend Brokerless chạy ngầm ở port {self.pub_port}")
        while True:
            socks = dict(self.poller.poll(1000))
            if self.sub_socket in socks:
                raw = self.sub_socket.recv_string()
                try:
                    msg = json.loads(raw)
                    handle_zmq_sync(msg['endpoint'], msg['data'])
                except Exception as e:
                    pass

zmq_network = None

# Hàm nhận dữ liệu siêu tốc từ mạng P2P ZeroMQ
def handle_zmq_sync(endpoint, data):
    if endpoint == '/broadcast-peer/': do_broadcast(data)
    elif endpoint == '/send-peer/': do_send_dm(data)
    elif endpoint == '/signal-read/': do_signal_read(data)
    elif endpoint == '/signal-typing/': do_signal_typing(data)
    elif endpoint == '/create-channel/': do_create_channel(data)

# ============================================================
# LOGIC LƯU TRỮ DỮ LIỆU DB CÁCH LY
# ============================================================
_db_lock = threading.RLock()

def get_cache_file(): return os.path.join(BASE_DIR, f"peers_cache_{CURRENT_PORT}.json")
def get_db_dir():
    db_dir = os.path.join(BASE_DIR, f"user_databases_{CURRENT_PORT}")
    if not os.path.exists(db_dir): os.makedirs(db_dir)
    return db_dir
def get_session_file(): return os.path.join(BASE_DIR, f"sessions_{CURRENT_PORT}.json")

def load_peers_cache():
    global active_peers_cache
    try:
        if os.path.exists(get_cache_file()):
            with open(get_cache_file(), 'r') as f: active_peers_cache = json.load(f)
    except: pass

def save_peers_cache():
    try:
        with open(get_cache_file(), 'w') as f: json.dump(active_peers_cache, f)
    except: pass

def get_valid_username(cookies):
    session_id = cookies.get(f'session_id_{CURRENT_PORT}') or cookies.get('session_id')
    if not session_id: return None
    username = validate_session(session_id)
    if username: return username
    with _db_lock:
        try:
            s_file = get_session_file()
            if os.path.exists(s_file):
                with open(s_file, 'r', encoding='utf-8') as f: return json.load(f).get(session_id)
        except: pass
    return None

def save_shared_session(session_id, username):
    with _db_lock:
        try:
            s_file = get_session_file()
            sessions = {}
            if os.path.exists(s_file):
                with open(s_file, 'r', encoding='utf-8') as f: sessions = json.load(f)
            sessions[session_id] = username
            tmp_file = f"{s_file}.tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f: json.dump(sessions, f)
            os.replace(tmp_file, s_file)
        except: pass

def get_db_file(username): return os.path.join(get_db_dir(), f"db_{username}.json")

def load_db(username):
    if not username: return {"general": {"members": [], "messages": []}}
    db_file = get_db_file(username)
    with _db_lock:
        if not os.path.exists(db_file):
            data = {"general": {"members": [], "messages": []}}
            save_db(username, data)
            return data
        try:
            with open(db_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "general" not in data: data["general"] = {"members": [], "messages": []}
                return data
        except: return {"general": {"members": [], "messages": []}}

def save_db(username, data):
    if not username: return
    db_file = get_db_file(username)
    tmp_file = f"{db_file}.tmp"
    with _db_lock:
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp_file, db_file) 
        except: pass

def _decode_body(body): return body.decode('utf-8') if isinstance(body, bytes) else body
def _json_response(data, status="success"): return json.dumps({"status": status, "data": data})
def _error_response(message): return json.dumps({"status": "error", "message": message})

# ============================================================
# CÁC HÀM XỬ LÝ ĐỒNG BỘ TRẠNG THÁI (DÙNG CHUNG CHO HTTP VÀ ZMQ)
# ============================================================
def do_broadcast(data):
    from_user, message, channel = data.get('from', ''), data.get('message', ''), data.get('channel', 'general')
    msg_ts = data.get('timestamp', time.time())
    msg_id = data.get('msg_id')

    all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")]
    for u in all_users:
        db = load_db(u)
        if channel not in db: db[channel] = {"members": [], "messages": []}
        if db[channel].get('is_private', False) and from_user not in db[channel].get('allowed_members', []): continue
        if not any(m.get('msg_id') == msg_id for m in db[channel]["messages"][-50:]):
            db[channel]["messages"].append({
                "msg_id": msg_id, "from": from_user, "text": message, "timestamp": msg_ts, "channel": channel
            })
        save_db(u, db)

def do_send_dm(data):
    from_user, to_user, message = data.get('from', ''), data.get('to', ''), data.get('message', '')
    msg_ts = data.get('timestamp', time.time())
    msg_id = data.get('msg_id')
    dm_channel = "dm:{}<->{}".format(*sorted([from_user, to_user]))

    for u in [from_user, to_user]:
        db = load_db(u)
        if dm_channel not in db: db[dm_channel] = {"members": sorted([from_user, to_user]), "messages": []}
        if not any(m.get('msg_id') == msg_id for m in db[dm_channel]["messages"][-50:]):
            db[dm_channel]["messages"].append({
                "msg_id": msg_id, "from": from_user, "to": to_user, "text": message, "timestamp": msg_ts
            })
        save_db(u, db)

def do_signal_read(data):
    channel = data.get('channel', 'general')
    username = data.get('username')
    ts = float(data.get('timestamp', 0))
    if channel not in channel_states: channel_states[channel] = {'typing': {}, 'reads': {}}
    if username: channel_states[channel]['reads'][username] = ts

def do_signal_typing(data):
    channel = data.get('channel', 'general')
    username = data.get('username')
    if channel not in channel_states: channel_states[channel] = {'typing': {}, 'reads': {}}
    if username: channel_states[channel]['typing'][username] = time.time()

def do_create_channel(data):
    name, creator = data.get('name', ''), data.get('creator', '')
    is_private = data.get('is_private', False)
    allowed_members = data.get('allowed_members', [])
    if creator and creator not in allowed_members: allowed_members.append(creator)

    all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")]
    for u in all_users:
        db = load_db(u)
        if name not in db:
            db[name] = {"members": [creator] if creator else [], "messages": [], "is_private": is_private, "allowed_members": allowed_members}
            save_db(u, db)

# ============================================================
# CÁC ROUTE CHỨC NĂNG CHAT (KÍCH HOẠT ĐỒNG BỘ ZMQ)
# ============================================================
@app.route('/login/', methods=['GET', 'POST'])
def login(headers="guest", body="anonymous", cookies=None):
    global CURRENT_USERNAME
    try:
        data = json.loads(_decode_body(body)) if body != "anonymous" else {}
        username, password = data.get('username', ''), data.get('password', '')

        if authenticate(username, password):
            CURRENT_USERNAME = username
            session_id = create_session(username)
            save_shared_session(session_id, username)
            load_db(username) 
            
            set_cookies = [
                f"session_id_{CURRENT_PORT}={session_id}; Path=/; HttpOnly",
                f"session_id={session_id}; Path=/; HttpOnly"
            ]
            return (_json_response({"username": username, "session_id": session_id}), set_cookies)
        return _error_response("Sai tài khoản")
    except Exception as e: return _error_response(str(e))

@app.route('/whoami/', methods=['GET', 'POST'])
def whoami(headers="guest", body="anonymous", cookies=None):
    if not get_valid_username(cookies): return _error_response("401 Unauthorized")
    return _json_response({"username": CURRENT_USERNAME})

@app.route('/ping/', methods=['GET', 'POST'])
def ping(headers="guest", body="anonymous", cookies=None):
    return _json_response({"username": CURRENT_USERNAME}) if CURRENT_USERNAME else _error_response("Not logged in yet")

@app.route('/submit-info/', methods=['POST'])
def submit_info(headers="guest", body="anonymous", cookies=None):
    global CURRENT_USERNAME
    try:
        data = json.loads(_decode_body(body))
        if data.get('username'): CURRENT_USERNAME = data.get('username')
        threading.Thread(target=register_to_tracker, daemon=True).start()
        return _json_response({"status": "ok"})
    except Exception as e: return _error_response(str(e))

@app.route('/channels/', methods=['POST', 'GET'])
def list_channels(headers="guest", body="anonymous", cookies=None): 
    try:
        username = get_valid_username(cookies) 
        if not username: return _error_response("401 Unauthorized")

        db = load_db(username)
        channel_list = []
        for n, i in db.items():
            is_dm = n.startswith('dm:')
            is_private = i.get('is_private', False)
            allowed_members = i.get('allowed_members', [])
            if is_private and not is_dm and username not in allowed_members: continue

            channel_list.append({
                "name": n, "member_count": len(i.get("members", [])), 
                "message_count": len(i.get("messages", [])), "is_dm": is_dm, "is_private": is_private 
            })
        return _json_response({"channels": channel_list})
    except: return _json_response({"channels": []})

@app.route('/messages/', methods=['POST'])
def fetch_messages(headers="guest", body="anonymous", cookies=None):
    try:
        username = get_valid_username(cookies) 
        if not username: return _error_response("401 Unauthorized")

        data = json.loads(_decode_body(body))
        channel_name, since_ts = data.get('channel', 'general'), float(data.get('since', 0))
        
        db = load_db(username)
        channel_data = db.get(channel_name, {})
        if channel_data.get('is_private', False) and username not in channel_data.get('allowed_members', []):
            return _json_response({"messages": [], "error": "Truy cập bị từ chối"})

        msgs = channel_data.get('messages', [])
        new_msgs = [m for m in msgs if float(m.get('timestamp', 0)) > since_ts]
        last_ts = max((float(m.get('timestamp', 0)) for m in new_msgs), default=since_ts)
        
        c_state = channel_states.get(channel_name, {'typing': {}, 'reads': {}})
        active_typers = [u for u, t in c_state.get('typing', {}).items() if time.time() - t < 3]
        
        return _json_response({"messages": new_msgs, "typing": active_typers, "reads": c_state.get('reads', {}), "last_ts": last_ts})
    except: return _json_response({"messages": []})

@app.route('/broadcast-peer/', methods=['POST'])
def broadcast_peer(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        username = get_valid_username(cookies)
        if not username: return _error_response("401 Unauthorized")

        msg_id = hashlib.md5(f"{data.get('from')}{data.get('message')}{data.get('channel')}{uuid.uuid4().hex}".encode()).hexdigest()
        data.update({"msg_id": msg_id, "timestamp": time.time(), "sender_port": CURRENT_PORT})
        
        do_broadcast(data)
        if zmq_network: zmq_network.broadcast('/broadcast-peer/', data)

        return _json_response({"message": "Sent", "msg_id": msg_id})
    except: return _error_response("Lỗi")

@app.route('/send-peer/', methods=['POST'])
def send_peer(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        username = get_valid_username(cookies)
        if not username: return _error_response("401 Unauthorized")

        msg_id = hashlib.md5(f"dm|{data.get('from')}{data.get('to')}{data.get('message')}{uuid.uuid4().hex}".encode()).hexdigest()
        data.update({"msg_id": msg_id, "timestamp": time.time(), "sender_port": CURRENT_PORT})

        do_send_dm(data)
        if zmq_network: zmq_network.broadcast('/send-peer/', data)

        dm_channel = "dm:{}<->{}".format(*sorted([data.get('from'), data.get('to')]))
        return _json_response({"delivered_to": data.get('to'), "channel": dm_channel})
    except: return _error_response("Lỗi gửi DM")

@app.route('/create-channel/', methods=['POST'])
def create_channel(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        username = get_valid_username(cookies)
        if not username: return _error_response("401 Unauthorized")

        do_create_channel(data)
        if zmq_network: zmq_network.broadcast('/create-channel/', data)
        return _json_response({"channel": data.get('name')})
    except: return _error_response("Lỗi")

@app.route('/signal-read/', methods=['POST'])
def signal_read(headers="guest", body="anonymous", cookies=None):
    username = get_valid_username(cookies)
    if not username: return _error_response("401 Unauthorized")
    try:
        data = json.loads(_decode_body(body))
        data['username'] = username
        do_signal_read(data)
        if zmq_network: zmq_network.broadcast('/signal-read/', data)
        return _json_response({"status": "ok"})
    except: return _error_response("Lỗi")

@app.route('/signal-typing/', methods=['POST'])
def signal_typing(headers="guest", body="anonymous", cookies=None):
    username = get_valid_username(cookies)
    if not username: return _error_response("401 Unauthorized")
    try:
        data = json.loads(_decode_body(body))
        data['username'] = username
        do_signal_typing(data)
        if zmq_network: zmq_network.broadcast('/signal-typing/', data)
        return _json_response({"status": "ok"})
    except: return _error_response("Lỗi")

@app.route('/get-list/', methods=['GET', 'POST'])
def get_list(headers="guest", body="anonymous", cookies=None):
    if not get_valid_username(cookies): return _error_response("401 Unauthorized")
    global online_status_cache
    all_users = set([f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")])
    all_users.update([k for k, v in online_status_cache.items() if v])
    peer_dict = {u: {"peer_id": u, "username": u, "is_online": online_status_cache.get(u, False)} for u in all_users}
    return _json_response({"peers": list(peer_dict.values())})

# ============================================================
# CÁC LUỒNG TRACKER & HEARTBEAT NỀN
# ============================================================
def register_to_tracker():
    try:
        data = json.dumps({"port": CURRENT_PORT}).encode('utf-8')
        req = urllib.request.Request(f"{TRACKER_URL}/submit-info/", data=data, headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=1)
    except: pass

def get_active_peers(force_update=False):
    global active_peers_cache, last_tracker_sync
    if not active_peers_cache: load_peers_cache()
        
    if force_update or (time.time() - last_tracker_sync > 5): 
        try:
            req = urllib.request.Request(f"{TRACKER_URL}/get-list/")
            with urllib.request.urlopen(req, timeout=0.5) as res:
                data = json.loads(res.read().decode())
                new_peers = data.get("peers", active_peers_cache)
                if new_peers != active_peers_cache:
                    active_peers_cache = new_peers
                    save_peers_cache()
                last_tracker_sync = time.time()
        except: pass
    return active_peers_cache

def heartbeat_worker():
    global online_status_cache
    while True:
        time.sleep(3) 
        active_ports = get_active_peers(force_update=False)
        
        # Cập nhật danh bạ mạng ZeroMQ
        if zmq_network: zmq_network.update_peers(active_ports)

        new_status = {}
        for port in active_ports:
            if port == CURRENT_PORT: continue 
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/ping/")
                with urllib.request.urlopen(req, timeout=1.0) as res:
                    data = json.loads(res.read().decode())
                    if data.get("data", {}).get("username"): new_status[data["data"]["username"]] = True
            except: pass 
        online_status_cache = new_status

# ============================================================
# ENTRY POINT
# ============================================================
def create_chatapp(ip, port):
    global CURRENT_PORT, zmq_network
    CURRENT_PORT = port
    print(f" [ChatApp] Peer khởi động tại HTTP {ip}:{port}")
    
    # 1. Khởi chạy kiến trúc ZMQ P2P Mesh
    zmq_network = ZMQNetworkManager(port)
    threading.Thread(target=zmq_network.listen_loop, daemon=True).start()

    # 2. Khởi chạy Tracker & HTTP Server cũ
    load_peers_cache()
    threading.Thread(target=register_to_tracker, daemon=True).start()
    threading.Thread(target=heartbeat_worker, daemon=True).start() 
    
    app.prepare_address(ip, port)
    app.run()