#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
#

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

app = AsynapRous()
CURRENT_PORT = 9000 
CURRENT_USERNAME = None  

# ============================================================
# LOGIC TRACKER & CACHE DANH BẠ (HYBRID P2P)
# ============================================================
TRACKER_URL = "http://127.0.0.1:80"

active_peers_cache = [] 
last_tracker_sync = 0
online_status_cache = {} 

def register_to_tracker():
    try:
        data = json.dumps({"port": CURRENT_PORT}).encode('utf-8')
        req = urllib.request.Request(f"{TRACKER_URL}/submit-info/", data=data, headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=1)
        print(f" Báo danh Port {CURRENT_PORT} với Tracker thành công!")
    except:
        print(f" Tracker (Port 80) sập. Port {CURRENT_PORT} sử dụng danh bạ P2P dự phòng.")

def get_active_peers(force_update=False):
    global active_peers_cache, last_tracker_sync
    if force_update or (time.time() - last_tracker_sync > 5): 
        try:
            req = urllib.request.Request(f"{TRACKER_URL}/get-list/")
            with urllib.request.urlopen(req, timeout=0.5) as res:
                data = json.loads(res.read().decode())
                active_peers_cache = data.get("peers", active_peers_cache)
                last_tracker_sync = time.time()
        except: pass 
    return active_peers_cache

def heartbeat_worker():
    global online_status_cache
    while True:
        time.sleep(3) 
        active_ports = get_active_peers(force_update=False)
        new_status = {}
        for port in active_ports:
            if port == CURRENT_PORT: continue 
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/whoami/")
                with urllib.request.urlopen(req, timeout=1.0) as res:
                    data = json.loads(res.read().decode())
                    uname = data.get("data", {}).get("username")
                    if uname: new_status[uname] = True
            except Exception: pass 
        online_status_cache = new_status

# ============================================================
# CƠ SỞ DỮ LIỆU CÁCH LY & XỬ LÝ COOKIE XUNG ĐỘT
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_db_lock = threading.RLock()

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

# ============================================================
# GIAO THỨC ĐỒNG BỘ P2P TRỰC TIẾP
# ============================================================
def p2p_sync_worker(endpoint, payload):
    payload['is_sync'] = True
    payload['sender_port'] = CURRENT_PORT 
    data_bytes = json.dumps(payload).encode('utf-8')
    peers_to_send = get_active_peers(force_update=True)
    
    for peer_port in peers_to_send:
        if peer_port == CURRENT_PORT: continue
        url = f"http://127.0.0.1:{peer_port}{endpoint}"
        try:
            req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=0.5)
        except: pass

def _decode_body(body):
    return body.decode('utf-8') if isinstance(body, bytes) else body

def _json_response(data, status="success"):
    return json.dumps({"status": status, "data": data})

def _error_response(message):
    return json.dumps({"status": "error", "message": message})

# ============================================================
# CÁC ROUTE CHỨC NĂNG CHAT
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
            threading.Thread(target=p2p_sync_worker, args=('/sync-user/', {"username": username}), daemon=True).start()

            set_cookies = [
                f"session_id_{CURRENT_PORT}={session_id}; Path=/; HttpOnly",
                f"session_id={session_id}; Path=/; HttpOnly"
            ]
            return (_json_response({"username": username, "session_id": session_id}), set_cookies)
        return _error_response("Sai tài khoản")
    except Exception as e: return _error_response(str(e))
 
@app.route('/whoami/', methods=['GET', 'POST'])
def whoami(headers="guest", body="anonymous", cookies=None):
    return _json_response({"username": CURRENT_USERNAME})

@app.route('/submit-info/', methods=['POST'])
def submit_info(headers="guest", body="anonymous", cookies=None):
    global CURRENT_USERNAME
    try:
        data = json.loads(_decode_body(body))
        if data.get('username'): CURRENT_USERNAME = data.get('username')
        threading.Thread(target=register_to_tracker, daemon=True).start()
        return _json_response({"status": "ok"})
    except Exception as e: return _error_response(str(e))

@app.route('/add-list/', methods=['POST'])
def add_list(headers="guest", body="anonymous", cookies=None):
    global active_peers_cache
    try:
        data = json.loads(_decode_body(body))
        new_port = data.get('port')
        if new_port and new_port not in active_peers_cache:
            active_peers_cache.append(new_port)
            print(f" [Danh bạ] Đã thêm Peer thủ công tại Port: {new_port}")
        return _json_response({"status": "ok", "message": f"Đã thêm Port {new_port} vào danh bạ"})
    except Exception: return _error_response("Lỗi thêm vào danh sách")

@app.route('/connect-peer/', methods=['POST'])
def connect_peer(headers="guest", body="anonymous", cookies=None):
    global CURRENT_USERNAME
    try:
        data = json.loads(_decode_body(body))
        target_port = data.get('port')
        if target_port:
            threading.Thread(target=p2p_sync_worker, args=('/sync-user/', {"username": CURRENT_USERNAME}), daemon=True).start()
        return _json_response({"status": "ok"})
    except Exception: return _error_response("Lỗi kết nối Peer")

