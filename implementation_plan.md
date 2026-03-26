# Assignment 1 - Non-blocking HTTP Server & Chat Application

Implement a fully working non-blocking HTTP server with proxy/backend architecture, HTTP authentication, and a hybrid P2P chat application, using the provided AsynapRous framework.

## User Review Required

> [!IMPORTANT]
> The existing codebase has multiple bugs and incomplete TODOs. The approach is to fix all bugs first, then implement the required features: non-blocking mechanisms, authentication, and the chat application. All backend logic uses **only** Python standard library (no frameworks).

> [!WARNING]
> The `config/proxy.conf` will be updated for localhost (127.0.0.1) development. If you need to test on a different network, this must be adjusted.

---

## Proposed Changes

### Component 1: Foundation Bug Fixes

#### [MODIFY] [dictionary.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/dictionary.py)
- Fix `from collections import MutableMapping` → `from collections.abc import MutableMapping` (deprecated in Python 3.10+)

#### [MODIFY] [request.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/request.py)
- Fix crash: `self.headers` is accessed before being set in `prepare()`. Move `self.headers = self.prepare_headers(request)` before cookie parsing
- Fix typo: `self._raw_heaers` → `self._raw_headers`
- Properly split raw headers and body using `fetch_headers_body()`

#### [MODIFY] [utils.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/utils.py)
- Fix import: `from urlparse import urlparse` → `from urllib.parse import urlparse, unquote`

#### [MODIFY] [__init__.py (root)](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/__init__.py)
- Fix import path: `from app.sampleapp` → `from apps.sampleapp`

---

### Component 2: Non-blocking Mechanisms (2 pts)

#### [MODIFY] [proxy.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/proxy.py)
- In `run_proxy()`: after `conn, addr = proxy.accept()`, spawn a daemon thread: `threading.Thread(target=handle_client, args=(ip, port, conn, addr, routes), daemon=True).start()`

#### [MODIFY] [backend.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/backend.py)
- In `run_backend()` threading mode: spawn a daemon thread for each accepted connection: `threading.Thread(target=handle_client, args=(ip, port, conn, addr, routes), daemon=True).start()`
- Fix indentation error in coroutine handler (line 110)

---

### Component 3: HTTP Server Core (Response/Request Pipeline)

#### [MODIFY] [response.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/response.py)
- Fix `build_response_header()`: build a proper HTTP/1.1 status line + formatted headers string
- Fix `build_response()`: actually call `build_content()` to load the file, then `build_response_header()`, and store results in `self._content` and `self._header` before returning them
- Add image/js MIME type support in `build_response()`

#### [MODIFY] [httpadapter.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/httpadapter.py)
- Fix `handle_client()`: When `req.hook` exists (routed webapp), call the hook function with headers/body, then build a JSON response. When no hook, build a normal file-serving response using `resp.build_response(req)`
- Fix the coroutine handler similarly
- Fix `extract_cookies` property signature (can't have extra params on a property)

---

### Component 4: Authentication (2 pts)

#### [MODIFY] [request.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/request.py)
- Implement `prepare_cookies()`: parse `Cookie:` header into a dictionary
- Implement `prepare_auth()`: extract Basic auth from `Authorization:` header (base64 decode per RFC 2617)
- Add `self.auth` attribute to store decoded credentials

#### [MODIFY] [httpadapter.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/httpadapter.py)
- Add authentication check: for protected routes, verify the session cookie or `Authorization` header
- When login is successful, include `Set-Cookie: session_id=<token>` in the response

#### [NEW] [db/users.json](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/db/users.json)
- Simple JSON file storing user credentials: `{"user1": "password1", "user2": "password2"}`

#### [NEW] [daemon/auth.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/daemon/auth.py)
- Session store (in-memory dict) mapping session_id → username
- `authenticate(username, password)`: check against `db/users.json`
- `create_session(username)`: generate UUID session token, store in session dict
- `validate_session(session_id)`: check if session is valid
- `build_auth_challenge()`: build 401 response with `WWW-Authenticate: Basic` header (RFC 7235)

---

### Component 5: Chat Application (3 pts)

#### [NEW] [apps/chatapp.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/apps/chatapp.py)
Chat server using AsynapRous with these routes:

**Client-Server (Initialization Phase):**
- `POST /login/` — Authenticate user, return session cookie
- `POST /submit-info/` — Register peer IP:port with the tracker
- `POST /add-list/` — Add peer to active peers list
- `GET /get-list/` — Return list of active peers
- `GET /channels/` — List available channels

**P2P (Chat Phase):**
- `POST /connect-peer/` — Initiate P2P connection to a peer
- `POST /broadcast-peer/` — Broadcast message to all connected peers
- `POST /send-peer/` — Send message to a specific peer
- `GET /messages/` — Get messages for a channel
- `POST /create-channel/` — Create a new channel

**Data structures (in-memory):**
- `peers`: dict mapping peer_id → `{ip, port, username, last_seen}`
- `channels`: dict mapping channel_name → `{members, messages[]}`
- `connections`: dict mapping peer_id → list of connected peer_ids

#### [NEW] [start_chatapp.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/start_chatapp.py)
- Entry point script to start the chat server on a configurable port (default 8000)

#### [NEW] [www/chat.html](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/www/chat.html)
- Chat UI with: login form, channel list sidebar, message area, text input + send button
- JavaScript using `fetch()` for async communication (allowed per assignment rules)
- Periodic polling for new messages

#### [MODIFY] [config/proxy.conf](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/config/proxy.conf)
- Update to localhost addresses for development

#### [MODIFY] [apps/__init__.py](file:///c:/Users/thinh/Documents/HK_6/Computer_Networks/btl/btl-mmt-asynaprous/apps/__init__.py)
- Add `from .chatapp import create_chatapp`

---

## Verification Plan

### Automated Tests

**1. Server startup test** — run each server process and verify it binds successfully:
```
python start_backend.py --server-port 9000
python start_proxy.py --server-port 8080
python start_sampleapp.py --server-port 2026
python start_chatapp.py --server-port 8000
```

**2. HTTP request/response test** — use `curl` or Python script to test:
```
# Start backend in one terminal
python start_backend.py --server-port 9000

# Test static file serving
curl http://127.0.0.1:9000/index.html

# Test sample app routes
python start_sampleapp.py --server-port 2026
curl -X POST http://127.0.0.1:2026/login
curl -X POST http://127.0.0.1:2026/echo -d '{"text":"hello"}'
```

**3. Authentication test:**
```
# Test that protected routes return 401
curl -v http://127.0.0.1:8000/get-list/

# Test login and cookie
curl -v -X POST http://127.0.0.1:8000/login/ -d '{"username":"user1","password":"password1"}'
# Use cookie from response for subsequent requests
curl -v -b "session_id=<token>" http://127.0.0.1:8000/get-list/
```

**4. Chat application test:**
```
# Start chat server
python start_chatapp.py --server-port 8000

# Register peer
curl -X POST http://127.0.0.1:8000/submit-info/ -d '{"ip":"127.0.0.1","port":8001}'

# Get peer list
curl http://127.0.0.1:8000/get-list/

# Send message
curl -X POST http://127.0.0.1:8000/send-peer/ -d '{"to":"peer1","message":"hello"}'
```

### Manual Verification

The user should test the full flow by:
1. Open browser to `http://127.0.0.1:8000/chat.html` (or via proxy at port 8080)
2. Log in with credentials from `db/users.json`
3. See peers list, join/create channels, send messages
4. Open a second browser tab as a different user to test P2P messaging
