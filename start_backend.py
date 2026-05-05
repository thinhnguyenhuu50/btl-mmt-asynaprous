import socket
import argparse

from daemon import create_backend 

import apps.chatapp
from apps.chatapp import app as chat_app_instance
PORT = 9000 

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='Backend',
        description='Start the backend process',
        epilog='Backend daemon for http_deamon application'
    )
    parser.add_argument('--server-ip',
        type=str,
        default='0.0.0.0',
        help='IP address to bind the server. Default is 0.0.0.0'
    )
    parser.add_argument(
        '--server-port',
        type=int,
        default=PORT,
        help='Port number to bind the server. Default is {}.'.format(PORT)
    )
 
    args = parser.parse_args()
    ip = args.server_ip
    port = args.server_port

    apps.chatapp.CURRENT_PORT = port

    apps.chatapp.create_chatapp(args.server_ip, args.server_port)