@app.route('/sync-user/', methods=['POST'])
def sync_user(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        if data.get('username'): load_db(data.get('username'))
        return _json_response({"status": "ok"})
    except: return _error_response("Lỗi")

@app.route('/channels/', methods=['POST', 'GET'])
def list_channels(headers="guest", body="anonymous", cookies=None): 
    try:
        username = get_valid_username(cookies) 
        if not username: return _json_response({"channels": []})

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
        if not username: return _json_response({"messages": []})

        data = json.loads(_decode_body(body))
        channel_name, since_ts = data.get('channel', 'general'), float(data.get('since', 0))
        
        db = load_db(username)
        channel_data = db.get(channel_name, {})
        
        if channel_data.get('is_private', False) and username not in channel_data.get('allowed_members', []):
            return _json_response({"messages": [], "error": "Truy cập bị từ chối"})

        msgs = channel_data.get('messages', [])
        new_msgs = [m for m in msgs if float(m.get('timestamp', 0)) > since_ts]
        last_ts = max((float(m.get('timestamp', 0)) for m in new_msgs), default=since_ts)
        
        return _json_response({"messages": new_msgs, "typing": [], "reads": {}, "last_ts": last_ts})
    except: return _json_response({"messages": []})

@app.route('/broadcast-peer/', methods=['POST'])
def broadcast_peer(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        from_user, message, channel = data.get('from', ''), data.get('message', ''), data.get('channel', 'general')
        is_sync = data.get('is_sync', False)
        
        sender_port = data.get('sender_port', 'Unknown')
        if is_sync: print(f" [Group: {channel}] Nhận tin nhắn từ '{from_user}' (Nguồn: 127.0.0.1:{sender_port})")

        msg_ts = data.get('timestamp') or time.time()
        msg_id = data.get('msg_id') or hashlib.md5(f"{from_user}{message}{channel}{uuid.uuid4().hex}".encode()).hexdigest()

        all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")]
        for u in all_users:
            db = load_db(u)
            if channel not in db: db[channel] = {"members": [], "messages": []}
            
            if db[channel].get('is_private', False) and from_user not in db[channel].get('allowed_members', []):
                continue

            if not any(m.get('msg_id') == msg_id for m in db[channel]["messages"][-50:]):
                db[channel]["messages"].append({
                    "msg_id": msg_id, "from": from_user, "text": message, "timestamp": msg_ts, "channel": channel
                })
            save_db(u, db)

        if not is_sync:
            data.update({"msg_id": msg_id, "timestamp": msg_ts})
            threading.Thread(target=p2p_sync_worker, args=('/broadcast-peer/', data), daemon=True).start()

        return _json_response({"message": "Sent", "msg_id": msg_id})
    except: return _error_response("Lỗi")

@app.route('/create-channel/', methods=['POST'])
def create_channel(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        name, creator, is_sync = data.get('name', ''), data.get('creator', ''), data.get('is_sync', False)
        
        is_private = data.get('is_private', False)
        allowed_members = data.get('allowed_members', [])
        if creator and creator not in allowed_members: allowed_members.append(creator)

        all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")]
        for u in all_users:
            db = load_db(u)
            if name not in db:
                db[name] = {
                    "members": [creator] if creator else [], 
                    "messages": [],
                    "is_private": is_private,
                    "allowed_members": allowed_members
                }
                save_db(u, db)
        if not is_sync: threading.Thread(target=p2p_sync_worker, args=('/create-channel/', data), daemon=True).start()
        return _json_response({"channel": name})
    except: return _error_response("Lỗi")

@app.route('/send-peer/', methods=['POST'])
def send_peer(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        from_user, to_user, message = data.get('from', ''), data.get('to', ''), data.get('message', '')
        is_sync = data.get('is_sync', False)
        
        sender_port = data.get('sender_port', 'Unknown')
        if is_sync: print(f" [DM] Nhận tin cá nhân từ '{from_user}' gửi cho '{to_user}' (Nguồn: 127.0.0.1:{sender_port})")
        
        msg_ts = data.get('timestamp') or time.time()
        msg_id = data.get('msg_id') or hashlib.md5(f"dm|{from_user}{to_user}{message}{uuid.uuid4().hex}".encode()).hexdigest()
        dm_channel = "dm:{}<->{}".format(*sorted([from_user, to_user]))

        for u in [from_user, to_user]:
            db = load_db(u)
            if dm_channel not in db: db[dm_channel] = {"members": sorted([from_user, to_user]), "messages": []}
            if not any(m.get('msg_id') == msg_id for m in db[dm_channel]["messages"][-50:]):
                db[dm_channel]["messages"].append({
                    "msg_id": msg_id, "from": from_user, "to": to_user, "text": message, "timestamp": msg_ts
                })
            save_db(u, db)
                
        if not is_sync:
            data.update({"msg_id": msg_id, "timestamp": msg_ts})
            threading.Thread(target=p2p_sync_worker, args=('/send-peer/', data), daemon=True).start()

        return _json_response({"delivered_to": to_user, "channel": dm_channel})
    except: return _error_response("Lỗi gửi DM")

@app.route('/get-list/', methods=['GET', 'POST'])
def get_list(headers="guest", body="anonymous", cookies=None):
    global online_status_cache
    all_users = set([f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")])
    all_users.update([k for k, v in online_status_cache.items() if v])
    
    peer_dict = {u: {
        "peer_id": u, 
        "username": u, 
        "is_online": online_status_cache.get(u, False) 
    } for u in all_users}
            
    return _json_response({"peers": list(peer_dict.values())})

def create_chatapp(ip, port):
    global CURRENT_PORT
    CURRENT_PORT = port
    print(f" [ChatApp] Peer khởi động tại {ip}:{port}")
    threading.Thread(target=register_to_tracker, daemon=True).start()
    threading.Thread(target=heartbeat_worker, daemon=True).start() 
    app.prepare_address(ip, port)
    app.run()