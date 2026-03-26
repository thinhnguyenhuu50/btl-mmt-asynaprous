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

This module implements a hybrid chat peer application combining client-server
and peer-to-peer (P2P) paradigms using the AsynapRous framework.

**Architecture:**
- A centralized tracker (apps/tracker.py, started via start_backend.py) owns
  the global state: peer registry, channels, and message history.
- Each chatapp instance is a **peer** that:
  1. Registers with the tracker on startup (POST /submit-info/)
  2. Queries the tracker for peer lists and messages
  3. Sends messages **directly** to other peers via P2P (using _notify_peer_async)
  4. Receives P2P messages from other peers (POST /receive-message/)

**Protocol Design:**
All communication uses HTTP-based RESTful APIs with JSON payloads.
  POST /login/         - Authenticate user (local)
  POST /submit-info/   - Register peer info (forwarded to tracker)
  GET  /get-list/      - Retrieve active peers list (forwarded to tracker)
  POST /connect-peer/  - Connect to a peer (forwarded to tracker)
  POST /broadcast-peer/- Broadcast message to all peers
  POST /send-peer/     - Send direct message to a peer
  GET  /channels/      - List available channels (forwarded to tracker)
  POST /create-channel/- Create a new channel (forwarded to tracker)
  GET  /messages/      - Get messages for a channel (forwarded to tracker)
  POST /receive-message/ - Receive P2P message from another peer (local)
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
# Configuration (set by create_chatapp)
# ============================================================

# URL of the centralized tracker, e.g. "http://127.0.0.1:9000"
TRACKER_URL = None
_tracker_ip = "127.0.0.1"
_tracker_port = 9000

# The port this peer is listening on
_self_port = 8000

# Local message cache for /receive-message/ P2P incoming messages
# channel_name -> [msg_entries] — only stores messages received via P2P
_received_messages = {}
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


async def _forward_to_tracker(path, data=None, method="POST"):
    """Send an HTTP request to the centralized tracker.

    :param path (str): URL path (e.g. '/submit-info/').
    :param data (dict): JSON payload to send.
    :param method (str): HTTP method.
    :rtype: dict or None - parsed JSON response.
    """
    try:
        reader, writer = await asyncio.open_connection(_tracker_ip, _tracker_port)
        body = json.dumps(data) if data else ""
        request = (
            "{} {} HTTP/1.1\r\n"
            "Host: {}:{}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n"
            "\r\n"
            "{}"
        ).format(method, path, _tracker_ip, _tracker_port, len(body), body)
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

        response_str = response.decode('utf-8', errors='replace')
        if '\r\n\r\n' in response_str:
            body_part = response_str.split('\r\n\r\n', 1)[1]
            try:
                return json.loads(body_part)
            except json.JSONDecodeError:
                pass
        return None
    except Exception as e:
        print("[ChatApp] Error forwarding to tracker: {}".format(e))
        return None


