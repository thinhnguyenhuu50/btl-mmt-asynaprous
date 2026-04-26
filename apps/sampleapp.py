#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course,
# and is released under the "MIT License Agreement". Please see the LICENSE
# file that should have been included as part of this package.
#
# AsynapRous release
#

"""
app.sampleapp
~~~~~~~~~~~~~~~~~
"""

import sys
import os
import json
from daemon import AsynapRous

app = AsynapRous()

@app.route('/login', methods=['POST'])
def login(headers="guest", body="anonymous", cookies=None): # <--- Đã thêm tham số cookies
    """
    Handle user login via POST request.
    """
    print("[SampleApp] Logging in {} to {}".format(headers, body))
    
    # -------------------------------------------------------------
    # GỢI Ý CHO ĐỒ ÁN (MULTI-SESSION & MULTI-BACKEND):
    # Thay vì chỉ trả về thông báo, bạn có thể cấp Session ID tại đây!
    # Từ file auth.py, bạn import hàm create_session:
    # 
    # session_id = create_session("admin") # Giả sử đăng nhập thành công
    # extra_cookies = [f"session={session_id}"]
    # data = {"message": "Login Success", "username": "admin"}
    # return (json.dumps(data).encode("utf-8"), extra_cookies) # Trả về tuple 2 phần tử
    # -------------------------------------------------------------
    
    data = {"message": "Welcome to the RESTful TCP WebApp"}
    json_str = json.dumps(data)
    return json_str.encode("utf-8")


@app.route("/echo", methods=["POST"])
def echo(headers="guest", body="anonymous", cookies=None):
    print("[SampleApp] received body {}".format(body))

    try:
        message = json.loads(body)
        data = {"received": message}
        json_str = json.dumps(data)
        return json_str.encode("utf-8")
    except json.JSONDecodeError:
        data = {"error": "Invalid JSON"}
        json_str = json.dumps(data)
        return json_str.encode("utf-8")


@app.route('/hello', methods=['PUT'])
async def hello(headers, body, cookies=None): 
    """
    Handle greeting via PUT request.
    """
    print("[SampleApp] ['PUT'] **ASYNC** Hello in {} to {}".format(headers, body))
    data = {"id": 1, "name": "Alice", "email": "alice@example.com"}

    json_str = json.dumps(data)
    return json_str.encode("utf-8")


def create_sampleapp(ip, port):
    # Prepare and launch the RESTful application
    app.prepare_address(ip, port)
    app.run()