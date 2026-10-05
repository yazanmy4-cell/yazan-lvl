import asyncio
import os
import json
import time
import secrets
import base64
from typing import Dict, Any, Optional, Callable
from aiohttp import web, ClientSession

ADMIN_USER = "admin"
ADMIN_PASS = "udp"

PROFILE_API = "https://ff.kibomodz.net/api/v1/profileboard/"
PROFILE_PASS = "K180726733"


class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.account_credentials: Dict[str, Dict] = {}
        self.refresh_callbacks: Dict[str, Callable] = {}
        self.logs: list = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.exp_targets_ref: Dict[str, int] = {}
        self.start_exp_ref: Dict[str, int] = {}
        self.exp_limit_reached_ref: set = set()
        self.account_start_ref: Dict[str, float] = {}
        self.session_matches_ref: Dict[str, int] = {}
        self.generated_accounts: list = []
        self.max_exp_target: int = 50000

    def bind_loop(self):
        self._loop = asyncio.get_running_loop()

    def register_account(self, uid, nickname, region, level, exp, likes=0):
        uid = str(uid)
        existing = self.accounts.get(uid, {})
        self.accounts[uid] = {
            "uid": uid,
            "nickname": nickname or existing.get("nickname") or f"Player_{uid}",
            "region": region or existing.get("region") or "ME",
            "level": int(level) if level else existing.get("level", 1),
            "exp": int(exp) if exp else existing.get("exp", 0),
            "likes": int(likes) if likes else existing.get("likes", 0),
            "status": existing.get("status", "CONNECTING"),
            "active_matches": existing.get("active_matches", 0),
            "matches_played": existing.get("matches_played", 0),
            "banner_png": existing.get("banner_png", ""),
            "banner_mime": existing.get("banner_mime", "image/webp"),
        }

    def update_status(self, uid, status, active_matches=None):
        uid = str(uid)
        if uid in self.accounts:
            self.accounts[uid]["status"] = status
            if active_matches is not None:
                self.accounts[uid]["active_matches"] = int(active_matches)

    def update_exp(self, uid, exp, level=None):
        uid = str(uid)
        if uid in self.accounts:
            self.accounts[uid]["exp"] = int(exp)
            if level is not None:
                self.accounts[uid]["level"] = int(level)

    def update_exp_target(self, uid, target):
        uid = str(uid)
        if uid in self.accounts:
            self.accounts[uid]["target"] = int(target)

    def increment_match(self, uid):
        uid = str(uid)
        if uid in self.accounts:
            self.accounts[uid]["active_matches"] = self.accounts[uid].get("active_matches", 0) + 1
            self.accounts[uid]["matches_played"] = self.accounts[uid].get("matches_played", 0) + 1

    def log(self, message, level="info"):
        self.logs.append({"t": time.time(), "level": level, "msg": str(message)})
        self.logs = self.logs[-500:]


bot_state = BotState()

_sessions: Dict[str, float] = {}
SESSION_TTL = 8 * 3600


def _new_session():
    tok = secrets.token_urlsafe(32)
    _sessions[tok] = time.time() + SESSION_TTL
    return tok


def _valid_session(tok):
    exp = _sessions.get(tok)
    if not exp or exp < time.time():
        _sessions.pop(tok, None)
        return False
    return True


def _authed(request):
    return _valid_session(request.cookies.get("yazan_sess", ""))


async def fetch_profile_banner(uid, name, level, banner_id="90100001", avatar_id="902000001"):
    url = PROFILE_API
    params = {
        "password": PROFILE_PASS,
        "name": str(name),
        "uid": str(uid),
        "level": str(level),
        "banner": str(banner_id),
        "avatar": str(avatar_id)
    }
    try:
        async with ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    content_type = resp.headers.get("Content-Type", "image/webp")
                    data = await resp.read()
                    b64 = base64.b64encode(data).decode("utf-8")
                    return {"banner_png": b64, "banner_mime": content_type}
    except Exception:
        pass
    return {"banner_png": "", "banner_mime": "image/webp"}


async def refresh_account_banner(uid):
    uid = str(uid)
    acc = bot_state.accounts.get(uid)
    if not acc:
        return
    result = await fetch_profile_banner(
        uid=uid,
        name=acc.get("nickname", f"Player_{uid}"),
        level=acc.get("level", 1)
    )
    if result["banner_png"]:
        acc["banner_png"] = result["banner_png"]
        acc["banner_mime"] = result["banner_mime"]


async def api_login(request: web.Request):
    data = await request.json()
    if data.get("username") == ADMIN_USER and data.get("password") == ADMIN_PASS:
        tok = _new_session()
        resp = web.json_response({"ok": True})
        resp.set_cookie("yazan_sess", tok, httponly=True, samesite="Lax", max_age=SESSION_TTL)
        return resp
    return web.json_response({"ok": False, "error": "Invalid credentials"}, status=401)


async def api_logout(request: web.Request):
    _sessions.pop(request.cookies.get("yazan_sess", ""), None)
    resp = web.json_response({"ok": True})
    resp.del_cookie("yazan_sess")
    return resp


