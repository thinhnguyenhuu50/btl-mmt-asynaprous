import os, datetime, mimetypes

BASE_DIR = os.getcwd() + "/"

class Response:
    def __init__(self):
        self._content = b""
        self._header = b""
        self.status_code = 200
        self.reason = "OK"
        self.headers = {}
        self.set_cookies = []

    def get_mime_type(self, path):
        mime, _ = mimetypes.guess_type(path)
        return mime or 'application/octet-stream'

    def build_response_header(self):

               
        status_line = f"HTTP/1.1 {self.status_code} {self.reason}\r\n"
        headers = {
            "Content-Type": self.headers.get('Content-Type', 'text/html'),
            "Content-Length": str(len(self._content)),
            "Date": datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "Connection": "close",
            "Server": "AsynapRous/2.0"
        }
        fmt = status_line
        for k, v in headers.items(): fmt += f"{k}: {v}\r\n"
        for c in self.set_cookies: fmt += f"Set-Cookie: {c}; Path=/; HttpOnly\r\n"
        return (fmt + "\r\n").encode('utf-8')

    def build_json_response(self, json_bytes, extra_cookies=None):
        self._content = json_bytes if isinstance(json_bytes, bytes) else json_bytes.encode('utf-8')
        self.headers['Content-Type'] = 'application/json'
        if extra_cookies: self.set_cookies.extend(extra_cookies)
        self._header = self.build_response_header()
        return self._header + self._content

    def build_notfound(self):
        return b"HTTP/1.1 404 Not Found\r\nContent-Length: 9\r\n\r\nNot Found"

    def build_response(self, request):
        
        path = request.path if request.path != '/' else '/index.html'
        mime_type = self.get_mime_type(path)
        if path.startswith('/uploads/'):
            folder = "public/uploads"
            path = path.replace('/uploads/', '', 1)
        elif mime_type.startswith('application/') and 'javascript' not in mime_type:
            folder = "apps"
        else:
             folder = "public"
        if mime_type.startswith('application/') and 'javascript' not in mime_type: folder = "apps"
        
        filepath = os.path.join(BASE_DIR, folder, path.lstrip('/'))
        try:
            with open(filepath, "rb") as f: self._content = f.read()
            self.headers['Content-Type'] = mime_type
            self._header = self.build_response_header()
            return self._header + self._content
        except:
            return self.build_notfound()