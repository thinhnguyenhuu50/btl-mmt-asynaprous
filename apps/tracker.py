#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#

"""
apps.tracker
~~~~~~~~~~~~~~~~~

This module implements the centralized tracker server for the hybrid
chat application. The tracker is the single source of truth for:
- Active peer registry (IP, port, username)
- Channel management (creation, membership)
- Message history (broadcast and DM)

Peer applications (chatapp.py) register with this tracker via
POST /submit-info/ and discover other peers via GET /get-list/.
Messages are stored here so that all peers share the same history.

The tracker runs as a backend process via start_backend.py.
"""

import json
import time
import threading

from daemon import AsynapRous

app = AsynapRous()

# ============================================================
# In-memory Data Structures (Single Source of Truth)
# ============================================================

# Registered peers: peer_id -> {ip, port, username, last_seen}
peers = {}

# Active connections: username -> [connected_peer_usernames]
connections = {}

# Channels: channel_name -> {members: [usernames], messages: [{from, text, timestamp}]}
channels = {
    "general": {
        "members": [],
        "messages": []
    }
}

# Lock for thread-safe access to shared data
_lock = threading.Lock()


# ============================================================
# Helper Functions
# ============================================================

def _json_response(data, status="success"):
    """Create a standard JSON response.

    :param data: data to include in response.
    :param status: status string.
    :rtype: bytes
    """
    response = {"status": status, "data": data}
    return json.dumps(response).encode('utf-8')


def _error_response(message):
    """Create an error JSON response.

    :param message: error message.
    :rtype: bytes
    """
    return json.dumps({"status": "error", "message": message}).encode('utf-8')


# ============================================================
# Tracker Routes
# ============================================================

@app.route('/submit-info/', methods=['POST'])
def submit_info(headers="guest", body="anonymous"):
    """Register peer information with the tracker.

    Protocol: POST /submit-info/
    Request body: {"ip": "...", "port": ..., "username": "..."}
    Response: {"status": "success", "data": {"peer_id": "..."}}
    """
    print("[Tracker] Submit-info request")
    try:
        info = json.loads(body) if body else {}
        peer_ip = info.get('ip', '127.0.0.1')
        peer_port = info.get('port', 0)
        peer_username = info.get('username', 'anonymous')

        with _lock:
            peer_id = peer_username
            peers[peer_id] = {
                "ip": peer_ip,
                "port": int(peer_port),
                "username": peer_username,
                "last_seen": time.time()
            }
            # Auto-join general channel
            if peer_username not in channels["general"]["members"]:
                channels["general"]["members"].append(peer_username)

        print("[Tracker] Registered peer '{}' at {}:{}".format(
            peer_username, peer_ip, peer_port))
        return _json_response({"peer_id": peer_id})
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/add-list/', methods=['POST'])
def add_list(headers="guest", body="anonymous"):
    """Add a peer to the active peers list.

    Protocol: POST /add-list/
    Request body: {"peer_id": "...", "ip": "...", "port": ...}
    Response: {"status": "success", "data": {"added": "peer_id"}}
    """
    print("[Tracker] Add-list request")
    try:
        info = json.loads(body) if body else {}
        peer_id = info.get('peer_id', '')
        peer_ip = info.get('ip', '127.0.0.1')
        peer_port = info.get('port', 0)

        with _lock:
            peers[peer_id] = {
                "ip": peer_ip,
                "port": int(peer_port),
                "username": peer_id,
                "last_seen": time.time()
            }

        return _json_response({"added": peer_id})
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/get-list/', methods=['GET', 'POST'])
def get_list(headers="guest", body="anonymous"):
    """Retrieve the list of active peers.

    Protocol: GET /get-list/
    Response: {"status": "success", "data": {"peers": [...]}}
    """
    print("[Tracker] Get-list request")
    with _lock:
        peer_list = []
        for pid, pinfo in peers.items():
            peer_list.append({
                "peer_id": pid,
                "ip": pinfo["ip"],
                "port": pinfo["port"],
                "username": pinfo["username"],
                "last_seen": pinfo["last_seen"]
            })
    return _json_response({"peers": peer_list})


