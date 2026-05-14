import sys
import os
import json
import time
import socket
import threading
import uuid
import urllib.request
import hashlib

from daemon import AsynapRous
from daemon.auth import (
    authenticate, create_session, validate_session,
    get_session_username, build_auth_challenge
)
# Nhúng Interface trừu tượng (Interface này che giấu hoàn toàn ZMQ)
from daemon.mq import MessageQueueInterface

app = AsynapRous()
CURRENT_PORT = 9000 
CURRENT_USERNAME = None  
mq = None 

# Trạng thái mạng lưới và giao diện
online_status_cache = {} 
channel_states = {} 
active_peers_cache = []

# ============================================================
# CƠ SỞ DỮ LIỆU CÁCH LY 
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_db_lock = threading.RLock()

def get_cache_file():
    return os.path.join(BASE_DIR, f"peers_cache_{CURRENT_PORT}.json")

def load_peers_cache():
    global active_peers_cache
    try:
        if os.path.exists(get_cache_file()):
            with open(get_cache_file(), 'r') as f:
                active_peers_cache = json.load(f)
    except: pass

def save_peers_cache():
    try:
        with open(get_cache_file(), 'w') as f:
            json.dump(active_peers_cache, f)
    except: pass

def get_db_dir():
    db_dir = os.path.join(BASE_DIR, f"user_databases_{CURRENT_PORT}")
    if not os.path.exists(db_dir): os.makedirs(db_dir)
    return db_dir

def get_session_file():
    return os.path.join(BASE_DIR, f"sessions_{CURRENT_PORT}.json")

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

def get_valid_username(cookies):
    session_id = cookies.get(f'session_id_{CURRENT_PORT}') or cookies.get('session_id')
    if not session_id: return None
    username = validate_session(session_id)
    if username: return username
    with _db_lock:
        try:
            s_file = get_session_file()
            if os.path.exists(s_file):
                with open(s_file, 'r', encoding='utf-8') as f:
                    return json.load(f).get(session_id)
        except: pass
    return None

def get_db_file(username):
    return os.path.join(get_db_dir(), f"db_{username}.json")

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

def _decode_body(body):
    return body.decode('utf-8') if isinstance(body, bytes) else body

def _json_response(data, status="success"):
    return json.dumps({"status": status, "data": data})

def _error_response(message):
    return json.dumps({"status": "error", "message": message})


# ============================================================
# CÁC HÀM XỬ LÝ (CALLBACKS) KHI MESSAGE QUEUE TRẢ VỀ DỮ LIỆU
# ============================================================
def process_msg(data, is_dm):
    from_u = data.get('from', '')
    msg = data.get('message', '')
    ts = data.get('timestamp')
    mid = data.get('msg_id')
    channel = data.get('channel', 'general')

    all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")]
    
    if is_dm:
        to_u = data.get('to', '')
        channel = "dm:{}<->{}".format(*sorted([from_u, to_u]))
        # FIX: Nếu là nhắn riêng, CHỈ cập nhật vào database của người gửi và người nhận
        target_users = [from_u, to_u]
    else:
        # Nếu là nhóm chat chung, cập nhật cho tất cả (hoặc những người trong nhóm)
        target_users = all_users

    for u in set(target_users):
        db = load_db(u)
        
        # Kiểm tra quyền: Nếu đây là nhóm kín (private), bỏ qua người ngoài
        if not is_dm and channel in db:
            ch_info = db[channel]
            if ch_info.get('is_private', False) and u not in ch_info.get('allowed_members', []):
                continue
        
        if channel not in db: 
            db[channel] = {"members": [], "messages": []}
        
        if not any(m.get('msg_id') == mid for m in db[channel]["messages"][-50:]):
            new_msg = {"msg_id": mid, "from": from_u, "text": msg, "timestamp": ts}
            if is_dm: 
                new_msg["to"] = data.get('to', '')
            else: 
                new_msg["channel"] = channel
            db[channel]["messages"].append(new_msg)
            
        save_db(u, db)

def on_broadcast(data):
    process_msg(data, is_dm=False)

def on_dm(data):
    process_msg(data, is_dm=True)

def on_create_channel(data):
    name = data.get('name', '')
    creator = data.get('creator', '')
    is_private = data.get('is_private', False)
    allowed_members = data.get('allowed_members', [])
    if creator and creator not in allowed_members: allowed_members.append(creator)

    all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")]
    for u in all_users:
        # FIX: Nếu tạo kênh private, chỉ những người được phép mới có kênh này trong DB
        if is_private and u not in allowed_members:
            continue
            
        db = load_db(u)
        if name not in db:
            db[name] = {
                "members": [creator] if creator else [], 
                "messages": [],
                "is_private": is_private,
                "allowed_members": allowed_members
            }
            save_db(u, db)

def on_typing(data):
    ch = data.get('channel', 'general')
    user = data.get('username')
    if ch not in channel_states: channel_states[ch] = {'typing': {}, 'reads': {}}
    channel_states[ch]['typing'][user] = time.time()

def on_read(data):
    ch = data.get('channel', 'general')
    user = data.get('username')
    ts = float(data.get('timestamp', 0))
    if ch not in channel_states: channel_states[ch] = {'typing': {}, 'reads': {}}
    channel_states[ch]['reads'][user] = ts


# ============================================================
# HEARTBEAT WORKER (Cập nhật online/offline)
# ============================================================
def heartbeat_worker():
    global online_status_cache
    while True:
        time.sleep(3) 
        # Lấy danh sách từ Message Queue Interface
        ports = mq.known_peers_list if mq else []
        new_status = {}
        for p in ports:
            if p == CURRENT_PORT: continue 
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{p}/ping/")
                with urllib.request.urlopen(req, timeout=1.0) as res:
                    d = json.loads(res.read().decode())
                    uname = d.get("data", {}).get("username")
                    if uname: new_status[uname] = True
            except Exception: pass 
        online_status_cache = new_status


