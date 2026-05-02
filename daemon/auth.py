#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#

"""
daemon.auth
~~~~~~~~~~~~~~~~~

This module implements HTTP authentication and session management
based on RFC 2617 (Basic/Digest Authentication), RFC 7235 (HTTP/1.1 Authentication),
and RFC 6265 (HTTP State Management / Cookies).

It provides:
- User credential verification against a JSON-based user store
- Session creation and validation using UUID tokens
- Cookie-based session persistence
- WWW-Authenticate challenge response for unauthorized requests

The session store is maintained in-memory as a dictionary mapping
session_id (UUID string) → username. Sessions do not expire in this
simple implementation.
"""

import json
import uuid
import os
import base64

# In-memory session store: session_id -> {username, created_at}
_sessions = {}

# Path to user credentials database
_USER_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "users.json")


def _load_users():
    """Load user credentials from the JSON database file.

    :rtype: dict mapping username -> password
    """
    try:
        with open(_USER_DB_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        print("[Auth] Error loading users database: {}".format(e))
        return {}


def authenticate(username, password):
    """Authenticate a user against the credentials database.

    Implements the server-side verification described in RFC 2617 Section 2:
    the server checks the provided credentials against its user store.

    :param username (str): The username to authenticate.
    :param password (str): The password to verify.
    :rtype: bool - True if credentials are valid, False otherwise.
    """
    users = _load_users()
    stored_password = users.get(username)
    if stored_password and stored_password == password:
        print("[Auth] User '{}' authenticated successfully".format(username))
        return True
    print("[Auth] Authentication failed for user '{}'".format(username))
    return False


def create_session(username):
    """Create a new session for an authenticated user.

    Generates a UUID-based session token and stores it in the in-memory
    session table. The token is intended to be sent to the client via
    the Set-Cookie header as defined in RFC 6265 Section 4.1.

    :param username (str): The authenticated username.
    :rtype: str - The generated session ID (UUID string).
    """
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "username": username,
    }
    print("[Auth] Session created for '{}': {}".format(username, session_id))
    return session_id


def validate_session(session_id):
    """Validate an existing session by its ID.

    Checks the in-memory session store to verify the session exists.
    This corresponds to the server-side cookie validation described
    in RFC 6265 Section 5.4.

    :param session_id (str): The session ID to validate.
    :rtype: str or None - The username if session is valid, None otherwise.
    """
    session = _sessions.get(session_id)
    if session:
        return session["username"]
    return None


def get_session_username(session_id):
    """Get the username associated with a session.

    :param session_id (str): The session ID.
    :rtype: str or None - The username or None if session not found.
    """
    return validate_session(session_id)


def invalidate_session(session_id):
    """Remove a session (logout).

    :param session_id (str): The session ID to invalidate.
    """
    if session_id in _sessions:
        username = _sessions[session_id]["username"]
        del _sessions[session_id]
        print("[Auth] Session invalidated for '{}'".format(username))


def parse_basic_auth(auth_header):
    """Parse a Basic Authentication header value.

    Per RFC 2617 Section 2, the Authorization header for Basic auth
    has the format: Basic <base64(username:password)>

    :param auth_header (str): The value of the Authorization header.
    :rtype: tuple or None - (username, password) if valid, None otherwise.
    """
    if not auth_header or not auth_header.startswith('Basic '):
        return None
    try:
        decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        username, password = decoded.split(':', 1)
        return (username, password)
    except Exception:
        return None


def build_auth_challenge():
    """Build a 401 Unauthorized response with WWW-Authenticate header.

    Per RFC 7235 Section 4.1, when a server receives a request for a
    protected resource without valid credentials, it MUST respond with
    a 401 status and include a WWW-Authenticate header specifying the
    authentication scheme.

    :rtype: bytes - Complete HTTP 401 response.
    """
    body = '{"error": "Unauthorized", "message": "Please provide valid credentials"}'
    response = (
        "HTTP/1.1 401 Unauthorized\r\n"
        "WWW-Authenticate: Basic realm=\"AsynapRous Server\"\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
        "\r\n"
        "{}".format(len(body), body)
    )
    return response.encode('utf-8')
