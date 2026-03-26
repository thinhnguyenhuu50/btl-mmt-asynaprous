#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#

"""
apps.chatapp
~~~~~~~~~~~~~~~~~

This module implements a hybrid chat application combining client-server
and peer-to-peer (P2P) paradigms using the AsynapRous framework.

**Client-Server Phase (Initialization):**
- Peer registration: new peers submit their IP/port to the centralized server
- Tracker update: the server maintains a tracking list of active peers
- Peer discovery: peers request the current list of active peers
- Connection setup: peers use the tracking list to initiate P2P connections

**Peer-to-Peer Phase (Chat):**
- Broadcast: a peer broadcasts messages to all connected peers
- Direct messaging: peers exchange messages without routing through server
- Channel management: users can create/join channels, view messages

**Protocol Design:**
All communication uses HTTP-based RESTful APIs with JSON payloads.
The protocol supports the following operations:
  POST /login/         - Authenticate user
  POST /submit-info/   - Register peer info with tracker
  POST /add-list/      - Add peer to active list
  GET  /get-list/      - Retrieve active peers list
  POST /connect-peer/  - Connect to a peer
  POST /broadcast-peer/- Broadcast message to all peers
  POST /send-peer/     - Send direct message to a peer
  GET  /channels/      - List available channels
  POST /create-channel/- Create a new channel
  GET  /messages/      - Get messages for a channel
"""

import sys
import os
import json
import time
import socket
import threading
import asyncio

from daemon import AsynapRous
from daemon.auth import (
    authenticate, create_session, validate_session,
    get_session_username, build_auth_challenge
)

app = AsynapRous()

# ============================================================
# In-memory Data Structures
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

def _get_session_from_headers(headers):
    """Extract session_id from request headers (Cookie header).

    :param headers (str): JSON string of headers dict.
    :rtype: str or None - session_id if found.
    """
    try:
        h = json.loads(headers) if isinstance(headers, str) else headers
        cookie_str = h.get('cookie', '')
        if cookie_str:
            for pair in cookie_str.split(';'):
                pair = pair.strip()
                if pair.startswith('session_id='):
                    return pair.split('=', 1)[1]
    except Exception:
        pass
    return None


def _require_auth(headers):
    """Check if request has valid authentication.

    :param headers (str): JSON string of headers.
    :rtype: tuple (bool, str) - (is_authenticated, username)
    """
    session_id = _get_session_from_headers(headers)
    if session_id:
        username = validate_session(session_id)
        if username:
            return True, username
    return False, None


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


async def _notify_peer_async(peer_ip, peer_port, path, data):
    """Send an HTTP POST request to a peer non-blockingly for P2P communication.

    :param peer_ip (str): IP address of target peer.
    :param peer_port (int): Port of target peer.
    :param path (str): URL path for the request.
    :param data (dict): JSON payload to send.
    :rtype: dict or None - response data if successful.
    """
    try:
        reader, writer = await asyncio.open_connection(peer_ip, int(peer_port))
        body = json.dumps(data)
        request = (
            "POST {} HTTP/1.1\r\n"
            "Host: {}:{}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n"
            "\r\n"
            "{}"
        ).format(path, peer_ip, peer_port, len(body), body)
        writer.write(request.encode('utf-8'))
        await writer.drain()

        response = b""
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            response += chunk
        writer.close()
        await writer.wait_closed()

        # Parse response body
        response_str = response.decode('utf-8', errors='replace')
        if '\r\n\r\n' in response_str:
            body_part = response_str.split('\r\n\r\n', 1)[1]
            try:
                return json.loads(body_part)
            except json.JSONDecodeError:
                pass
        return None
    except Exception as e:
        print("[ChatApp] Error notifying peer {}:{} - {}".format(peer_ip, peer_port, e))
        return None


# ============================================================
# Client-Server Routes (Initialization Phase)
# ============================================================

