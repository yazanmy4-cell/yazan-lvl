import asyncio
import aiohttp
import ssl
import time
import requests
import urllib3
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

KEY = bytes([89,103,38,116,99,37,68,69,117,104,54,37,90,99,94,56])
IV  = bytes([54,111,121,90,68,114,50,50,69,51,121,99,104,106,77,37])

CLIENT_URL = "https://clientbp.ppmainecoonghj.com"
LOGIN_URL  = "https://loginbp.ppmainecoonghj.com"
OB_VERSION = "OB55"


def vr(n):
    r = []
    while True:
        b = n & 0x7F
        n >>= 7
        if n: b |= 0x80
        r.append(b)
        if not n: break
    return bytes(r)


def pb(fields):
    p = bytearray()
    for f, v in fields.items():
        if isinstance(v, bool):
            p.extend(vr((f << 3) | 0)); p.extend(vr(1 if v else 0))
        elif isinstance(v, int):
            p.extend(vr((f << 3) | 0)); p.extend(vr(v))
        elif isinstance(v, str):
            d = v.encode(); p.extend(vr((f << 3) | 2)); p.extend(vr(len(d))); p.extend(d)
        elif isinstance(v, (bytes, bytearray)):
            d = bytes(v); p.extend(vr((f << 3) | 2)); p.extend(vr(len(d))); p.extend(d)
    return bytes(p)


def read_varint(data, pos):
    result = 0; shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
    return result, pos


def parse_pb(data):
    fields = {}; pos = 0; n = len(data)
    while pos < n:
        try:
            key, pos = read_varint(data, pos)
        except:
            break
        fn = key >> 3; wt = key & 0x07
        try:
            if wt == 0:
                val, pos = read_varint(data, pos)
            elif wt == 2:
                ln, pos = read_varint(data, pos)
                val = data[pos:pos + ln]
                pos += ln
            elif wt == 5:
                val = data[pos:pos + 4]; pos += 4
            elif wt == 1:
                val = data[pos:pos + 8]; pos += 8
            else:
                break
        except:
            break
        fields.setdefault(fn, []).append(val)
    return fields


def make_ssl():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def build_major(open_id, access_token):
    fields = {
        3: time.strftime("%Y-%m-%d %H:%M:%S"), 4: "free fire", 5: 1, 7: "fake garena",
        8: "Android OS 9 / API-28 (PPR1.180720.122/6736742)", 9: "Handheld",
        10: "WIFI", 11: "WIFI", 12: 1257, 13: 480, 14: "240",
        15: "x86-64 | 2000 | 6", 16: 7965, 17: "Adreno (TM) 540", 18: "OpenGL ES 3.2",
        19: "Google|e6200d04-93a3-4514-9341-d379f92c92c2", 20: "14.242.36.36",
        21: "en", 22: open_id, 23: "4", 24: "Handheld", 25: "infinix x6891",
        29: access_token, 30: 1, 41: "WIFI", 42: "WIFI",
        57: "7428b253defc164018c604a1ebbfebdf", 60: 128886, 61: 113471, 62: 7998,
        64: 120040, 65: 128886, 66: 120040, 67: 128886, 73: 2,
        74: "/data/app/com.dts.freefireth/lib/arm64", 76: 1, 78: 3, 79: 2, 81: "64",
        83: "2019121229", 86: "OpenGLES2", 87: 4095, 88: 4, 90: "City", 91: "ME",
        92: 20583, 93: "android",
        94: "KqsHTxlzSl3i59tPt7bT3bNzIDdkBgGk3cO/WZnqY5h3i+mCiEozhU9+75L4xBzZExI/HsQIq8bS8vk7KzjerfDAftCvpq+MzU9ZBwlWJWqfcJOP",
        95: 111107, 96: '{"cur_rate":null,"support_etc2":false}', 97: 1, 98: 1,
        99: "4", 100: "4", 104: 83371, 105: 1,
        106: "https://dl.gmc.freefiremobile.com/live/ABHotUpdates/|https://core-gmc.freefiremobile.com/live/ABHotUpdates/|211c933168f55902c7dfbfd8c4e2957d",
        107: "c8e41b7a93f02d56e1a94c7b8203f5d1",
    }
    return AES.new(KEY, AES.MODE_CBC, IV).encrypt(pad(pb(fields), 16))


