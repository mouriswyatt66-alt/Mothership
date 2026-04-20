"""
Mock Game Backend Server - Flask
For local development and testing of your own game.

Project layout:
  app.py
  config.json
  requirements.txt

Run:
  pip install -r requirements.txt
  python app.py
"""

import json
import os
import uuid
import time
import random
import string
import base64
import hashlib
from datetime import datetime, timezone
from flask import Flask, request, make_response

# ─── Load config ─────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as _f:
    CONFIG = json.load(_f)

SERVER_CFG   = CONFIG["server"]
GAME_CFG     = CONFIG["game"]
TITLE_ID     = GAME_CFG["title_id"]
ENV_ID       = GAME_CFG["env_id"]
TOKEN_EXPIRY = GAME_CFG["token_expiry_seconds"]

app = Flask(__name__)

# ─── In-memory state ──────────────────────────────────────────────────────────

PLAYERS     = {}   # player_id -> player dict
INVENTORIES = {}   # player_id -> {entitlement_id: quantity}
USER_DATA   = {}   # player_id -> {key_name: value}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def rand_uuid():
    return str(uuid.uuid4())

def rand_b64(n=32):
    chars = string.ascii_letters + string.digits + "-_"
    return "".join(random.choices(chars, k=n))

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def fake_jwt(player_id: str, external_id: str, service: str = "STEAM") -> str:
    """Produce a fake JWT-shaped token (for local testing only)."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "ES256"}).encode()
    ).rstrip(b"=").decode()

    now = int(time.time())
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": player_id,
        "did": rand_uuid(),
        "env": ENV_ID,
        "externalService": service,
        "externalServiceId": external_id,
        "tid": TITLE_ID,
        "tags": None,
        "nbf": now,
        "exp": now + TOKEN_EXPIRY,
        "iat": now,
    }).encode()).rstrip(b"=").decode()

    sig = base64.urlsafe_b64encode(
        hashlib.sha256(f"{header}.{payload}".encode()).digest()
    ).rstrip(b"=").decode()

    return f"{header}.{payload}.{sig}"

def mock_headers(body: str) -> dict:
    """Return a dict of realistic-looking Cloudflare-style security headers."""
    ray_id  = "".join(random.choices("0123456789abcdef", k=16)) + "-EWR"
    nel_url = "https://a.nel.example.com/report/v4?s=" + rand_b64(64)
    return {
        "Content-Type": "application/json; charset=utf-8",
        "Connection": "keep-alive",
        "Content-Length": str(len(body.encode("utf-8"))),
        "content-security-policy": (
            "default-src 'self';base-uri 'self';font-src 'self' https: data:;"
            "form-action 'self';frame-ancestors 'self';img-src 'self' data:;"
            "object-src 'none';script-src 'self';script-src-attr 'none';"
            "style-src 'self' https: 'unsafe-inline';upgrade-insecure-requests"
        ),
        "cross-origin-opener-policy": "same-origin",
        "cross-origin-resource-policy": "same-origin",
        "origin-agent-cluster": "?1",
        "referrer-policy": "no-referrer",
        "strict-transport-security": "max-age=31536000; includeSubDomains",
        "x-content-type-options": "nosniff",
        "x-dns-prefetch-control": "off",
        "x-download-options": "noopen",
        "x-frame-options": "SAMEORIGIN",
        "x-permitted-cross-domain-policies": "none",
        "x-xss-protection": "0",
        "cf-cache-status": "DYNAMIC",
        "Nel": json.dumps({
            "report_to": "cf-nel",
            "success_fraction": 0.0,
            "max_age": 604800,
        }),
        "Report-To": json.dumps({
            "group": "cf-nel",
            "max_age": 604800,
            "endpoints": [{"url": nel_url}],
        }),
        "Server": "cloudflare",
        "CF-RAY": ray_id,
    }

def make_json_response(data, status: int = 200):
    body = json.dumps(data)
    resp = make_response(body, status)
    for k, v in mock_headers(body).items():
        resp.headers[k] = v
    return resp

# ─── Player helpers ───────────────────────────────────────────────────────────

def get_or_create_player(external_id: str, service: str = "STEAM"):
    for pid, p in PLAYERS.items():
        if p["ExternalProviderId"] == external_id:
            return pid, p

    pid      = rand_uuid()
    username = f"player_{random.randint(1000, 9999)}"
    PLAYERS[pid] = {
        "ExternalProviderId":       external_id,
        "ExternalProviderUsername": username,
        "IsPrimaryId":             True,
        "PlayerId":                pid,
        "Tags":                    None,
    }

    # Seed inventory from config
    INVENTORIES[pid] = {
        eid: meta["quantity"]
        for eid, meta in CONFIG["default_inventory"].items()
    }
    USER_DATA[pid] = {}
    return pid, PLAYERS[pid]

def player_from_request():
    """Extract player_id from Bearer token if present."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        parts = auth[7:].split(".")
        if len(parts) == 3:
            try:
                padded  = parts[1] + "=="
                payload = json.loads(base64.urlsafe_b64decode(padded).decode())
                pid     = payload.get("sub")
                if pid and pid in PLAYERS:
                    return pid
            except Exception:
                pass
    return None

