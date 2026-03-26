#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.httpadapter
~~~~~~~~~~~~~~~~~

This module provides a http adapter object to manage and persist 
http settings (headers, bodies). The adapter supports both
raw URL paths and RESTful route definitions, and integrates with
Request and Response objects to handle client-server communication.
"""

from .request import Request
from .response import Response
from .dictionary import CaseInsensitiveDict

import asyncio
import inspect
import json

class HttpAdapter:
    """
    A mutable :class:`HTTP adapter <HTTP adapter>` for managing client connections
    and routing requests.

    The `HttpAdapter` class encapsulates the logic for receiving HTTP requests,
    dispatching them to appropriate route handlers, and constructing responses.
    It supports RESTful routing via hooks and integrates with :class:`Request <Request>` 
    and :class:`Response <Response>` objects for full request lifecycle management.

    Attributes:
        ip (str): IP address of the client.
        port (int): Port number of the client.
        conn (socket): Active socket connection.
        connaddr (tuple): Address of the connected client.
        routes (dict): Mapping of route paths to handler functions.
        request (Request): Request object for parsing incoming data.
        response (Response): Response object for building and sending replies.
    """

    __attrs__ = [
        "ip",
        "port",
        "conn",
        "connaddr",
        "routes",
        "request",
        "response",
    ]

    def __init__(self, ip, port, conn, connaddr, routes):
        """
        Initialize a new HttpAdapter instance.

        :param ip (str): IP address of the client.
        :param port (int): Port number of the client.
        :param conn (socket): Active socket connection.
        :param connaddr (tuple): Address of the connected client.
        :param routes (dict): Mapping of route paths to handler functions.
        """

        #: IP address.
        self.ip = ip
        #: Port.
        self.port = port
        #: Connection
        self.conn = conn
        #: Connection address
        self.connaddr = connaddr
        #: Routes
        self.routes = routes
        #: Request
        self.request = Request()
        #: Response
        self.response = Response()

    def handle_client(self, conn, addr, routes):
        """
        Handle an incoming client connection.

        This method reads the request from the socket, prepares the request object,
        invokes the appropriate route handler if available, builds the response,
        and sends it back to the client.

        :param conn (socket): The client socket connection.
        :param addr (tuple): The client's address.
        :param routes (dict): The route mapping for dispatching requests.
        """

        # Connection handler.
        self.conn = conn        
        # Connection address.
        self.connaddr = addr
        # Request handler
        req = self.request
        # Response handler
        resp = self.response

        try:
            # Handle the request
            msg = conn.recv(4096).decode('utf-8', errors='replace')
            if not msg:
                conn.close()
                return

            req.prepare(msg, routes)
            print("[HttpAdapter] Invoke handle_client connection {}".format(addr))

            response = b""

            # Handle request hook (routed webapp endpoints)
            if req.hook:
                # Call the registered route handler
                print("[HttpAdapter] Dispatching to hook: {}".format(req.hook))
                try:
                    # Extract headers and body for the handler
                    headers_str = json.dumps(req.headers) if req.headers else "{}"
                    body_str = req.body if req.body else ""

                    if inspect.iscoroutinefunction(req.hook):
                        # Run async handler
                        loop = asyncio.new_event_loop()
                        result = loop.run_until_complete(req.hook(headers_str, body_str))
                        loop.close()
                    else:
                        result = req.hook(headers_str, body_str)

                    # Check if handler returned (result, cookies_list) tuple
                    extra_cookies = None
                    if isinstance(result, tuple) and len(result) == 2:
                        result, extra_cookies = result

                    # Build JSON response from handler result
                    if isinstance(result, bytes):
                        response = resp.build_json_response(result, extra_cookies=extra_cookies)
                    elif isinstance(result, str):
                        response = resp.build_json_response(result.encode('utf-8'), extra_cookies=extra_cookies)
                    elif isinstance(result, dict):
                        response = resp.build_json_response(
                            json.dumps(result).encode('utf-8'), extra_cookies=extra_cookies
                        )
                    else:
                        response = resp.build_json_response(
                            json.dumps({"result": str(result)}).encode('utf-8'), extra_cookies=extra_cookies
                        )
                except Exception as e:
                    print("[HttpAdapter] Hook error: {}".format(e))
                    error_data = json.dumps({"error": str(e)}).encode('utf-8')
                    resp.status_code = 500
                    resp.reason = "Internal Server Error"
                    response = resp.build_json_response(error_data)
            else:
                # No hook — serve static file
                response = resp.build_response(req)

            print("[HttpAdapter] Sending response ({} bytes)".format(len(response)))
            conn.sendall(response)
        except Exception as e:
            print("[HttpAdapter] Error handling client {}: {}".format(addr, e))
        finally:
            conn.close()

    async def handle_client_coroutine(self, reader, writer):
        """
        Handle an incoming client connection using stream reader writer asynchronously.

        This method reads the request from the socket, prepares the request object,
        invokes the appropriate route handler if available, builds the response,
        and sends it back to the client.

        :param reader (StreamReader): The async stream reader.
        :param writer (StreamWriter): The async stream writer.
        """
        # Request handler
        req = self.request
        # Response handler
        resp = self.response

        addr = writer.get_extra_info("peername")
        print("[HttpAdapter] Invoke handle_client_coroutine connection {})".format(addr))

        try:
            # Handle the request asynchronously
            msg = await reader.read(4096)
            if not msg:
                writer.close()
                return

            req.prepare(msg.decode("utf-8", errors='replace'), routes={})

            response = b""

            # Handle request hook
            if req.hook:
                headers_str = json.dumps(req.headers) if req.headers else "{}"
                body_str = req.body if req.body else ""

                if inspect.iscoroutinefunction(req.hook):
                    result = await req.hook(headers_str, body_str)
                else:
                    result = req.hook(headers_str, body_str)

                if isinstance(result, bytes):
                    response = resp.build_json_response(result)
                elif isinstance(result, dict):
                    response = resp.build_json_response(
                        json.dumps(result).encode('utf-8')
                    )
                else:
                    response = resp.build_json_response(
                        str(result).encode('utf-8')
                    )
            else:
                # Build static response
                response = resp.build_response(req)

            # Send response asynchronously
            writer.write(response)
            await writer.drain()
        except Exception as e:
            print("[HttpAdapter] Coroutine error: {}".format(e))
        finally:
            writer.close()

    def extract_cookies(self, req):
        """
        Extract cookies from the :class:`Request <Request>` headers.

        :param req: The :class:`Request <Request>` object.
        :rtype: dict - A dictionary of cookie key-value pairs.
        """
        cookies = {}
        if hasattr(req, 'cookies') and req.cookies:
            return req.cookies
        
        # Fallback: parse from raw headers
        if hasattr(req, 'headers') and req.headers:
            cookie_str = req.headers.get('cookie', '')
            if cookie_str:
                for pair in cookie_str.split(';'):
                    pair = pair.strip()
                    if '=' in pair:
                        key, value = pair.split('=', 1)
                        cookies[key.strip()] = value.strip()
        return cookies

    def add_headers(self, request):
        """
        Add headers to the request.

        This method is intended to be overridden by subclasses to inject
        custom headers. It does nothing by default.

        
        :param request: :class:`Request <Request>` to add headers to.
        """
        pass

    def build_proxy_headers(self, proxy):
        """Returns a dictionary of the headers to add to any request sent
        through a proxy. 

        :class:`HttpAdapter <HttpAdapter>`.

        :param proxy: The url of the proxy being used for this request.
        :rtype: dict
        """
        headers = {}
        username, password = ("user1", "password")

        if username:
            headers["Proxy-Authorization"] = (username, password)

        return headers