@app.route('/login/', methods=['POST'])
def login(headers="guest", body="anonymous"):
    """Handle user login via POST request.

    Authenticates user credentials and creates a session.
    Returns a session cookie for subsequent requests.

    Protocol: POST /login/
    Request body: {"username": "...", "password": "..."}
    Response: {"status": "success", "data": {"username": "...", "session_id": "..."}}
    """
    print("[ChatApp] Login request")
    try:
        credentials = json.loads(body) if body else {}
        username = credentials.get('username', '')
        password = credentials.get('password', '')

        if authenticate(username, password):
            session_id = create_session(username)

            # Register as peer automatically
            with _lock:
                peer_id = username
                peers[peer_id] = {
                    "ip": "127.0.0.1",
                    "port": 0,
                    "username": username,
                    "last_seen": time.time()
                }
                # Auto-join general channel
                if username not in channels["general"]["members"]:
                    channels["general"]["members"].append(username)

            response_data = {
                "username": username,
                "session_id": session_id
            }
            # Return (json_bytes, cookies_list) tuple so the adapter
            # sets a real Set-Cookie header (RFC 6265).
            cookies = ["session_id={}; Path=/; HttpOnly".format(session_id)]
            return (_json_response(response_data), cookies)
        else:
            return _error_response("Invalid username or password")
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/validate-session/', methods=['GET', 'POST'])
def validate_session_route(headers="guest", body="anonymous"):
    """Validate an existing session from the Cookie header.

    This endpoint allows the client to check if a stored cookie
    still maps to a valid server-side session, enabling session
    persistence across page refreshes (RFC 6265).

    Protocol: GET /validate-session/
    Response: {"status": "success", "data": {"username": "...", "session_id": "..."}}
    """
    print("[ChatApp] Validate-session request")
    session_id = _get_session_from_headers(headers)
    if session_id:
        username = validate_session(session_id)
        if username:
            return _json_response({"username": username, "session_id": session_id})
    return _error_response("No valid session")


@app.route('/submit-info/', methods=['POST'])
def submit_info(headers="guest", body="anonymous"):
    """Register peer information with the tracker server.

    A new peer joins the network by submitting its IP and port.
    The tracker stores this information for peer discovery.

    Protocol: POST /submit-info/
    Request body: {"ip": "...", "port": ..., "username": "..."}
    Response: {"status": "success", "data": {"peer_id": "..."}}
    """
    print("[ChatApp] Submit-info request")
    authenticated, username = _require_auth(headers)

    try:
        info = json.loads(body) if body else {}
        peer_ip = info.get('ip', '127.0.0.1')
        peer_port = info.get('port', 0)
        peer_username = info.get('username', username or 'anonymous')

        with _lock:
            peer_id = peer_username
            peers[peer_id] = {
                "ip": peer_ip,
                "port": peer_port,
                "username": peer_username,
                "last_seen": time.time()
            }

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
    print("[ChatApp] Add-list request")
    try:
        info = json.loads(body) if body else {}
        peer_id = info.get('peer_id', '')
        peer_ip = info.get('ip', '127.0.0.1')
        peer_port = info.get('port', 0)

        with _lock:
            peers[peer_id] = {
                "ip": peer_ip,
                "port": peer_port,
                "username": peer_id,
                "last_seen": time.time()
            }

        return _json_response({"added": peer_id})
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/get-list/', methods=['GET', 'POST'])
def get_list(headers="guest", body="anonymous"):
    """Retrieve the list of active peers.

    Returns all currently registered peers so that a new peer
    can discover others and initiate P2P connections.

    Protocol: GET /get-list/
    Response: {"status": "success", "data": {"peers": [...]}}
    """
    print("[ChatApp] Get-list request")
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


# ============================================================
# P2P Routes (Chat Phase)
# ============================================================