def resolve_player():
    """Return a player_id, creating a dummy one if needed."""
    pid = player_from_request()
    if pid:
        return pid
    if PLAYERS:
        return next(iter(PLAYERS))
    # Create a throwaway player so routes don't crash
    ext = str(random.randint(76561190000000000, 76561199999999999))
    pid, _ = get_or_create_player(ext)
    return pid


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/v2/player/client/auth/begin/STEAM", methods=["GET"])
def auth_begin_steam():
    return make_json_response({"Nonce": rand_b64(28)}, 200)


@app.route("/v2/player/client/auth/complete/STEAM", methods=["POST"])
def auth_complete_steam():
    external_id = str(random.randint(76561190000000000, 76561199999999999))
    pid, player = get_or_create_player(external_id)
    token       = fake_jwt(pid, external_id)
    now_ms      = int(time.time() * 1000)
    return make_json_response({
        "ExternalProviderId":       external_id,
        "ExternalProviderUsername": player["ExternalProviderUsername"],
        "IsPrimaryId":             True,
        "PlayerId":                pid,
        "Tags":                    None,
        "Token":                   token,
        "ExpirationTime":          now_ms + TOKEN_EXPIRY * 1000,
    }, 201)


# ═══════════════════════════════════════════════════════════════════════════════
#  TITLE DATA
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/v1/title-data/client", methods=["GET"])
def get_title_data():
    results = [
        {"key": k, "data": v}
        for k, v in CONFIG["title_data"].items()
    ]
    return make_json_response({"Results": results}, 200)


@app.route("/v1/title-data/client/<key>", methods=["GET"])
def get_title_data_key(key):
    val = CONFIG["title_data"].get(key, f"default_value_for_{key}")
    return make_json_response({"key": key, "data": val}, 200)


# ═══════════════════════════════════════════════════════════════════════════════
#  INVENTORY
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/v1/Inventory/client", methods=["GET"])
def get_inventory():
    pid = resolve_player()
    inv = INVENTORIES.get(pid, {})

    entitlements = []
    for eid, qty in inv.items():
        meta = CONFIG["default_inventory"].get(eid, {
            "in_game_id": eid,
            "name": eid,
        })
        entitlements.append({
            "entitlement_id": eid,
            "in_game_id":     meta["in_game_id"],
            "name":           meta["name"],
            "quantity":       qty,
        })

    return make_json_response({
        "Results": {
            pid: {
                "platform":     "STEAM",
                "isPrimary":    True,
                "entitlements": entitlements,
            }
        }
    }, 200)


