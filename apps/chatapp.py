# # Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# # All rights reserved.

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
TRACKER_URL = "http://127.0.0.1:80"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "public"))

active_peers_cache = [] 
last_tracker_sync = 0

def register_to_tracker():
    try:
        data = json.dumps({"port": CURRENT_PORT}).encode('utf-8')
        req = urllib.request.Request(f"{TRACKER_URL}/register", data=data, headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=1)
        print(f" Báo danh Port {CURRENT_PORT} với Tracker thành công!")
    except:
        print(f" Tracker sập. Port {CURRENT_PORT} dùng P2P tiếp.")

def get_active_peers():
    global active_peers_cache, last_tracker_sync
    if time.time() - last_tracker_sync > 5:
        try:
            req = urllib.request.Request(f"{TRACKER_URL}/peers")
            with urllib.request.urlopen(req, timeout=0.5) as res:
                data = json.loads(res.read().decode())
                active_peers_cache = data.get("peers", active_peers_cache)
        except: 
            pass
        finally:
            last_tracker_sync = time.time()
    return active_peers_cache

_db_lock = threading.RLock()

def get_db_dir():
    db_dir = os.path.join(BASE_DIR, f"user_databases_{CURRENT_PORT}")
    if not os.path.exists(db_dir): os.makedirs(db_dir)
    return db_dir

def get_session_file():
    return os.path.join(BASE_DIR, "sessions_global.json")

def save_shared_session(session_id, username):
    with _db_lock:
        try:
            s_file = get_session_file()
            sessions = {}
            if os.path.exists(s_file):
                with open(s_file, 'r', encoding='utf-8') as f: sessions = json.load(f)
            sessions[session_id] = username
            with open(f"{s_file}.tmp", 'w', encoding='utf-8') as f: json.dump(sessions, f)
            os.replace(f"{s_file}.tmp", s_file)
        except: pass

def get_valid_username(cookies):
    session_id = cookies.get('session_id')
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
    with _db_lock:
        try:
            with open(f"{db_file}.tmp", 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(f"{db_file}.tmp", db_file) 
        except: pass

@app.route('/')
def serve_index(headers, body, cookies=None):
    try:
        path = os.path.join(PUBLIC_DIR, "index.html")
        with open(path, 'r', encoding='utf-8') as f: return f.read()
    except Exception as e: return f"404: {e}"

@app.route('/(.*\\.(?:css|js))')
def serve_static(headers, body, cookies=None, file_path=None):
    try:
        full_path = os.path.join(PUBLIC_DIR, file_path)
        with open(full_path, 'r', encoding='utf-8') as f: return f.read()
    except: return ""

def _decode_body(body):
    return body.decode('utf-8') if isinstance(body, bytes) else body

def _json_response(data, status="success"):
    return json.dumps({"status": status, "data": data})

def _error_response(message):
    return json.dumps({"status": "error", "message": message})

# --- P2P SYNC ---
def p2p_sync_worker(endpoint, payload):
    payload['is_sync'] = True
    data_bytes = json.dumps(payload).encode('utf-8')
    for peer_port in get_active_peers():
        if peer_port == CURRENT_PORT: continue
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{peer_port}{endpoint}", data=data_bytes, headers={'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=0.5)
        except: pass

@app.route('/login/', methods=['GET', 'POST'])
def login(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body)) if body != "anonymous" else {}
        username, password = data.get('username', ''), data.get('password', '')
        if authenticate(username, password):
            session_id = create_session(username)
            save_shared_session(session_id, username)
            load_db(username)
            
            threading.Thread(target=p2p_sync_worker, args=('/sync-user/', {"username": username}), daemon=True).start()
            set_cookies = [f"session_id={session_id}; Path=/; HttpOnly"]
            return (_json_response({"username": username, "session_id": session_id}), set_cookies)
        return _error_response("Sai thông tin đăng nhập")
    except Exception as e: return _error_response(str(e))

