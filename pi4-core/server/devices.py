"""Session-authenticated, explicitly configured MQTT device controls."""
import json
from aiohttp import web
import rewatch as rw
from .auth import SESSION_COOKIE


def add_device_routes(app, policy, telemetry, publish, *, simulation=False):
    def authorize(request):
        sid = request.cookies.get(SESSION_COOKIE)
        if not sid or not app["auth_db"].validate_session(sid):
            raise web.HTTPUnauthorized(text="sign in first")
        origin = request.headers.get("Origin")
        if origin and origin not in app["auth_origins"]:
            raise web.HTTPForbidden(text="Origin not allowed")

    async def inventory(request):
        authorize(request)
        return web.json_response({"devices": policy.inventory(telemetry()), "simulation": simulation})

    async def control(request):
        authorize(request)
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType(text="application/json required")
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            payload = policy.command(body.get("device"), body.get("action"), body.get("value"),
                                     confirmed=body.get("confirmed", False))
        except (ValueError, TypeError, UnicodeDecodeError) as error:
            raise web.HTTPBadRequest(text=str(error)) from None
        try:
            accepted = await publish(rw.topic("iot", payload["device"], "cmd"), payload)
        except Exception:
            accepted = False
        if not accepted:
            raise web.HTTPServiceUnavailable(text="command transport unavailable; nothing confirmed")
        app["auth_db"].audit("device_command_requested", detail=json.dumps(payload), ip=request.remote)
        return web.json_response({"ok": True, "status": "requested", "command": payload,
                                  "simulation": simulation}, status=202)

    app.router.add_get("/api/devices", inventory)
    app.router.add_post("/api/control", control)