@app.route('/connect-peer/', methods=['POST'])
def connect_peer(headers="guest", body="anonymous"):
    """Initiate a P2P connection to another peer.

    Protocol: POST /connect-peer/
    Request body: {"from": "username", "to": "target_peer_id"}
    Response: {"status": "success", "data": {"connected_to": "peer_id"}}
    """
    print("[ChatApp] Connect-peer request")
    try:
        data = json.loads(body) if body else {}
        from_user = data.get('from', '')
        to_peer = data.get('to', '')

        with _lock:
            if to_peer not in peers:
                return _error_response("Peer '{}' not found".format(to_peer))

            # Register bidirectional connection
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
async def broadcast_peer(headers="guest", body="anonymous"):
    """Broadcast a message to all connected peers.

    In the P2P paradigm, the broadcasting peer sends the message
    directly to each connected peer without routing through the server.
    However, the server also stores the message for channel history.

    Protocol: POST /broadcast-peer/
    Request body: {"from": "username", "message": "...", "channel": "..."}
    Response: {"status": "success", "data": {"delivered_to": [...]}}
    """
    print("[ChatApp] Broadcast-peer request")
    try:
        data = json.loads(body) if body else {}
        from_user = data.get('from', 'anonymous')
        message = data.get('message', '')
        channel_name = data.get('channel', 'general')

        delivered_to = []

        with _lock:
            # Store message in channel
            if channel_name not in channels:
                channels[channel_name] = {"members": [], "messages": []}

            msg_entry = {
                "from": from_user,
                "text": message,
                "timestamp": time.time(),
                "channel": channel_name
            }
            channels[channel_name]["messages"].append(msg_entry)

            # Gather target peer info
            members_to_notify = []
            for member in channels[channel_name]["members"]:
                if member != from_user and member in peers:
                    members_to_notify.append(peers[member])

        # Notify peers asynchronously outside the lock
        tasks = []
        for peer_info in members_to_notify:
            delivered_to.append(peer_info["username"])
            tasks.append(_notify_peer_async(
                peer_info["ip"], 
                peer_info["port"], 
                '/receive-message/', 
                {
                    "from": from_user,
                    "message": message,
                    "channel": channel_name,
                    "timestamp": msg_entry["timestamp"]
                }
            ))
        
        if tasks:
            await asyncio.gather(*tasks)

        return _json_response({
            "delivered_to": delivered_to,
            "message_id": len(channels.get(channel_name, {}).get("messages", []))
        })
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/send-peer/', methods=['POST'])
async def send_peer(headers="guest", body="anonymous"):
    """Send a direct message to a specific peer.

    In P2P mode, this message is sent directly to the target peer.
    The server records it for message history.

    Protocol: POST /send-peer/
    Request body: {"from": "username", "to": "target", "message": "..."}
    Response: {"status": "success", "data": {"delivered_to": "target"}}
    """
    print("[ChatApp] Send-peer request")
    try:
        data = json.loads(body) if body else {}
        from_user = data.get('from', 'anonymous')
        to_user = data.get('to', '')
        message = data.get('message', '')

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
                "timestamp": time.time(),
            }
            channels[dm_channel]["messages"].append(msg_entry)

            target_peer = peers.get(to_user)

        # Send asynchronously to the target peer outside the lock
        if target_peer:
            await _notify_peer_async(
                target_peer["ip"], 
                target_peer["port"], 
                '/receive-message/', 
                {
                    "from": from_user,
                    "message": message,
                    "channel": dm_channel,
                    "timestamp": msg_entry["timestamp"]
                }
            )

        return _json_response({"delivered_to": to_user, "channel": dm_channel})
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
    print("[ChatApp] List channels request")
    try:
        # Optionally filter by user
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
    print("[ChatApp] Create channel request")
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
    print("[ChatApp] Join channel request")
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
    print("[ChatApp] Get messages request")
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


@app.route('/receive-message/', methods=['POST'])
def receive_message(headers="guest", body="anonymous"):
    """Receive a message from a peer (P2P incoming endpoint).

    Other peers call this endpoint directly to deliver messages
    without going through the centralized server.

    Protocol: POST /receive-message/
    Request body: {"from": "...", "message": "...", "channel": "..."}
    """
    print("[ChatApp] Receive message from peer")
    try:
        data = json.loads(body) if body else {}
        from_user = data.get('from', 'anonymous')
        message = data.get('message', '')
        channel_name = data.get('channel', 'general')
        msg_timestamp = data.get('timestamp', time.time())

        with _lock:
            if channel_name not in channels:
                channels[channel_name] = {"members": [], "messages": []}

            # Check if this exact message was already added (prevents duplicates when simulating multiple peers on same server)
            is_dup = False
            for m in channels[channel_name]["messages"]:
                if m.get("from") == from_user and m.get("timestamp") == msg_timestamp:
                    is_dup = True
                    break

            if not is_dup:
                channels[channel_name]["messages"].append({
                    "from": from_user,
                    "text": message,
                    "timestamp": msg_timestamp,
                    "channel": channel_name
                })

        return _json_response({"received": True})
    except json.JSONDecodeError:
        return _error_response("Invalid JSON")


# ============================================================
# Entry Point
# ============================================================

def create_chatapp(ip, port):
    """Create and start the chat application server.

    :param ip (str): IP address to bind.
    :param port (int): Port number to listen on.
    """
    print("[ChatApp] Starting chat application on {}:{}".format(ip, port))
    app.prepare_address(ip, port)
    app.run()
