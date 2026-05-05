from .request import Request
from .response import Response
import asyncio, inspect, json

class HttpAdapter:
    def __init__(self, conn, addr, routes):
        self.conn, self.addr, self.routes = conn, addr, routes
        self.request, self.response = Request(), Response()

    def handle_client(self):
        try:
            raw_data = self.conn.recv(8192)
            if not raw_data: return
            
            if b'\r\n\r\n' in raw_data:
                headers_part, body_part = raw_data.split(b'\r\n\r\n', 1)
                content_length = 0
                
                for line in headers_part.decode('utf-8', errors='ignore').split('\r\n'):
                    if line.lower().startswith('content-length:'):
                        try: content_length = int(line.split(':')[1].strip())
                        except: pass
                
                while len(body_part) < content_length:
                    chunk = self.conn.recv(8192)
                    if not chunk: break
                    body_part += chunk
                    raw_data  += chunk
            
            self.request.prepare(raw_data, self.routes)
            
            if self.request.hook:
                result = self.request.hook(self.request.headers, self.request.body, self.request.cookies)
                
                extra_cookies = None
                if isinstance(result, tuple) and len(result) == 2:
                    result, extra_cookies = result
                    
                resp_body = json.dumps(result) if isinstance(result, dict) else str(result)
                out = self.response.build_json_response(resp_body, extra_cookies)
            else:
                out = self.response.build_response(self.request)
                
            self.conn.sendall(out)
        except Exception as e: print(f"Adapter Error: {e}")
        finally: self.conn.close()