async def api_me(request: web.Request):
    return web.json_response({"authed": _authed(request)})


async def api_start(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    data = await request.json()

    try:
        target = int(data.get("target", 0))
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid target"}, status=400)
    if target < 1:
        return web.json_response({"ok": False, "error": "Target must be positive"}, status=400)
    if target > 50000:
        return web.json_response({"ok": False, "error": "Maximum EXP target is 50,000."}, status=400)

    token = str(data.get("token", "")).strip()
    uid_in = str(data.get("uid", "")).strip()
    password_in = str(data.get("password", "")).strip()

    if token:
        if len(token) < 30:
            return web.json_response({"ok": False, "error": "Token too short"}, status=400)
        payload = {"type": "token", "token": token}
    elif uid_in and password_in:
        payload = {"type": "guest", "uid": uid_in, "password": password_in}
    else:
        return web.json_response({"ok": False, "error": "Provide token OR uid+password"}, status=400)

    login_handler = bot_state.refresh_callbacks.get("on_account_login_only")
    if not login_handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await login_handler(payload)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Login failed: {e}"}, status=500)

    uid = None
    deadline = time.time() + 90
    while time.time() < deadline:
        for k, creds in list(bot_state.account_credentials.items()):
            if token and creds.get("auth_type") == "token" and creds.get("auth_token") == token:
                uid = str(creds.get("account_id"))
                break
            if uid_in and creds.get("auth_type") == "guest" and str(creds.get("auth_uid")) == uid_in:
                uid = str(creds.get("account_id"))
                break
        if uid and uid in bot_state.accounts:
            break
        await asyncio.sleep(0.5)

    if not uid or uid not in bot_state.accounts:
        return web.json_response({"ok": False, "error": "Login timeout"}, status=502)

    try:
        setter = bot_state.refresh_callbacks.get("on_set_target")
        if setter:
            await setter(uid, target)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Target rejected: {e}"}, status=400)

    if uid in bot_state.accounts:
        bot_state.accounts[uid]["status"] = "READY"

    asyncio.create_task(refresh_account_banner(uid))

    return web.json_response({"ok": True, "uid": uid, "ready": True})


async def api_start_account(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    data = await request.json()
    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"ok": False, "error": "Missing uid"}, status=400)

    if "target" in data and data["target"] is not None:
        try:
            target = int(data["target"])
            if target < 1:
                return web.json_response({"ok": False, "error": "Target must be positive"}, status=400)
            if target > 50000:
                return web.json_response({"ok": False, "error": "Maximum EXP target is 50,000."}, status=400)
            setter = bot_state.refresh_callbacks.get("on_set_target")
            if setter:
                await setter(uid, target)
        except Exception as e:
            return web.json_response({"ok": False, "error": f"Target rejected: {e}"}, status=400)

    handler = bot_state.refresh_callbacks.get("on_start_account")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await handler(uid)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Start failed: {e}"}, status=500)

    asyncio.create_task(refresh_account_banner(uid))

    return web.json_response({"ok": True, "uid": uid})


async def api_stop_account(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    data = await request.json()
    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"ok": False, "error": "Missing uid"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_stop_account")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await handler(uid)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Stop failed: {e}"}, status=500)
    return web.json_response({"ok": True, "uid": uid})


async def api_halt_account(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    data = await request.json()
    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"ok": False, "error": "Missing uid"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_halt_account")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await handler(uid)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Halt failed: {e}"}, status=500)
    return web.json_response({"ok": True, "uid": uid})


async def api_delete_account(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    data = await request.json()
    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"ok": False, "error": "Missing uid"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_delete_account")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await handler(uid)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Delete failed: {e}"}, status=500)
    return web.json_response({"ok": True, "uid": uid})


async def api_add_friend(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    data = await request.json()
    uid = str(data.get("uid", "")).strip()
    target = str(data.get("target", "")).strip()
    if not uid or not target:
        return web.json_response({"ok": False, "error": "Missing uid or target"}, status=400)
    if not target.isdigit():
        return web.json_response({"ok": False, "error": "Target must be numeric"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_add_friend")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        result = await handler(uid, target)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Add friend failed: {e}"}, status=500)
    if not result or not result.get("ok"):
        return web.json_response({"ok": False, "error": (result.get("error", "Failed") if result else "Failed")}, status=502)
    return web.json_response({"ok": True, "uid": uid, "target": target})


async def api_gen_accounts(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    data = await request.json()
    name = str(data.get("name", "")).strip()
    region = str(data.get("region", "ME")).strip().upper()
    try:
        count = int(data.get("count", 1))
    except Exception:
        count = 1
    try:
        threads = int(data.get("threads", 2))
    except Exception:
        threads = 2
    count = max(1, min(50, count))
    threads = max(1, min(10, threads))

    handler = bot_state.refresh_callbacks.get("on_generate_accounts")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        result = await handler(name, region, count, threads)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Generate failed: {e}"}, status=500)
    if not result:
        return web.json_response({"ok": False, "error": "No accounts generated"}, status=502)
    return web.json_response({"ok": True, "generated": len(result), "accounts": result})


async def api_generated_list(request: web.Request):
    if not _authed(request):
        return web.json_response({"accounts": []}, status=401)
    accounts = getattr(bot_state, "generated_accounts", []) or []
    return web.json_response({"accounts": accounts})


async def api_gen_start(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    data = await request.json()
    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"ok": False, "error": "Missing uid"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_gen_start")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await handler(uid)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Start failed: {e}"}, status=500)
    return web.json_response({"ok": True})


async def api_gen_import(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    data = await request.json()
    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"ok": False, "error": "Missing uid"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_gen_import")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await handler(uid)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Import failed: {e}"}, status=500)
    return web.json_response({"ok": True})


