import os
import time
import base64
import random
import json
import codecs
import signal
import threading
import requests
import hmac
import hashlib
import re
import sys
import struct
from datetime import datetime
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as _pad
from cryptography.hazmat.backends import default_backend
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEVELOPER = "xYAKOUB"
TELEGRAM = "@xvezqw"
INSTAGRAM = "0a.yakoub"

ACCOUNTS_FILE = "accounts.json"
API_HEX_KEY = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
API_SECRET_KEY = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
AES_KEY_G = bytes([89,103,38,116,99,37,68,69,117,104,54,37,90,99,94,56])
AES_IV_G  = bytes([54,111,121,90,68,114,50,50,69,51,121,99,104,106,77,37])
REGION_LANG = {"BD":"bn","IND":"hi","PK":"ur","SG":"en","ID":"id","ME":"ar","VN":"vi","TW":"zh","CIS":"ru","TH":"th","EU":"en","US":"en","SAC":"es","LK":"en","BR":"pt"}

EXIT = False
SUCCESS_COUNT = 0
LOCK = threading.Lock()

def pad(data, bs):
    p = _pad.PKCS7(bs * 8).padder()
    return p.update(data) + p.finalize()

class AES:
    MODE_CBC = 2
    block_size = 16
    @staticmethod
    def new(key, mode, iv):
        class C:
            def __init__(self, k, i):
                self.k, self.i = k, i
            def encrypt(self, data):
                c = Cipher(algorithms.AES(self.k), modes.CBC(self.i), backend=default_backend()).encryptor()
                return c.update(data) + c.finalize()
        return C(key, iv)

def encode_varint(n):
    if n < 0: return b""
    result = []
    while True:
        byte = n & 0x7F
        n >>= 7
        if n: byte |= 0x80
        result.append(byte)
        if not n: break
    return bytes(result)

def create_proto_field(field_num, value):
    if isinstance(value, int):
        return encode_varint((field_num << 3) | 0) + encode_varint(value)
    elif isinstance(value, (str, bytes)):
        encoded_val = value.encode() if isinstance(value, str) else value
        return encode_varint((field_num << 3) | 2) + encode_varint(len(encoded_val)) + encoded_val
    return b""

def build_proto(fields):
    return b"".join(create_proto_field(k, v) for k, v in fields.items())

def encrypt_api(plain_hex):
    cipher = AES.new(AES_KEY_G, AES.MODE_CBC, AES_IV_G)
    return cipher.encrypt(pad(bytes.fromhex(plain_hex), AES.block_size)).hex()

def generate_password():
    return os.urandom(10).hex()

