import socket
import threading
import argparse
import re
from urllib.parse import urlparse
from collections import defaultdict

from daemon import create_proxy

PROXY_PORT = 8080

def parse_virtual_hosts(config_file):
    """
    Parses virtual host blocks from a config file.
    """
    print(f"\n🔍 [Proxy Config] Đang đọc file cấu hình: {config_file}")

    try:
        with open(config_file, 'r') as f:
            config_text = f.read()
    except FileNotFoundError:
        print(f"❌ LỖI: Không tìm thấy file {config_file}")
        return {}

    # Match each host block
    host_blocks = re.findall(r'host\s+"([^"]+)"\s*\{(.*?)\}', config_text, re.DOTALL)

    routes = {}
    print(f"✅ Tìm thấy {len(host_blocks)} host định nghĩa trong file.\n" + "-"*50)

    for host, block in host_blocks:
        proxy_map = {}
        # Find all proxy_pass entries
        proxy_passes = re.findall(r'proxy_pass\s+http://([^\s;]+);', block)
        
        # Find dist_policy
        policy_match = re.search(r'dist_policy\s+(\w+)', block)
        dist_policy_map = policy_match.group(1) if policy_match else 'round-robin'

        # Xây dựng routes
        if len(proxy_passes) == 1:
            routes[host] = (proxy_passes[0], dist_policy_map)
        else:
            routes[host] = (proxy_passes, dist_policy_map)

        # PRINT CHI TIẾT TỪNG HOST RA TERMINAL
        print(f"🌐 Host: {host}")
        print(f"   -> Chuyển hướng tới: {proxy_passes}")
        print(f"   -> Chính sách: {dist_policy_map}")
        print("-"*50)

    return routes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='Proxy', description='', epilog='Proxy daemon')
    parser.add_argument('--server-ip', default='0.0.0.0')
    parser.add_argument('--server-port', type=int, default=PROXY_PORT)
 
    args = parser.parse_args()
    ip = args.server_ip
    port = args.server_port

    # Đọc routes
    routes = parse_virtual_hosts("config/proxy.conf")

    if not routes:
        print("⚠️ CẢNH BÁO: Không có route nào được nạp. Proxy có thể không hoạt động đúng.")

    print(f"🚀 [PROXY START] Đang chạy tại {ip}:{port}...")
    create_proxy(ip, port, routes)