# ============================================================
# CÁC ROUTE API CỦA ỨNG DỤNG (WEB HTTP)
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
    if CURRENT_USERNAME:
        return _json_response({"username": CURRENT_USERNAME})
    return _error_response("Not logged in yet")

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
            
            if is_private and not is_dm and username not in allowed_members:
                continue

            channel_list.append({
                "name": n, 
                "member_count": len(i.get("members", [])), 
                "message_count": len(i.get("messages", [])), 
                "is_dm": is_dm,
                "is_private": is_private 
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
        
        current_time = time.time()
        c_state = channel_states.get(channel_name, {'typing': {}, 'reads': {}})
        active_typers = [u for u, t in c_state.get('typing', {}).items() if current_time - t < 3]
        
        return _json_response({
            "messages": new_msgs, 
            "typing": active_typers, 
            "reads": c_state.get('reads', {}), 
            "last_ts": last_ts
        })
    except: return _json_response({"messages": []})

@app.route('/get-list/', methods=['GET', 'POST'])
def get_list(headers="guest", body="anonymous", cookies=None):
    if not get_valid_username(cookies): return _error_response("401 Unauthorized")

    global online_status_cache
    all_users = set([f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")])
    all_users.update([k for k, v in online_status_cache.items() if v])
    
    peer_dict = {u: {
        "peer_id": u, 
        "username": u, 
        "is_online": online_status_cache.get(u, False) 
    } for u in all_users}
            
    return _json_response({"peers": list(peer_dict.values())})

@app.route('/broadcast-peer/', methods=['POST'])
def broadcast_peer(headers="guest", body="anonymous", cookies=None):
    try:
        username = get_valid_username(cookies)
        if not username: return _error_response("401 Unauthorized")

        data = json.loads(_decode_body(body))
        data.update({
            "from": username,
            "msg_id": hashlib.md5(f"{uuid.uuid4().hex}".encode()).hexdigest(),
            "timestamp": time.time()
        })

        # 1. Lưu DB nội bộ
        on_broadcast(data)

        # 2. Phát cho mạng lưới qua Interface
        mq.send("CHAT_BROADCAST", data)

        return _json_response({"message": "Sent", "msg_id": data["msg_id"]})
    except: return _error_response("Lỗi")

@app.route('/send-peer/', methods=['POST'])
def send_peer(headers="guest", body="anonymous", cookies=None):
    try:
        username = get_valid_username(cookies)
        if not username: return _error_response("401 Unauthorized")

        data = json.loads(_decode_body(body))
        data.update({
            "from": username,
            "msg_id": hashlib.md5(f"dm|{uuid.uuid4().hex}".encode()).hexdigest(),
            "timestamp": time.time()
        })

        on_dm(data)
        mq.send("CHAT_DM", data)
        
        dm_channel = "dm:{}<->{}".format(*sorted([username, data.get('to')]))
        return _json_response({"delivered_to": data.get('to'), "channel": dm_channel})
    except: return _error_response("Lỗi gửi DM")

@app.route('/create-channel/', methods=['POST'])
def create_channel(headers="guest", body="anonymous", cookies=None):
    try:
        username = get_valid_username(cookies)
        if not username: return _error_response("401 Unauthorized")

        data = json.loads(_decode_body(body))
        on_create_channel(data)
        mq.send("CHANNEL_CREATE", data)
        return _json_response({"channel": data.get('name')})
    except: return _error_response("Lỗi")

@app.route('/signal-read/', methods=['POST'])
def signal_read(headers="guest", body="anonymous", cookies=None):
    username = get_valid_username(cookies)
    if not username: return _error_response("401 Unauthorized")
    try:
        data = json.loads(_decode_body(body))
        data['username'] = username
        on_read(data)
        mq.send("SIGNAL_READ", data)
        return _json_response({"status": "ok"})
    except: return _error_response("Lỗi")

@app.route('/signal-typing/', methods=['POST'])
def signal_typing(headers="guest", body="anonymous", cookies=None):
    username = get_valid_username(cookies)
    if not username: return _error_response("401 Unauthorized")
    try:
        data = json.loads(_decode_body(body))
        data['username'] = username
        on_typing(data)
        mq.send("SIGNAL_TYPING", data)
        return _json_response({"status": "ok"})
    except: return _error_response("Lỗi")

# ============================================================
# KHỞI CHẠY HỆ THỐNG
# ============================================================
def create_chatapp(ip, port):
    global CURRENT_PORT, mq
    CURRENT_PORT = port
    print(f" [ChatApp] Node khởi động tại HTTP {ip}:{port}")
    
    load_peers_cache()

    # 1. Khởi tạo đối tượng Interface Message Queue
    mq = MessageQueueInterface(port=CURRENT_PORT)
    
    # 2. Đăng ký các hàm hứng sự kiện
    mq.register_handler("CHAT_BROADCAST", on_broadcast)
    mq.register_handler("CHAT_DM", on_dm)
    mq.register_handler("CHANNEL_CREATE", on_create_channel)
    mq.register_handler("SIGNAL_TYPING", on_typing)
    mq.register_handler("SIGNAL_READ", on_read)
    
    # 3. Yêu cầu Message Queue bắt đầu chạy ngầm
    mq.start()
    
    # 4. Bật luồng Heartbeat HTTP để cập nhật danh bạ
    threading.Thread(target=heartbeat_worker, daemon=True).start() 
    
    # 5. Chạy Web Server HTTP (AsynapRous)
    app.prepare_address(ip, port)
    app.run()