def save_account_to_json(account_data):
    try:
        with LOCK:
            accounts = []
            if os.path.exists(ACCOUNTS_FILE):
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    try:
                        accounts = json.load(f)
                        if not isinstance(accounts, list): accounts = []
                    except Exception:
                        accounts = []
            simplified = {
                "uid": account_data["uid"],
                "password": account_data["password"],
                "account_id": account_data["account_id"],
                "name": account_data["name"],
                "region": account_data["region"],
                "Telegram": TELEGRAM,
                "Instagram": INSTAGRAM,
                "Developer": DEVELOPER,
                "date_created": account_data["date_created"],
            }
            accounts.append(simplified)
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(accounts, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def _decode_major_login_response(response_bytes):
    if not response_bytes: return None
    def read_varint(buf, off):
        value = 0; shift = 0; start = off
        while off < len(buf):
            b = buf[off]; off += 1
            value |= (b & 0x7f) << shift
            if b < 0x80: return value, off - start
            shift += 7
            if shift > 70: raise ValueError("varint too long")
        raise ValueError("truncated varint")
    def parse(buf):
        off = 0; out = {}
        while off < len(buf):
            tag, n = read_varint(buf, off); off += n
            field_no, wire = tag >> 3, tag & 7
            if wire == 0:
                value, n = read_varint(buf, off); off += n
            elif wire == 2:
                ln, n = read_varint(buf, off); off += n
                if off + ln > len(buf): raise ValueError("bad length")
                value = buf[off:off+ln]; off += ln
            elif wire == 5:
                if off + 4 > len(buf): raise ValueError("bad fixed32")
                value = struct.unpack_from("<I", buf, off)[0]; off += 4
            elif wire == 1:
                if off + 8 > len(buf): raise ValueError("bad fixed64")
                value = struct.unpack_from("<Q", buf, off)[0]; off += 8
            else: raise ValueError("unsupported wire type")
            out[field_no] = value
        return out
    candidates = [response_bytes]
    candidates.extend(response_bytes[o:] for o in range(1, min(80, len(response_bytes))))
    for candidate in candidates:
        try:
            d = parse(candidate)
            if isinstance(d.get(1), int) and d[1] > 100000:
                def as_text(v):
                    if isinstance(v, bytes):
                        try: return v.decode("utf-8")
                        except Exception: return v.decode("latin1", "ignore")
                    return str(v) if v is not None else ""
                return {
                    "account_uid": int(d.get(1, 0)),
                    "region": as_text(d.get(2, "")),
                    "token": as_text(d.get(8, "")),
                    "url": as_text(d.get(10, "")),
                    "timestamp": int(d.get(21, 0)),
                    "key": d.get(22, b"") if isinstance(d.get(22, b""), bytes) else bytes.fromhex(str(d.get(22, ""))),
                    "iv": d.get(23, b"") if isinstance(d.get(23, b""), bytes) else bytes.fromhex(str(d.get(23, ""))),
                }
        except Exception:
            continue
    return None

def major_login(access_token, open_id, lang):
    try:
        fields = {
            3: time.strftime("%Y-%m-%d %H:%M:%S"),4: "free fire",5: 1,7: "fake garena",
            8: "Android OS 9 / API-28 (PPR1.180720.122/6736742)",9: "Handheld",
            10: "WIFI",11: "WIFI",12: 1257,13: 480,14: "240",
            15: "x86-64 | 2000 | 6",16: 7965,17: "Adreno (TM) 540",18: "OpenGL ES 3.2",
            19: "Google|e6200d04-93a3-4514-9341-d379f92c92c2",20: "14.242.36.36",
            21: lang or "en",22: open_id,23: "4",24: "Handheld",25: "infinix x6891",
            29: access_token,30: 1,41: "WIFI",42: "WIFI",
            57: "7428b253defc164018c604a1ebbfebdf",60: 128886,61: 113471,62: 7998,
            64: 120040,65: 128886,66: 120040,67: 128886,73: 2,
            74: "/data/app/com.dts.freefireth/lib/arm64",76: 1,78: 3,79: 2,81: "64",
            83: "2019121229",86: "OpenGLES2",87: 4095,88: 4,90: "City",91: "ME",
            92: 20583,93: "android",
            94: "KqsHTxlzSl3i59tPt7bT3bNzIDdkBgGk3cO/WZnqY5h3i+mCiEozhU9+75L4xBzZExI/HsQIq8bS8vk7KzjerfDAftCvpq+MzU9ZBwlWJWqfcJOP",
            95: 111107,96: '{"cur_rate":null,"support_etc2":false}',97: 1,98: 1,
            99: "4",100: "4",104: 83371,105: 1,
            106: "https://dl.gmc.freefiremobile.com/live/ABHotUpdates/|https://core-gmc.freefiremobile.com/live/ABHotUpdates/|211c933168f55902c7dfbfd8c4e2957d",
            107: "c8e41b7a93f02d56e1a94c7b8203f5d1",
        }
        data = bytes.fromhex(encrypt_api(build_proto(fields).hex()))
        response = requests.post("https://loginbp.ppmainecoonghj.com/MajorLogin",
            headers={
                "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
                "Accept-Encoding": "identity","X-GA-SV": str(int(time.time())),
                "Authorization": "Bearer","X-GA": "v1 1","ReleaseVersion": "OB55",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Unity-Version": "2018.4.12f1","Host": "loginbp.ppmainecoonghj.com",
            }, data=data, verify=False, timeout=15)
        if response.status_code != 200: return None
        m = re.search(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", response.text)
        if not m: return None
        jwt_token = m.group(0)
        payload_part = jwt_token.split(".")[1]
        data_json = json.loads(base64.urlsafe_b64decode(payload_part + "=" * (4 - len(payload_part) % 4)))
        acc_id = data_json.get("account_id") or data_json.get("external_id")
        if not acc_id: return None
        return {"account_id": str(acc_id), "jwt_token": jwt_token}
    except Exception:
        return None

def login_generated_account(access_token, open_id, lang):
    try:
        login = major_login(access_token, open_id, lang)
        if not login: return None
        fields = {
            3: time.strftime("%Y-%m-%d %H:%M:%S"),4: "free fire",5: 1,7: "OGxMERO",
            8: "Android OS 9 / API-28 (PPR1.180720.122/6736742)",9: "Handheld",
            10: "WIFI",11: "WIFI",12: 1257,13: 480,14: "240",
            15: "x86-64 | 2000 | 6",16: 7965,17: "Adreno (TM) 540",18: "OpenGL ES 3.2",
            19: "Google|e6200d04-93a3-4514-9341-d379f92c92c2",20: "14.242.36.36",
            21: lang or "en",22: open_id,23: "4",24: "Handheld",25: "infinix x6891",
            29: access_token,30: 1,41: "WIFI",42: "WIFI",
            57: "7428b253defc164018c604a1ebbfebdf",60: 128886,61: 113471,62: 7998,
            64: 120040,65: 128886,66: 120040,67: 128886,73: 2,
            74: "/data/app/com.dts.freefireth/lib/arm64",76: 1,78: 3,79: 2,81: "64",
            83: "2019121229",86: "OpenGLES2",87: 4095,88: 4,90: "City",91: "ME",
            92: 20583,93: "android",
            94: "KqsHTxlzSl3i59tPt7bT3bNzIDdkBgGk3cO/WZnqY5h3i+mCiEozhU9+75L4xBzZExI/HsQIq8bS8vk7KzjerfDAftCvpq+MzU9ZBwlWJWqfcJOP",
            95: 111107,96: '{"cur_rate":null,"support_etc2":false}',97: 1,98: 1,
            99: "4",100: "4",104: 83371,105: 1,
            106: "https://dl.gmc.freefiremobile.com/live/ABHotUpdates/|https://core-gmc.freefiremobile.com/live/ABHotUpdates/|211c933168f55902c7dfbfd8c4e2957d",
            107: "c8e41b7a93f02d56e1a94c7b8203f5d1",
        }
        payload = bytes.fromhex(encrypt_api(build_proto(fields).hex()))
        headers = {
            "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
            "Accept-Encoding": "identity","X-GA-SV": str(int(time.time())),
            "Authorization": "Bearer","X-GA": "v1 1","ReleaseVersion": "OB55",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Unity-Version": "2018.4.12f1","Host": "loginbp.ppmainecoonghj.com",
        }
        r = requests.post("https://loginbp.ppmainecoonghj.com/MajorLogin", headers=headers, data=payload, verify=False, timeout=15)
        if r.status_code != 200: return None
        auth = _decode_major_login_response(r.content)
        if not auth or not auth["token"]: return None
        base_url = auth["url"] or "https://clientbp.ppmainecoonghj.com"
        if not base_url.startswith("http"): base_url = "https://" + base_url
        base_url = base_url.rstrip("/")
        login_data = None
        candidates = [base_url, "https://clientbp.ppmainecoonghj.com","https://clientbp.ggpolarbear.com","https://client.ind.freefiremobile.com","https://client.us.freefiremobile.com"]
        seen = set()
        for host in candidates:
            if host in seen: continue
            seen.add(host)
            try:
                rr = requests.post(host + "/GetLoginData", headers={**headers, "Authorization": f"Bearer {auth['token']}"}, data=payload, verify=False, timeout=15)
                if rr.status_code == 200 and rr.content:
                    login_data = rr.content; base_url = host; break
            except Exception: continue
        if not login_data: return None
        return {**auth, "url": base_url, "login_data": login_data, "jwt_token": login.get("jwt_token"), "account_id": login.get("account_id")}
    except Exception:
        return None

def create_account(region, prefix, thread_id):
    for attempt in range(5):
        try:
            session = requests.Session()
            password = generate_password()
            payload_register = json.dumps({"app_id":100067,"client_type":2,"password":password,"source":2}, separators=(",",":"))
            signature = hmac.new(API_SECRET_KEY.encode(), payload_register.encode(), hashlib.sha256).hexdigest()
            headers_reg = {
                "User-Agent": "GarenaMSDK/4.0.44(ASUS ;Android 13;en;%s;app 1.132.1 2019121229;)" % region,
                "Accept": "application/json","Authorization": "Signature %s" % signature,
                "Content-Type": "application/json; charset=utf-8","Host": "100067.connect.garena.com",
            }
            resp_reg = session.post("https://100067.connect.garena.com/api/v2/oauth/guest:register", headers=headers_reg, data=payload_register, timeout=12, verify=False)
            if resp_reg.status_code != 200:
                if resp_reg.status_code == 429: time.sleep(2 ** attempt)
                continue
            reg_json = resp_reg.json()
            if reg_json.get("code") != 0: continue
            uid = reg_json["data"]["uid"]
            payload_token = json.dumps({"client_id":100067,"client_secret":API_HEX_KEY,"client_type":2,"device_id":"02-%s" % hashlib.md5(str(uid).encode()).hexdigest()[:36],"password":password,"response_type":"token","uid":uid}, separators=(",",":"))
            headers_tok = {"User-Agent":"GarenaMSDK/4.0.44(ASUS ;Android 13;en;%s;app 1.132.1 2019121229;)" % region,"Accept":"application/json","Content-Type":"application/json; charset=utf-8","Host":"100067.connect.garena.com"}
            resp_tok = session.post("https://100067.connect.garena.com/api/v2/oauth/guest/token:grant", headers=headers_tok, data=payload_token, timeout=12, verify=False)
            if resp_tok.status_code != 200: continue
            tok_json = resp_tok.json()
            if tok_json.get("code") != 0: continue
            access_token = tok_json["data"]["access_token"]
            open_id = tok_json["data"]["open_id"]
            keystream = [0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30]
            field = codecs.decode("".join(chr(ord(open_id[i]) ^ keystream[i % len(keystream)]) for i in range(len(open_id))).encode("unicode_escape").decode("utf-8"), "unicode_escape").encode("latin1")
            name = "%s%d" % (prefix, random.randint(1000, 9999))
            lang = REGION_LANG.get(region.upper(), "en")
            proto_data = build_proto({
                1: name,2: access_token,3: open_id,5: 102000007,6: 4,7: 1,13: 1,14: field,15: lang,16: 1,17: 1,20: "1.132.6",21: 1,
                22: bytes.fromhex('474752450101010067020000a6a42db7bc5516876af3d1ba4adc337bac558af092eb3757d59d65c9323bba42c6593a48b74f33b2b5b3dc45cbd7ac02040db58f394045be4835213e12c35e5566445a5224f39d205fcf91c0e6bec797e7b3968ac00e90d7500b5865828a9d6f2091c3070f5319a130748e407ed57e6638974670ac045631b3d08c310cf1256cebcf1aed2d97d177534603d1c95d9c5d698340e797e72aa7ecc67a33122e48b0dfda050a1649586aca5e979be1fd9d99f48cd8cf59630e0ff60f67d4ed2ec4e5e7475970449a6c06329009ee0ce2567892587675781a31e4bb2774403b2f78e9811df2cb397fa602572266747704c6258077910902eb7420bcb4ab743d1610cddba9019e7867aaad3aa7ba9b04968064a409b66733f9f78c566a25ff478cba37a2ffe23203d4b05bceef826f174b0be7912d19432cc759325251fa094d70693fb672d6f9e799284081b3adb541dd8f27ef80dcf1e7f0ff30f2fd976659457ce41e175a2d6301b777981ccc16b9a8247abaab8de0867836c27de0146fe4d0e1fd39b86ba51f0b58601cfcbd7f6f3451fe4184b26ed44ac2f6f7bb4ce5d9a80f88c2cbfe7553e5ab97c8b028ae16b4f70f037753b8c229a6e5e9038fcbb9b4c2abb954894f8f2faf177bfdaab3b0ed537156633621d16b62d58ba4ebe518997c33e2304976ba6af9df7e7e34302c7910ae559c7e3d20a30d71c14f85c0e86f26291bbf18c2d9dfe9a908592eea4523e6c1e5d9bb5abfbebfccd5c4e136f9be777723e932b06c029df5125191000c90fde62a8e5f8fceb28648f0c69ec3037d09302b2ade908a20dbd42761ca449b2743fc362649e16235769d9fbd7f87cd64972b58d69c0441abb5d22ddc6ed059f7ac1bdbfaef8c60e64631809c5e08c7cb4074c8ce6170d94b411604986be4ae163a')
            })
            encrypted_payload = bytes.fromhex(encrypt_api(proto_data.hex()))
            headers_major = {"User-Agent":"UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)","Accept-Encoding":"identity","X-GA-SV":str(int(time.time())),"Authorization":"Bearer","X-GA":"v1 1","ReleaseVersion":"OB55","Content-Type":"application/x-www-form-urlencoded","X-Unity-Version":"2018.4.12f1","Host":"loginbp.ppmainecoonghj.com"}
            session.post("https://loginbp.ppmainecoonghj.com/MajorRegister", headers=headers_major, data=encrypted_payload, verify=False, timeout=12)
            login_res = login_generated_account(access_token, open_id, lang)
            if login_res:
                account_id = login_res.get("account_id") or str(login_res.get("account_uid") or "")
                if not account_id: continue
                account_data = {"uid": int(uid),"password": password,"account_id": account_id,"name": name,"region": region,"Telegram": TELEGRAM,"Instagram": INSTAGRAM,"Developer": DEVELOPER,"date_created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                return account_data
        except Exception:
            pass
        time.sleep(0.3)
    return None

def generate_account(name, region="ME", target=1, threads=2):
    global EXIT, SUCCESS_COUNT
    EXIT = False
    SUCCESS_COUNT = 0
    if not name:
        name = "bot"
    if region.upper() not in REGION_LANG:
        region = "ME"
    results = []
    def worker(tid):
        global SUCCESS_COUNT
        while not EXIT:
            with LOCK:
                if SUCCESS_COUNT >= target: break
            acc = create_account(region.upper(), name, tid)
            if acc:
                with LOCK:
                    if SUCCESS_COUNT >= target: break
                    SUCCESS_COUNT += 1
                    results.append(acc)
            else:
                time.sleep(0.3)
    ts = []
    for i in range(threads):
        t = threading.Thread(target=worker, args=(i+1,), daemon=True)
        t.start(); ts.append(t)
    while any(t.is_alive() for t in ts):
        time.sleep(0.3)
        with LOCK:
            if SUCCESS_COUNT >= target: break
    return results[0] if results else None