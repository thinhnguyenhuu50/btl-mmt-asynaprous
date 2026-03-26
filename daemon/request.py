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
daemon.request
~~~~~~~~~~~~~~~~~

This module provides a Request object to manage and persist 
request settings (cookies, auth, proxies).
"""
from .dictionary import CaseInsensitiveDict
import base64

class Request():
    """The fully mutable "class" `Request <Request>` object,
    containing the exact bytes that will be sent to the server.

    Instances are generated from a "class" `Request <Request>` object, and
    should not be instantiated manually; doing so may produce undesirable
    effects.

    Usage::

      >>> import deamon.request
      >>> req = request.Request()
      ## Incoming message obtain aka. incoming_msg
      >>> r = req.prepare(incoming_msg)
      >>> r
      <Request>
    """
    __attrs__ = [
        "method",
        "url",
        "headers",
        "body",
        "_raw_headers",
        "_raw_body",
        "reason",
        "cookies",
        "body",
        "routes",
        "hook",
    ]

    def __init__(self):
        #: HTTP verb to send to the server.
        self.method = None
        #: HTTP URL to send the request to.
        self.url = None
        #: dictionary of HTTP headers.
        self.headers = {}
        #: HTTP path
        self.path = None        
        # The cookies set used to create Cookie header
        self.cookies = {}
        #: request body to send to the server.
        self.body = None
        # The raw header
        self._raw_headers = None
        #: The raw body
        self._raw_body = None
        #: Routes
        self.routes = {}
        #: Hook point for routed mapped-path
        self.hook = None
        #: Authentication credentials (username, password)
        self.auth = None

    def extract_request_line(self, request):
        try:
            lines = request.splitlines()
            first_line = lines[0]
            method, path, version = first_line.split()

            if path == '/':
                path = '/index.html'
        except Exception:
            return None, None, None

        return method, path, version
             
    def prepare_headers(self, request):
        """Prepares the given HTTP headers."""
        lines = request.split('\r\n')
        headers = {}
        for line in lines[1:]:
            if ': ' in line:
                key, val = line.split(': ', 1)
                headers[key.lower()] = val
        return headers

    def fetch_headers_body(self, request):
        """Prepares the given HTTP headers."""
        # Split request into header section and body section
        parts = request.split("\r\n\r\n", 1)  # split once at blank line

        _headers = parts[0]
        _body = parts[1] if len(parts) > 1 else ""
        return _headers, _body

    def prepare(self, request, routes=None):
        """Prepares the entire request with the given parameters."""

        # Prepare the request line from the request header
        print("[Request] prepare request msg {}".format(request[:200] if request else ""))
        self.method, self.path, self.version = self.extract_request_line(request)
        print("[Request] {} path {} version {}".format(self.method, self.path, self.version))

        # Split raw headers and body
        self._raw_headers, self._raw_body = self.fetch_headers_body(request)
        self.body = self._raw_body

        # Parse headers into dictionary
        self.headers = self.prepare_headers(request)

        # Parse cookies from Cookie header (RFC 6265)
        cookie_str = self.headers.get('cookie', '')
        self.cookies = {}
        if cookie_str:
            for pair in cookie_str.split(';'):
                pair = pair.strip()
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    self.cookies[key.strip()] = value.strip()

        # Parse Basic auth from Authorization header (RFC 2617/7235)
        auth_header = self.headers.get('authorization', '')
        if auth_header.startswith('Basic '):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
                username, password = decoded.split(':', 1)
                self.auth = (username, password)
            except Exception:
                self.auth = None

        #
        # @bksysnet Preparing the webapp hook with AsynapRous instance
        # The default behaviour with HTTP server is empty routed
        #
        if routes and routes != {}:
            self.routes = routes
            print("[Request] Routing METHOD {} path {}".format(self.method, self.path))
            self.hook = routes.get((self.method, self.path))
            print("[Request] Hook has request {}".format(self.hook))

        return

    def prepare_body(self, data, files, json=None):
        if data:
            self.body = data
        self.prepare_content_length(self.body)
        return

    def prepare_content_length(self, body):
        if body:
            self.headers["Content-Length"] = str(len(body))
        else:
            self.headers["Content-Length"] = "0"
        return

    def prepare_auth(self, auth, url=""):
        """Prepare the request authentication.

        :param auth: tuple of (username, password)
        :param url: optional URL
        """
        if auth and len(auth) == 2:
            credentials = base64.b64encode(
                "{}:{}".format(auth[0], auth[1]).encode('utf-8')
            ).decode('utf-8')
            self.headers["Authorization"] = "Basic {}".format(credentials)
            self.auth = auth
        return

    def prepare_cookies(self, cookies):
        """Prepare the Cookie header from a cookies dictionary.

        :param cookies: dict of cookie key-value pairs
        """
        if isinstance(cookies, dict):
            cookie_str = '; '.join(
                '{}={}'.format(k, v) for k, v in cookies.items()
            )
            self.headers["Cookie"] = cookie_str
        elif isinstance(cookies, str):
            self.headers["Cookie"] = cookies