@app.route('/connect-peer/', methods=['POST'])
def connect_peer(headers="guest", body="anonymous"):
    """Register a P2P connection between two peers.

    Protocol: POST /connect-peer/
    Request body: {"from": "username", "to": "target_peer_id"}
    Response: {"status": "success", "data": {"connected_to": "peer_id"}}
    """
    print("[Tracker] Connect-peer request")
    try:
        data = json.loads(body) if body else {}
        from_user = data.get('from', '')
        to_peer = data.get('to', '')

        with _lock:
            if to_peer not in peers:
                return _error_response("Peer '{}' not found".format(to_peer))

            if from_user not in connections:
                connections[from_user] = []
            if to_peer not in connections[from_user]:
                connections[from_user].append(to_peer)

            if to_peer not in connections:
                connections[to_peer] = []
            if from_user not in connections[to_peer]:
                connections[to_peer].append(from_user)

        return _json_response({"connected_to": to_peer})
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/broadcast-peer/', methods=['POST'])
def broadcast_peer(headers="guest", body="anonymous"):
    """Store a broadcast message in channel history.

    The tracker stores the message. P2P notification is handled
    by the peer that originated the broadcast.

    Protocol: POST /broadcast-peer/
    Request body: {"from": "username", "message": "...", "channel": "..."}
    Response: {"status": "success", "data": {"delivered_to": [...], "message_id": ...}}
    """
    print("[Tracker] Broadcast-peer request")
    try:
        data = json.loads(body) if body else {}
        from_user = data.get('from', 'anonymous')
        message = data.get('message', '')
        channel_name = data.get('channel', 'general')
        msg_timestamp = data.get('timestamp', time.time())

        with _lock:
            if channel_name not in channels:
                channels[channel_name] = {"members": [], "messages": []}

            msg_entry = {
                "from": from_user,
                "text": message,
                "timestamp": msg_timestamp,
                "channel": channel_name
            }
            channels[channel_name]["messages"].append(msg_entry)

            # Build list of peers to notify (returned to the calling peer)
            members_to_notify = []
            for member in channels[channel_name]["members"]:
                if member != from_user and member in peers:
                    members_to_notify.append({
                        "username": peers[member]["username"],
                        "ip": peers[member]["ip"],
                        "port": peers[member]["port"]
                    })

        return _json_response({
            "delivered_to": [p["username"] for p in members_to_notify],
            "peers_to_notify": members_to_notify,
            "message_id": len(channels.get(channel_name, {}).get("messages", [])),
            "timestamp": msg_timestamp
        })
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/send-peer/', methods=['POST'])
def send_peer(headers="guest", body="anonymous"):
    """Store a direct message in DM channel history.

    The tracker stores the message. P2P delivery is handled
    by the sending peer directly.

    Protocol: POST /send-peer/
    Request body: {"from": "username", "to": "target", "message": "..."}
    Response: {"status": "success", "data": {"delivered_to": "target", "channel": "...", "target_peer": {...}}}
    """
    print("[Tracker] Send-peer request")
    try:
        data = json.loads(body) if body else {}
        from_user = data.get('from', 'anonymous')
        to_user = data.get('to', '')
        message = data.get('message', '')
        msg_timestamp = data.get('timestamp', time.time())

        with _lock:
            # Create a DM channel name (sorted for consistency)
            dm_channel = "dm:{}<->{}".format(
                *sorted([from_user, to_user])
            )

            if dm_channel not in channels:
                channels[dm_channel] = {
                    "members": sorted([from_user, to_user]),
                    "messages": []
                }

            msg_entry = {
                "from": from_user,
                "to": to_user,
                "text": message,
                "timestamp": msg_timestamp,
            }
            channels[dm_channel]["messages"].append(msg_entry)

            # Return target peer info for P2P delivery
            target_peer = peers.get(to_user)
            target_info = None
            if target_peer:
                target_info = {
                    "username": target_peer["username"],
                    "ip": target_peer["ip"],
                    "port": target_peer["port"]
                }

        return _json_response({
            "delivered_to": to_user,
            "channel": dm_channel,
            "target_peer": target_info,
            "timestamp": msg_timestamp
        })
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