async def api_state(request: web.Request):
    if not _authed(request):
        return web.json_response({"accounts": []}, status=401)

    EXP_TARGETS = getattr(bot_state, "exp_targets_ref", {}) or {}
    _start      = getattr(bot_state, "start_exp_ref", {}) or {}
    _reached    = getattr(bot_state, "exp_limit_reached_ref", set()) or set()
    _started    = getattr(bot_state, "account_start_ref", {}) or {}
    _matches    = getattr(bot_state, "session_matches_ref", {}) or {}

    now = time.time()
    out = []
    for uid, acc in bot_state.accounts.items():
        exp = int(acc.get("exp", 0))
        target = int(EXP_TARGETS.get(uid, acc.get("target", 0) or 0))
        start_exp = int(_start.get(uid, exp if target else 0))
        exp_gain = max(0, exp - start_exp) if target else 0
        remaining = max(0, target - exp_gain) if target else 0
        progress = (exp_gain / target * 100.0) if target else 0.0
        progress = max(0.0, min(100.0, progress))

        started_at = float(_started.get(uid, 0) or 0)
        elapsed_seconds = int(max(0, now - started_at)) if started_at else 0

        eta_seconds = 0
        rate_per_hour = 0
        if elapsed_seconds > 5 and exp_gain > 0 and remaining > 0:
            rate_per_sec = exp_gain / elapsed_seconds
            rate_per_hour = int(rate_per_sec * 3600)
            if rate_per_sec > 0:
                eta_seconds = int(remaining / rate_per_sec)

        session_matches = int(_matches.get(uid, 0))

        if uid in _reached:
            status = "COMPLETED"
            eta_seconds = 0
        else:
            status = acc.get("status", "OFFLINE") or "OFFLINE"
            if status == "IN_MATCH":
                status = "RUNNING"

        running = False
        for k, t in bot_state.account_workers.items():
            if (k == uid or (k in bot_state.account_credentials and
                              str(bot_state.account_credentials[k].get("account_id")) == uid)):
                if t and not t.done():
                    running = True
                break

        out.append({
            "uid": uid,
            "nickname": acc.get("nickname", f"Player_{uid}"),
            "level": int(acc.get("level", 1)),
            "exp": exp,
            "start_exp": start_exp,
            "exp_gain": exp_gain,
            "target": target,
            "remaining": remaining,
            "progress": round(progress, 2),
            "likes": int(acc.get("likes", 0)),
            "region": acc.get("region", "ME"),
            "status": status,
            "running": running,
            "active_matches": int(acc.get("active_matches", 0)),
            "matches_played": session_matches,
            "banner_png": acc.get("banner_png", ""),
            "banner_mime": acc.get("banner_mime", "image/webp"),
            "eta_seconds": eta_seconds,
            "elapsed_seconds": elapsed_seconds,
            "rate_per_hour": rate_per_hour,
        })

    return web.json_response({"accounts": out, "server_time": now})


async def index(request: web.Request):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "index.html")
    if not os.path.exists(path):
        return web.Response(text="index.html not found", status=404)
    return web.FileResponse(path)


async def start_web_dashboard(host="0.0.0.0", port=11006):
    app = web.Application()
    app.router.add_post("/api/login",          api_login)
    app.router.add_post("/api/logout",         api_logout)
    app.router.add_get ("/api/me",             api_me)
    app.router.add_post("/api/start",          api_start)
    app.router.add_post("/api/start-account",  api_start_account)
    app.router.add_post("/api/stop-account",   api_stop_account)
    app.router.add_post("/api/halt-account",   api_halt_account)
    app.router.add_post("/api/delete-account", api_delete_account)
    app.router.add_post("/api/add-friend",     api_add_friend)
    app.router.add_post("/api/gen-accounts",   api_gen_accounts)
    app.router.add_get ("/api/generated-list", api_generated_list)
    app.router.add_post("/api/gen-start",      api_gen_start)
    app.router.add_post("/api/gen-import",     api_gen_import)
    app.router.add_get ("/api/state",          api_state)
    app.router.add_get ("/",                   index)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"YAZAN LEVEL running on http://{host}:{port}")
    return runner