async def oauth(uid, password):
    url = "https://100067.connect.garena.com/api/v2/oauth/guest/token:grant"
    headers = {
        "User-Agent": "GarenaMSDK/4.0.44(iPhone11,8;iOS 17.0.2;ar;MR;app 2.126.18 2019121229;)",
        "Content-Type": "application/json; charset=utf-8"
    }
    body = {
        "client_id": 100067,
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_type": 2,
        "device_id": "",
        "password": password,
        "response_type": "token",
        "uid": int(uid)
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, headers=headers, json=body, ssl=make_ssl(),
                          timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                return None
            j = await r.json()
            return j.get("data", j)


async def major_login(payload):
    url = f"{LOGIN_URL}/MajorLogin"
    headers = {
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "X-GA-SV": str(int(time.time())),
        "Authorization": "Bearer",
        "X-GA": "v1 1",
        "ReleaseVersion": OB_VERSION,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1"
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, data=payload, headers=headers, ssl=make_ssl(),
                          timeout=aiohttp.ClientTimeout(total=15)) as r:
            raw = await r.read()
            return raw if r.status == 200 else None


async def get_login_data(payload, token):
    url = f"{CLIENT_URL}/GetLoginData"
    headers = {
        "Host": "clientbp.ppmainecoonghj.com",
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "X-GA-SV": str(int(time.time())),
        "Authorization": f"Bearer {token}",
        "X-GA": "v1 1",
        "ReleaseVersion": OB_VERSION,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1"
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, data=payload, headers=headers, ssl=make_ssl(),
                          timeout=aiohttp.ClientTimeout(total=15)) as r:
            raw = await r.read()
            return raw if r.status == 200 else None


def encrypt_api(pt):
    return AES.new(KEY, AES.MODE_CBC, IV).encrypt(
        pad(bytes.fromhex(pt), AES.block_size)
    ).hex()


def Encrypt_ID(x):
    x = int(x)
    dec = ['80','81','82','83','84','85','86','87','88','89','8a','8b','8c','8d','8e','8f','90','91','92','93','94','95','96','97','98','99','9a','9b','9c','9d','9e','9f','a0','a1','a2','a3','a4','a5','a6','a7','a8','a9','aa','ab','ac','ad','ae','af','b0','b1','b2','b3','b4','b5','b6','b7','b8','b9','ba','bb','bc','bd','be','bf','c0','c1','c2','c3','c4','c5','c6','c7','c8','c9','ca','cb','cc','cd','ce','cf','d0','d1','d2','d3','d4','d5','d6','d7','d8','d9','da','db','dc','dd','de','df','e0','e1','e2','e3','e4','e5','e6','e7','e8','e9','ea','eb','ec','ed','ee','ef','f0','f1','f2','f3','f4','f5','f6','f7','f8','f9','fa','fb','fc','fd','fe','ff']
    xxx = ['1','01','02','03','04','05','06','07','08','09','0a','0b','0c','0d','0e','0f','10','11','12','13','14','15','16','17','18','19','1a','1b','1c','1d','1e','1f','20','21','22','23','24','25','26','27','28','29','2a','2b','2c','2d','2e','2f','30','31','32','33','34','35','36','37','38','39','3a','3b','3c','3d','3e','3f','40','41','42','43','44','45','46','47','48','49','4a','4b','4c','4d','4e','4f','50','51','52','53','54','55','56','57','58','59','5a','5b','5c','5d','5e','5f','60','61','62','63','64','65','66','67','68','69','6a','6b','6c','6d','6e','6f','70','71','72','73','74','75','76','77','78','79','7a','7b','7c','7d','7e','7f']
    x = x / 128
    if x > 128:
        x = x / 128
        if x > 128:
            x = x / 128
            if x > 128:
                x = x / 128
                strx = int(x); y = (x - int(strx)) * 128; stry = str(int(y))
                z = (y - int(stry)) * 128; strz = str(int(z))
                n = (z - int(strz)) * 128; strn = str(int(n))
                m = (n - int(strn)) * 128
                return dec[int(m)] + dec[int(n)] + dec[int(z)] + dec[int(y)] + xxx[int(x)]
            else:
                strx = int(x); y = (x - int(strx)) * 128; stry = str(int(y))
                z = (y - int(stry)) * 128; strz = str(int(z))
                n = (z - int(strz)) * 128; strn = str(int(n))
                return dec[int(n)] + dec[int(z)] + dec[int(y)] + xxx[int(x)]
        else:
            strx = int(x); y = (x - int(strx)) * 128; stry = str(int(y))
            z = (y - int(stry)) * 128; strz = str(int(z))
            return dec[int(z)] + dec[int(y)] + xxx[int(x)]
    else:
        strx = int(x); y = (x - int(strx)) * 128; stry = str(int(y))
        return dec[int(y)] + xxx[int(x)]


def send_friend_request(target_id, token):
    d0 = "08c8b5cfea1810" + Encrypt_ID(target_id) + "18012008"
    try:
        r = requests.post(
            f"{CLIENT_URL}/RequestAddingFriend",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-GA": "v1 1",
                "ReleaseVersion": OB_VERSION,
                "Host": "clientbp.ppmainecoonghj.com",
                "Accept-Encoding": "gzip, deflate",
                "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
                "Connection": "keep-alive",
                "Authorization": f"Bearer {token}",
                "X-Unity-Version": "2018.4.12f1",
                "Accept": "*/*"
            },
            data=bytes.fromhex(encrypt_api(d0)),
            verify=False,
            timeout=10
        )
        return r.status_code == 200, r.status_code, r.text[:300]
    except Exception as e:
        return False, 0, str(e)


async def send_friend_request_async(uid, password, target_id):
    td = await oauth(uid, password)
    if not td:
        return {"ok": False, "stage": "oauth"}

    open_id = td.get("open_id")
    access_token = td.get("access_token")
    if not open_id or not access_token:
        return {"ok": False, "stage": "oauth_fields"}

    ml_payload = build_major(open_id, access_token)
    ml = await major_login(ml_payload)
    if not ml:
        return {"ok": False, "stage": "major_login"}

    body = ml[64:]
    f = parse_pb(body)
    if 1 not in f or 8 not in f:
        return {"ok": False, "stage": "parse"}

    account_id = int(f[1][0])
    jwt = f[8][0].decode()

    ld = await get_login_data(ml_payload, jwt)
    if not ld:
        return {"ok": False, "stage": "get_login_data"}

    ok, code, txt = send_friend_request(target_id, jwt)
    return {
        "ok": ok,
        "status": code,
        "response": txt,
        "account_id": account_id,
        "target": str(target_id)
    }


def send_friend_request_sync(uid, password, target_id):
    try:
        return asyncio.run(send_friend_request_async(uid, password, target_id))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(send_friend_request_async(uid, password, target_id))
        finally:
            loop.close()