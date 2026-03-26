#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course,
# and is released under the "MIT License Agreement". Please see the LICENSE
# file that should have been included as part of this package.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#


"""
start_backend
~~~~~~~~~~~~~~~~~

This module provides the entry point for deploying the centralized tracker
server. The tracker maintains the global peer registry, channel list, and
message history. Peer applications (start_chatapp.py) register with and
query this tracker to discover other peers and synchronize messages.
"""

import socket
import argparse

from apps.tracker import create_tracker

# Default port number used if none is specified via command-line arguments.
PORT = 9000 

if __name__ == "__main__":
    """
    Entry point for launching the tracker server.

    This block parses command-line arguments to determine the server's IP address
    and port. It then calls `create_tracker(ip, port)` to start the centralized
    tracker that manages peer registration and message history.

    :arg --server-ip (str): IP address to bind the server (default: 0.0.0.0).
    :arg --server-port (int): Port number to bind the server (default: 9000).
    """

    parser = argparse.ArgumentParser(
        prog='Tracker',
        description='Start the centralized tracker server',
        epilog='Tracker daemon for hybrid P2P chat application'
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

    create_tracker(ip, port)
