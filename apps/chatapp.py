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

NODE_ADDRESSES = [
    "http://127.0.0.1:9000",
    "http://127.0.0.1:9001",
    "http://127.0.0.1:9002"
]
KNOWN_PEERS = [9000, 9001, 9002] 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "user_databases")
if not os.path.exists(DB_DIR): os.makedirs(DB_DIR)

# ============================================================
# CƠ CHẾ SỬA LỖI 1: ĐỒNG BỘ SESSION (Chống mất kết nối qua Proxy)
# ============================================================
SESSION_FILE = os.path.join(BASE_DIR, "shared_sessions.json")

def save_shared_session(session_id, username):
    try:
        sessions = {}
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                sessions = json.load(f)
        sessions[session_id] = username
        
        tmp_file = f"{SESSION_FILE}.tmp.{CURRENT_PORT}"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(sessions, f)
        os.replace(tmp_file, SESSION_FILE) # Tráo file cực nhanh (Atomic)
    except: pass

def get_valid_username(cookies):
    """Hàm xác thực thông minh: Thử RAM trước, nếu thất bại thử File Chung"""
    session_id = cookies.get('session_id') if cookies else None
    if not session_id: return None
    
    username = validate_session(session_id)
    if username: return username
    
    # Cứu vãn từ Shared Sessions khi Proxy điều hướng sang Node khác
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get(session_id)
    except: pass
    return None

def get_db_file(username):
    return os.path.join(DB_DIR, f"db_{username}.json")

def load_db(username):
    if not username: return {"general": {"members": [], "messages": []}}
    db_file = get_db_file(username)
    
    if not os.path.exists(db_file):
        data = {"general": {"members": [], "messages": []}}
        save_db(username, data)
        return data
        
    for _ in range(3):
        try:
            with open(db_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "general" not in data: data["general"] = {"members": [], "messages": []}
                return data
        except:
            time.sleep(0.05)
    return {"general": {"members": [], "messages": []}}

def save_db(username, data):
    if not username: return
    db_file = get_db_file(username)
    tmp_file = f"{db_file}.tmp.{CURRENT_PORT}"
    try:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_file, db_file) 
    except: pass


def p2p_sync_worker(endpoint, payload):
    payload['is_sync'] = True
    data_bytes = json.dumps(payload).encode('utf-8')
    for peer_port in KNOWN_PEERS:
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

            return (_json_response({
                "username": username, 
                "session_id": session_id,
                "active_nodes": NODE_ADDRESSES 
            }), [f"session_id={session_id}; Path=/; HttpOnly"])
        return _error_response("Sai tài khoản")
    except Exception as e: return _error_response(str(e))

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
        channel_list = [{"name": n, "member_count": len(i.get("members", [])), 
                         "message_count": len(i.get("messages", [])), "is_dm": n.startswith('dm:')} 
                        for n, i in db.items()]
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

        all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(DB_DIR) if f.startswith("db_")]
        for u in all_users:
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
    except: return _error_response("Lỗi")

@app.route('/create-channel/', methods=['POST'])
def create_channel(headers="guest", body="anonymous", cookies=None):
    try:
        data = json.loads(_decode_body(body))
        name, creator, is_sync = data.get('name', ''), data.get('creator', ''), data.get('is_sync', False)
        all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(DB_DIR) if f.startswith("db_")]
        for u in all_users:
            db = load_db(u)
            if name not in db:
                db[name] = {"members": [creator] if creator else [], "messages": []}
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
    all_users = [f.replace("db_", "").replace(".json", "") for f in os.listdir(DB_DIR) if f.startswith("db_")]
    peer_list = [{"peer_id": u, "username": u} for u in all_users]
    return _json_response({"peers": peer_list, "active_nodes": NODE_ADDRESSES})

def create_chatapp(ip, port):
    app.prepare_address(ip, port)
    app.run()