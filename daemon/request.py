import base64

class Request:
    def __init__(self):
        self.method = self.path = self.version = self.body = self.hook = None
        self.headers, self.cookies = {}, {}

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

            if 'cookie' in self.headers:
                for p in self.headers['cookie'].split(';'):
                    if '=' in p:
                        k, v = p.strip().split('=', 1)
                        self.cookies[k] = v

            if routes: self.hook = routes.get((self.method, self.path))
        except Exception as e:
            print(f"[Request] Parse error: {e}")