# ═══════════════════════════════════════════════════════════════════════════════
#  PROGRESSION TREE
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/v1/progression-tree/client", methods=["GET"])
def get_progression_tree():
    pid     = resolve_player()
    tree_id = rand_uuid()

    nodes = []
    prev_id = None
    for node_cfg in CONFIG["progression_nodes"]:
        nid = rand_uuid()
        node = {
            "id":   nid,
            "name": node_cfg["name"],
            "tree_id": tree_id,
            "prerequisite_entitlements": None,
            "prerequisite_levels":       None,
            "prerequisite_nodes": (
                {"type": "AND", "nodes": [{"node_id": prev_id}]}
                if prev_id and not node_cfg["unlocked"]
                else None
            ),
            "transaction": None,
            "cost": (
                None if node_cfg["cost"] == 0 else {
                    "SI_TechPoints": {
                        "Entitlement": {
                            "entitlement_id": "d4a0fad9-4602-435d-b379-cd5f69fb4321",
                            "name":           "SI_TechPoints",
                            "in_game_id":     "SI_TECH_POINTS",
                            "type":           "CURRENCY",
                        },
                        "Delta": node_cfg["cost"],
                    }
                }
            ),
            "unlocked": node_cfg["unlocked"],
        }
        nodes.append(node)
        prev_id = nid

    return make_json_response({
        "Results": [{
            "Tree": {
                "id":         tree_id,
                "title_id":   TITLE_ID,
                "env_id":     ENV_ID,
                "name":       "SI_Gadgets",
                "track_id":   None,
                "created_at": "2025-10-02T15:53:15.278Z",
            },
            "NodeDefinitions":        nodes,
            "PlayerId":               pid,
            "InventoryRefreshRequired": False,
            "Track":                  None,
        }]
    }, 200)


# ═══════════════════════════════════════════════════════════════════════════════
#  USER DATA  (per-player key-value store)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/v1/userdata/client", methods=["GET"])
def get_user_data():
    pid      = resolve_player()
    key_name = request.args.get("key_name", "")
    value    = USER_DATA.get(pid, {}).get(key_name, "")
    return make_json_response({
        "id":             rand_uuid(),
        "metadata_id":    rand_uuid(),
        "key_name":       key_name,
        "user_id":        pid,
        "value":          value,
        "generation":     0,
        "created_by":     "",
        "last_written_by": "",
    }, 200)


@app.route("/v1/userdata/client", methods=["POST", "PUT"])
def set_user_data():
    pid  = resolve_player()
    body = request.get_json(silent=True) or {}
    key_name = body.get("key_name", request.args.get("key_name", ""))
    value    = body.get("value", "")
    USER_DATA.setdefault(pid, {})[key_name] = value
    return make_json_response({
        "id":             rand_uuid(),
        "metadata_id":    rand_uuid(),
        "key_name":       key_name,
        "user_id":        pid,
        "value":          value,
        "generation":     1,
        "created_by":     pid,
        "last_written_by": pid,
    }, 201)


# ═══════════════════════════════════════════════════════════════════════════════
#  ANALYTICS / TELEMETRY
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/v1/client/analytics/event/batch", methods=["POST"])
def analytics_batch():
    body   = request.get_json(silent=True) or {}
    events = body.get("Events", [])
    result = [
        {"EventId": f"{e.get('EventName', 'event')}-{now_iso()}"}
        for e in events
    ] or [{"EventId": f"generic_event-{now_iso()}"}]
    return make_json_response(result, 201)


@app.route("/v1/client/analytics/ev", methods=["POST"])
def analytics_single():
    return make_json_response([{"EventId": f"event-{now_iso()}"}], 201)


# ═══════════════════════════════════════════════════════════════════════════════
#  PLAYER / ME
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/v1/userdata/client/me", methods=["GET"])
def get_me():
    pid    = resolve_player()
    player = PLAYERS.get(pid, {
        "ExternalProviderId":       rand_uuid(),
        "ExternalProviderUsername": f"player_{random.randint(1000, 9999)}",
        "IsPrimaryId":             True,
        "PlayerId":                pid,
        "Tags":                    None,
    })
    return make_json_response(player, 200)


# ═══════════════════════════════════════════════════════════════════════════════
#  CATCH-ALL  — accept every route, always return 200
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.route("/<path:path>",            methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def catch_all(path):
    body = request.get_json(silent=True) or {}
    return make_json_response({
        "success":   True,
        "path":      f"/{path}",
        "method":    request.method,
        "requestId": rand_uuid(),
        "timestamp": now_iso(),
        "data":      body,
    }, 200)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 42)
    print("  Mock Game Backend")
    print(f"  http://{SERVER_CFG['host']}:{SERVER_CFG['port']}")
    print("  All routes → 200/201 with CF-style headers")
    print("=" * 42)
    app.run(
        host  = SERVER_CFG["host"],
        port  = SERVER_CFG["port"],
        debug = SERVER_CFG["debug"],
    )