@app.route('/submit-info/', methods=['POST'])
def submit_info(headers="guest", body="anonymous", cookies=None):
    return _json_response({"status": "ok"})

@app.route('/sync-user/', methods=['POST'])
def sync_user(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        if data.get('username'): load_db(data.get('username'))
        return _json_response({"status": "ok"})
    except: return _error_response("Lỗi Sync User")

@app.route('/channels/', methods=['POST', 'GET'])
def list_channels(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body)) if body != "anonymous" else {}
        req_user = data.get('username')
        username = req_user if req_user else get_valid_username(cookies)
        
        if not username: return _json_response({"channels": []})
        db = load_db(username)
        channel_list = [{"name": n, "member_count": len(i.get("members", [])), 
                         "message_count": len(i.get("messages", [])), "is_dm": n.startswith('dm:')} 
                        for n, i in db.items()]
        return _json_response({"channels": channel_list})
    except: return _json_response({"channels": []})

@app.route('/messages/', methods=['POST'])
def fetch_messages(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        channel_name, since_ts = data.get('channel', 'general'), float(data.get('since', 0))
        
        req_user = data.get('username')
        username = req_user if req_user else get_valid_username(cookies)
        
        if channel_name.startswith("dm:"):
            members = channel_name.replace("dm:", "").split("<->")
            if members: username = members[0]
            if not username: return _json_response({"messages": []})
        
        db = load_db(username)
        msgs = db.get(channel_name, {}).get('messages', [])
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
        
        msg_ts = data.get('timestamp') or time.time()
        msg_id = data.get('msg_id') or hashlib.md5(f"{from_user}{message}{channel}{uuid.uuid4().hex}".encode()).hexdigest()
        all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")]
        
        for u in all_users:
            if channel.startswith("dm:"):
                members = channel.replace("dm:", "").split("<->")
                if u not in members:
                    continue
            db = load_db(u)
            if channel not in db: db[channel] = {"members": [], "messages": []}
            if not any(m.get('msg_id') == msg_id for m in db[channel]["messages"][-50:]):
                db[channel]["messages"].append({
                    "msg_id": msg_id, "from": from_user, "text": message, "timestamp": msg_ts, "channel": channel
                })
            save_db(u, db)
        
        if not is_sync:
            data.update({"msg_id": msg_id, "timestamp": msg_ts})
            threading.Thread(target=p2p_sync_worker, args=('/broadcast-peer/', data), daemon=True).start()
        return _json_response({"message": "Sent", "msg_id": msg_id})
    except: return _error_response("Lỗi Broadcast")

@app.route('/create-channel/', methods=['POST'])
def create_channel(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        name, creator, is_sync = data.get('name', ''), data.get('creator', ''), data.get('is_sync', False)
        all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")]
        for u in all_users:
            db = load_db(u)
            if name not in db:
                db[name] = {"members": [creator] if creator else [], "messages": []}
                save_db(u, db)
        if not is_sync: threading.Thread(target=p2p_sync_worker, args=('/create-channel/', data), daemon=True).start()
        return _json_response({"channel": name})
    except: return _error_response("Lỗi Create")

@app.route('/send-peer/', methods=['POST'])
def send_peer(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        from_user, to_user, message = data.get('from', ''), data.get('to', ''), data.get('message', '')
        is_sync = data.get('is_sync', False)
        
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
    except: return _error_response("Lỗi DM")

@app.route('/get-list/', methods=['GET', 'POST'])
def get_list(headers="guest", body="anonymous", cookies=None):
    all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(get_db_dir()) if f.startswith("db_")]
    peer_list = [{"peer_id": u, "username": u} for u in all_users]
    return _json_response({"peers": peer_list})

def create_chatapp(ip, port):
    global CURRENT_PORT
    CURRENT_PORT = port
    print(f" [ChatApp] Node khởi động tại {ip}:{port}")
    threading.Thread(target=register_to_tracker, daemon=True).start()
    app.prepare_address(ip, port)
    app.run()