def _forward_to_tracker_sync(path, data=None, method="POST"):
    """Synchronous wrapper for _forward_to_tracker.

    Creates a new event loop to run the async function,
    used by sync route handlers.

    :param path (str): URL path.
    :param data (dict): JSON payload.
    :param method (str): HTTP method.
    :rtype: dict or None
    """
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_forward_to_tracker(path, data, method))
        loop.close()
        return result
    except Exception as e:
        print("[ChatApp] Sync forward error: {}".format(e))
        return None


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
    After login, auto-registers the peer with the tracker.

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

            # Register with tracker
            _forward_to_tracker_sync('/submit-info/', {
                "ip": "127.0.0.1",
                "port": _self_port,
                "username": username
            })

            response_data = {
                "username": username,
                "session_id": session_id
            }
            cookies = ["session_id={}; Path=/; HttpOnly".format(session_id)]
            return (_json_response(response_data), cookies)
        else:
            return _error_response("Invalid username or password")
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/validate-session/', methods=['GET', 'POST'])
def validate_session_route(headers="guest", body="anonymous"):
    """Validate an existing session from the Cookie header.

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


# ============================================================
# Routes Forwarded to Tracker
# ============================================================

@app.route('/submit-info/', methods=['POST'])
def submit_info(headers="guest", body="anonymous"):
    """Register peer info — forwarded to tracker.

    Protocol: POST /submit-info/
    """
    print("[ChatApp] Submit-info -> forwarding to tracker")
    try:
        info = json.loads(body) if body else {}
        # Ensure the port is set to our actual listening port
        info['port'] = _self_port
        result = _forward_to_tracker_sync('/submit-info/', info)
        if result:
            return json.dumps(result).encode('utf-8')
        return _error_response("Failed to register with tracker")
    except Exception as e:
        return _error_response(str(e))


@app.route('/add-list/', methods=['POST'])
def add_list(headers="guest", body="anonymous"):
    """Add peer to list — forwarded to tracker.

    Protocol: POST /add-list/
    """
    print("[ChatApp] Add-list -> forwarding to tracker")
    try:
        data = json.loads(body) if body else {}
        result = _forward_to_tracker_sync('/add-list/', data)
        if result:
            return json.dumps(result).encode('utf-8')
        return _error_response("Failed to add to tracker")
    except Exception as e:
        return _error_response(str(e))


@app.route('/get-list/', methods=['GET', 'POST'])
def get_list(headers="guest", body="anonymous"):
    """Get active peers list — forwarded to tracker.

    Protocol: GET /get-list/
    """
    print("[ChatApp] Get-list -> forwarding to tracker")
    result = _forward_to_tracker_sync('/get-list/', {}, "POST")
    if result:
        return json.dumps(result).encode('utf-8')
    return _error_response("Failed to get peer list from tracker")


@app.route('/connect-peer/', methods=['POST'])
def connect_peer(headers="guest", body="anonymous"):
    """Connect to peer — forwarded to tracker.

    Protocol: POST /connect-peer/
    """
    print("[ChatApp] Connect-peer -> forwarding to tracker")
    try:
        data = json.loads(body) if body else {}
        result = _forward_to_tracker_sync('/connect-peer/', data)
        if result:
            return json.dumps(result).encode('utf-8')
        return _error_response("Failed to connect peer via tracker")
    except Exception as e:
        return _error_response(str(e))


@app.route('/channels/', methods=['GET', 'POST'])
def list_channels(headers="guest", body="anonymous"):
    """List channels — forwarded to tracker.

    Protocol: GET /channels/
    """
    print("[ChatApp] Channels -> forwarding to tracker")
    try:
        data = {}
        if body and body != "anonymous":
            try:
                data = json.loads(body)
            except Exception:
                pass
        result = _forward_to_tracker_sync('/channels/', data)
        if result:
            return json.dumps(result).encode('utf-8')
        return _error_response("Failed to get channels from tracker")
    except Exception as e:
        return _error_response(str(e))


@app.route('/create-channel/', methods=['POST'])
def create_channel(headers="guest", body="anonymous"):
    """Create channel — forwarded to tracker.

    Protocol: POST /create-channel/
    """
    print("[ChatApp] Create-channel -> forwarding to tracker")
    try:
        data = json.loads(body) if body else {}
        result = _forward_to_tracker_sync('/create-channel/', data)
        if result:
            return json.dumps(result).encode('utf-8')
        return _error_response("Failed to create channel on tracker")
    except Exception as e:
        return _error_response(str(e))


@app.route('/join-channel/', methods=['POST'])
def join_channel(headers="guest", body="anonymous"):
    """Join channel — forwarded to tracker.

    Protocol: POST /join-channel/
    """
    print("[ChatApp] Join-channel -> forwarding to tracker")
    try:
        data = json.loads(body) if body else {}
        result = _forward_to_tracker_sync('/join-channel/', data)
        if result:
            return json.dumps(result).encode('utf-8')
        return _error_response("Failed to join channel on tracker")
    except Exception as e:
        return _error_response(str(e))


@app.route('/messages/', methods=['GET', 'POST'])
def get_messages(headers="guest", body="anonymous"):
    """Get messages — forwarded to tracker.

    Protocol: GET /messages/
    """
    print("[ChatApp] Messages -> forwarding to tracker")
    try:
        data = {}
        if body and body != "anonymous":
            try:
                data = json.loads(body)
            except Exception:
                pass
        result = _forward_to_tracker_sync('/messages/', data)
        if result:
            return json.dumps(result).encode('utf-8')
        return _error_response("Failed to get messages from tracker")
    except Exception as e:
        return _error_response(str(e))


# ============================================================
# P2P Routes (Chat Phase)
# ============================================================

@app.route('/broadcast-peer/', methods=['POST'])
async def broadcast_peer(headers="guest", body="anonymous"):
    """Broadcast a message to all connected peers.

    1. Forward to tracker for central storage + get list of peers to notify
    2. Notify each peer directly via P2P

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
        msg_timestamp = time.time()
        data['timestamp'] = msg_timestamp

        # Forward to tracker for storage and get peer list
        tracker_result = await _forward_to_tracker('/broadcast-peer/', data)

        delivered_to = []
        if tracker_result and tracker_result.get('status') == 'success':
            peers_to_notify = tracker_result.get('data', {}).get('peers_to_notify', [])
            stored_timestamp = tracker_result.get('data', {}).get('timestamp', msg_timestamp)

            # Notify each peer directly via P2P
            tasks = []
            for peer_info in peers_to_notify:
                # Skip notifying ourselves
                if int(peer_info.get('port', 0)) == _self_port:
                    continue
                delivered_to.append(peer_info["username"])
                tasks.append(_notify_peer_async(
                    peer_info["ip"],
                    peer_info["port"],
                    '/receive-message/',
                    {
                        "from": from_user,
                        "message": message,
                        "channel": channel_name,
                        "timestamp": stored_timestamp
                    }
                ))

            if tasks:
                await asyncio.gather(*tasks)

        return _json_response({
            "delivered_to": delivered_to,
            "message_id": tracker_result.get('data', {}).get('message_id', 0) if tracker_result else 0
        })
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


