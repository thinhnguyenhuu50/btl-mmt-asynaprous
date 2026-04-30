from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import time

class TrackerHandler(BaseHTTPRequestHandler):
    active_peers = {} 

    def do_POST(self):
        if self.path == '/register':
            length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            peer_url = data.get('peer')
            
            if peer_url:
                TrackerHandler.active_peers[peer_url] = time.time()
                print(f"📍 [Tracker] Báo danh: {peer_url}")
            
            # Chỉ trả về các Node còn sống (báo cáo trong 60 giây qua)
            now = time.time()
            alive = [p for p, t in TrackerHandler.active_peers.items() if now - t < 60]
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'active_peers': alive}).encode('utf-8'))

    def log_message(self, format, *args): pass

if __name__ == '__main__':
    print("🚀 [SERVER TRUNG TÂM] Đang chạy tại port 8000 (Sẵn sàng nhận IP LAN)...")
    HTTPServer(('0.0.0.0', 8000), TrackerHandler).serve_forever()