#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynApRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.response
~~~~~~~~~~~~~~~~~

This module provides a :class: `Response <Response>` object to manage and persist 
response settings (cookies, auth, proxies), and to construct HTTP responses
based on incoming requests. 

The current version supports MIME type detection, content loading and header formatting
"""
import datetime
import os
import mimetypes
from .dictionary import CaseInsensitiveDict

BASE_DIR = ""

class Response():   
    """The :class:`Response <Response>` object, which contains a
    server's response to an HTTP request.

    Instances are generated from a :class:`Request <Request>` object, and
    should not be instantiated manually; doing so may produce undesirable
    effects.

    :class:`Response <Response>` object encapsulates headers, content, 
    status code, cookies, and metadata related to the request-response cycle.
    It is used to construct and serve HTTP responses in a custom web server.

    :attrs status_code (int): HTTP status code (e.g., 200, 404).
    :attrs headers (dict): dictionary of response headers.
    :attrs url (str): url of the response.
    :attrsencoding (str): encoding used for decoding response content.
    :attrs history (list): list of previous Response objects (for redirects).
    :attrs reason (str): textual reason for the status code (e.g., "OK", "Not Found").
    :attrs cookies (CaseInsensitiveDict): response cookies.
    :attrs elapsed (datetime.timedelta): time taken to complete the request.
    :attrs request (PreparedRequest): the original request object.

    Usage::

      >>> import Response
      >>> resp = Response()
      >>> resp.build_response(req)
      >>> resp
      <Response>
    """

    __attrs__ = [
        "_content",
        "_header",
        "status_code",
        "method",
        "headers",
        "url",
        "history",
        "encoding",
        "reason",
        "cookies",
        "elapsed",
        "request",
        "body",
        "reason",
    ]


    def __init__(self, request=None):
        """
        Initializes a new :class:`Response <Response>` object.

        : params request : The originating request object.
        """

        self._content = b""
        self._header = b""
        self._content_consumed = False
        self._next = None

        #: Integer Code of responded HTTP Status, e.g. 404 or 200.
        self.status_code = 200

        #: Case-insensitive Dictionary of Response Headers.
        self.headers = {}

        #: URL location of Response.
        self.url = None

        #: Encoding to decode with when accessing response text.
        self.encoding = None

        #: A list of :class:`Response <Response>` objects from
        #: the history of the Request.
        self.history = []

        #: Textual reason of responded HTTP Status, e.g. "Not Found" or "OK".
        self.reason = "OK"

        #: A of Cookies the response headers.
        self.cookies = CaseInsensitiveDict()

        #: The amount of time elapsed between sending the request
        self.elapsed = datetime.timedelta(0)

        #: The :class:`PreparedRequest <PreparedRequest>` object to which this
        #: is a response.
        self.request = None

        #: Extra cookies to set in the response (list of Set-Cookie values)
        self.set_cookies = []


    def get_mime_type(self, path):
        """
        Determines the MIME type of a file based on its path.

        "params path (str): Path to the file.

        :rtype str: MIME type string (e.g., 'text/html', 'image/png').
        """

        try:
            mime_type, _ = mimetypes.guess_type(path)
        except Exception:
            return 'application/octet-stream'
        return mime_type or 'application/octet-stream'


    def prepare_content_type(self, mime_type='text/html'):
        """
        Prepares the Content-Type header and determines the base directory
        for serving the file based on its MIME type.

        All web assets (HTML, CSS, JS, images, etc.) are served from the
        unified ``public/`` directory.

        :params mime_type (str): MIME type of the requested resource.

        :rtype str: Base directory path for locating the resource.

        :raises ValueError: If the MIME type is unsupported.
        """
        
        base_dir = ""

        # Validate header attr existence
        if not hasattr(self, "headers") or self.headers is None:
            self.headers = {}

        # Processing mime_type based on main_type and sub_type
        main_type, sub_type = mime_type.split('/', 1)
        print("[Response] Processing main_type={} sub_type={}".format(main_type,sub_type))
        if main_type == 'text':
            self.headers['Content-Type']='text/{}'.format(sub_type)
            base_dir = BASE_DIR+"public/"
        elif main_type == 'image':
            base_dir = BASE_DIR+"public/"
            self.headers['Content-Type']='image/{}'.format(sub_type)
        elif main_type == 'application':
            if sub_type == 'javascript':
                base_dir = BASE_DIR+"public/"
            else:
                base_dir = BASE_DIR+"apps/"
            self.headers['Content-Type']='application/{}'.format(sub_type)
        elif main_type == 'video':
            base_dir = BASE_DIR+"public/"
            self.headers['Content-Type']='video/{}'.format(sub_type)
        else:
            base_dir = BASE_DIR+"public/"
            self.headers['Content-Type'] = mime_type

        return base_dir


    def build_content(self, path, base_dir):
        """
        Loads the objects file from storage space.

        :params path (str): relative path to the file.
        :params base_dir (str): base directory where the file is located.

        :rtype tuple: (int, bytes) representing content length and content data.
        """

        filepath = os.path.join(base_dir, path.lstrip('/'))

        print("[Response] Serving the object at location {}".format(filepath))
        try:
            with open(filepath, "rb") as f:
               content = f.read()
        except Exception as e:
            print("[Response] build_content exception: {}".format(e))
            return -1, b""
        return len(content), content


    def build_response_header(self, request):
        """
        Constructs the HTTP response headers based on the class:`Request <Request>
        and internal attributes.

        :params request (class:`Request <Request>`): incoming request object.

        :rtypes bytes: encoded HTTP response header.
        """
        # Status line
        status_line = "HTTP/1.1 {} {}".format(self.status_code, self.reason)

        # Build dynamic headers
        headers = {
            "Content-Type": self.headers.get('Content-Type', 'text/html'),
            "Content-Length": str(len(self._content)),
            "Date": datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "Cache-Control": "no-cache",
            "Connection": "close",
            "Server": "AsynapRous/1.0",
        }

        # Add Set-Cookie headers if present
        cookie_headers = ""
        for cookie in self.set_cookies:
            cookie_headers += "Set-Cookie: {}\r\n".format(cookie)

        # Format the header string
        fmt_header = status_line + "\r\n"
        for key, value in headers.items():
            fmt_header += "{}: {}\r\n".format(key, value)
        fmt_header += cookie_headers
        fmt_header += "\r\n"

        return fmt_header.encode('utf-8')


    def build_notfound(self):
        """
        Constructs a standard 404 Not Found HTTP response.

        :rtype bytes: Encoded 404 response.
        """

        return (
                "HTTP/1.1 404 Not Found\r\n"
                "Accept-Ranges: bytes\r\n"
                "Content-Type: text/html\r\n"
                "Content-Length: 13\r\n"
                "Cache-Control: max-age=86000\r\n"
                "Connection: close\r\n"
                "\r\n"
                "404 Not Found"
            ).encode('utf-8')

    def build_unauthorized(self):
        """
        Constructs a 401 Unauthorized HTTP response with WWW-Authenticate header (RFC 7235).

        :rtype bytes: Encoded 401 response.
        """
        body = "401 Unauthorized - Please provide valid credentials"
        return (
            "HTTP/1.1 401 Unauthorized\r\n"
            "WWW-Authenticate: Basic realm=\"AsynapRous Server\"\r\n"
            "Content-Type: text/plain\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n"
            "\r\n"
            "{}".format(len(body), body)
        ).encode('utf-8')

    def build_json_response(self, json_bytes, extra_cookies=None):
        """
        Builds a complete HTTP response for JSON data.

        :params json_bytes (bytes): JSON content as bytes.
        :params extra_cookies (list): optional list of Set-Cookie values.
        :rtype bytes: complete HTTP response.
        """
        self._content = json_bytes if isinstance(json_bytes, bytes) else json_bytes.encode('utf-8')
        self.headers['Content-Type'] = 'application/json'
        self.status_code = 200
        self.reason = "OK"

        if extra_cookies:
            self.set_cookies = extra_cookies

        self._header = self.build_response_header(None)
        return self._header + self._content

    def build_response(self, request, envelop_content=None):
        """
        Builds a full HTTP response including headers and content based on the request.

        :params request (class:`Request <Request>`): incoming request object.

        :rtype bytes: complete HTTP response using prepared headers and content.
        """
        print("[Response] Start build response with req {}".format(request))

        path = request.path

        mime_type = self.get_mime_type(path)
        print("[Response] {} path {} mime_type {}".format(request.method, request.path, mime_type))

        base_dir = ""

        # If HTML, parse and serve embedded objects
        if path.endswith('.html') or mime_type == 'text/html':
            base_dir = self.prepare_content_type(mime_type = 'text/html')
        elif mime_type == 'text/css':
            base_dir = self.prepare_content_type(mime_type = 'text/css')
        elif mime_type in ('text/javascript', 'application/javascript'):
            base_dir = self.prepare_content_type(mime_type = mime_type)
        elif mime_type.startswith('image/'):
            base_dir = self.prepare_content_type(mime_type = mime_type)
        elif mime_type == 'application/json' or mime_type == 'application/octet-stream':
            base_dir = self.prepare_content_type(mime_type = 'application/json')
            if envelop_content:
                self._content = envelop_content if isinstance(envelop_content, bytes) else envelop_content.encode('utf-8')
                self._header = self.build_response_header(request)
                return self._header + self._content
        else:
            # Try to serve from static for unknown types
            base_dir = self.prepare_content_type(mime_type=mime_type)

        # Load content from file
        content_length, content = self.build_content(path, base_dir)

        if content_length < 0:
            return self.build_notfound()

        # Store content and build headers
        self._content = content
        self.status_code = 200
        self.reason = "OK"
        self._header = self.build_response_header(request)

        return self._header + self._content
