#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#

"""
start_chatapp
~~~~~~~~~~~~~~~~~

This module provides the entry point for launching the hybrid chat application
server using the AsynapRous framework. The chat application combines
client-server paradigm (for peer registration and discovery) and
peer-to-peer paradigm (for direct messaging between peers).

It parses command-line arguments to configure the server's IP address
and port, then launches the chat application server.
"""

import json
import socket
import argparse

from apps.chatapp import create_chatapp

PORT = 8000  # Default port for chat application

if __name__ == "__main__":
    """
    Entry point for launching the chat application server.

    :arg --server-ip (str): IP address to bind the server (default: 0.0.0.0).
    :arg --server-port (int): Port number to bind the server (default: 8000).
    """

    parser = argparse.ArgumentParser(
        prog='ChatApp',
        description='Start the hybrid chat application server',
        epilog='ChatApp daemon using AsynapRous framework'
    )
    parser.add_argument('--server-ip', default='0.0.0.0',
        help='IP address to bind the server. Default is 0.0.0.0')
    parser.add_argument('--server-port', type=int, default=PORT,
        help='Port number to bind the server. Default is {}.'.format(PORT))

    args = parser.parse_args()
    ip = args.server_ip
    port = args.server_port

    # Prepare and launch the chat application
    create_chatapp(ip, port)