@app.route('/send-peer/', methods=['POST'])
async def send_peer(headers="guest", body="anonymous"):
    """Send a direct message to a specific peer.

    1. Forward to tracker for storage + get target peer info
    2. Send directly to target peer via P2P

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
        msg_timestamp = time.time()
        data['timestamp'] = msg_timestamp

        # Forward to tracker for storage
        tracker_result = await _forward_to_tracker('/send-peer/', data)

        dm_channel = ""
        if tracker_result and tracker_result.get('status') == 'success':
            dm_channel = tracker_result.get('data', {}).get('channel', '')
            target_peer = tracker_result.get('data', {}).get('target_peer')
            stored_timestamp = tracker_result.get('data', {}).get('timestamp', msg_timestamp)

            # Send directly to target peer via P2P
            if target_peer and int(target_peer.get('port', 0)) != _self_port:
                await _notify_peer_async(
                    target_peer["ip"],
                    target_peer["port"],
                    '/receive-message/',
                    {
                        "from": from_user,
                        "message": message,
                        "channel": dm_channel,
                        "timestamp": stored_timestamp
                    }
                )

        return _json_response({"delivered_to": to_user, "channel": dm_channel})
    except json.JSONDecodeError:
        return _error_response("Invalid JSON in request body")


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
        print("[ChatApp] P2P message received: {}".format(data))
        return _json_response({"received": True})
    except json.JSONDecodeError:
        return _error_response("Invalid JSON")


# ============================================================
# Entry Point
# ============================================================

def create_chatapp(ip, port, tracker_url=None):
    """Create and start the chat application peer server.

    :param ip (str): IP address to bind.
    :param port (int): Port number to listen on.
    :param tracker_url (str): URL of the centralized tracker (e.g. 'http://127.0.0.1:9000').
    """
    global TRACKER_URL, _tracker_ip, _tracker_port, _self_port

    _self_port = port

    if tracker_url:
        TRACKER_URL = tracker_url
        # Parse tracker IP and port from URL
        url = tracker_url.replace("http://", "").replace("https://", "")
        parts = url.split(":")
        _tracker_ip = parts[0]
        if len(parts) > 1:
            _tracker_port = int(parts[1].rstrip('/'))
    
    print("[ChatApp] Starting peer on {}:{}".format(ip, port))
    print("[ChatApp] Tracker at {}:{}".format(_tracker_ip, _tracker_port))
    app.prepare_address(ip, port)
    app.run()