# ============================================================
# Channel Management Routes
# ============================================================

@app.route('/channels/', methods=['GET', 'POST'])
def list_channels(headers="guest", body="anonymous"):
    """List available channels.

    Protocol: GET /channels/
    Response: {"status": "success", "data": {"channels": [...]}}
    """
    print("[Tracker] List channels request")
    try:
        data = {}
        if body and body != "anonymous":
            try:
                data = json.loads(body)
            except Exception:
                pass
        username = data.get('username', '')

        with _lock:
            channel_list = []
            for name, info in channels.items():
                if not name.startswith('dm:') or (username and username in info["members"]):
                    channel_list.append({
                        "name": name,
                        "member_count": len(info["members"]),
                        "message_count": len(info["messages"]),
                        "is_dm": name.startswith('dm:')
                    })
        return _json_response({"channels": channel_list})
    except Exception as e:
        return _error_response(str(e))


@app.route('/create-channel/', methods=['POST'])
def create_channel(headers="guest", body="anonymous"):
    """Create a new channel.

    Protocol: POST /create-channel/
    Request body: {"name": "channel_name", "creator": "username"}
    Response: {"status": "success", "data": {"channel": "name"}}
    """
    print("[Tracker] Create channel request")
    try:
        data = json.loads(body) if body else {}
        name = data.get('name', '')
        creator = data.get('creator', '')

        if not name:
            return _error_response("Channel name is required")

        with _lock:
            if name in channels:
                return _error_response("Channel '{}' already exists".format(name))

            channels[name] = {
                "members": [creator] if creator else [],
                "messages": []
            }

        return _json_response({"channel": name, "created_by": creator})
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/join-channel/', methods=['POST'])
def join_channel(headers="guest", body="anonymous"):
    """Join an existing channel.

    Protocol: POST /join-channel/
    Request body: {"channel": "channel_name", "username": "..."}
    """
    print("[Tracker] Join channel request")
    try:
        data = json.loads(body) if body else {}
        channel_name = data.get('channel', '')
        username = data.get('username', '')

        with _lock:
            if channel_name not in channels:
                return _error_response("Channel '{}' not found".format(channel_name))

            if username not in channels[channel_name]["members"]:
                channels[channel_name]["members"].append(username)

        return _json_response({"joined": channel_name})
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/messages/', methods=['GET', 'POST'])
def get_messages(headers="guest", body="anonymous"):
    """Get messages for a channel.

    Protocol: GET /messages/
    Request body: {"channel": "...", "since": timestamp}
    Response: {"status": "success", "data": {"messages": [...]}}
    """
    print("[Tracker] Get messages request")
    try:
        data = {}
        if body and body != "anonymous":
            try:
                data = json.loads(body)
            except Exception:
                pass

        channel_name = data.get('channel', 'general')
        since = data.get('since', 0)

        with _lock:
            if channel_name not in channels:
                return _json_response({"messages": [], "channel": channel_name})

            msgs = channels[channel_name]["messages"]
            if since:
                msgs = [m for m in msgs if m.get("timestamp", 0) > since]

        return _json_response({"messages": msgs, "channel": channel_name})
    except Exception as e:
        return _error_response(str(e))


# ============================================================
# Entry Point
# ============================================================

def create_tracker(ip, port):
    """Create and start the tracker server.

    :param ip (str): IP address to bind.
    :param port (int): Port number to listen on.
    """
    print("[Tracker] Starting tracker server on {}:{}".format(ip, port))
    app.prepare_address(ip, port)
    app.run()
