import base64

class Request:
    def __init__(self):
        self.method = self.path = self.version = self.body = self.hook = None
        self.headers, self.cookies = {}, {}
        self.auth = None

    def prepare_auth(self, auth_header):
        if not auth_header or not auth_header.lower().startswith('basic '):
            return None
        try:
            decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
            username, password = decoded.split(':', 1)
            return (username, password)
        except Exception:
            return None

    def prepare(self, raw_request, routes=None):
        try:
            parts = raw_request.split(b"\r\n\r\n", 1)
            header_lines = parts[0].decode('utf-8', errors='ignore').split("\r\n")
            self.body = parts[1] if len(parts) > 1 else b""
            first_line = header_lines[0].split()
            self.method, self.path = first_line[0], first_line[1]
            
            for line in header_lines[1:]:
                if ': ' in line:
                    k, v = line.split(': ', 1)
                    self.headers[k.lower()] = v
            
            # Xử lý Auth
            if 'authorization' in self.headers:
                self.auth = self.prepare_auth(self.headers['authorization'])

            # Xử lý Cookies
            if 'cookie' in self.headers:
                for p in self.headers['cookie'].split(';'):
                    if '=' in p:
                        k, v = p.strip().split('=', 1)
                        self.cookies[k] = v
                        
            if routes: self.hook = routes.get((self.method, self.path))
        except Exception as e:
            print(f"[Request] Parse error: {e}")