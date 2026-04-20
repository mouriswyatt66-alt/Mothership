"""
Mock Game Backend Server - Flask
For local development and testing of your own game.
"""

from flask import Flask, request, jsonify, make_response
import uuid
import time
import random
import string
import base64
import json
from datetime import datetime, timezone, timedelta
import hashlib

app = Flask(__name__)

# ─── Helpers ────────────────────────────────────────────────────────────────

def rand_uuid():
    return str(uuid.uuid4())

def rand_b64(n=32):
    raw = ''.join(random.choices(string.ascii_letters + string.digits + '-_', k=n))
    return raw

def fake_jwt(player_id: str, env_id: str, external_id: str, service: str = "STEAM"):
    """Generate a fake (non-cryptographic) JWT-shaped token for testing."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "ES256"}).encode()
    ).rstrip(b'=').decode()

    now = int(time.time())
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": player_id,
        "did": rand_uuid(),
        "env": env_id,
        "externalService": service,
        "externalServiceId": external_id,
        "tid": "f3e9fb19",
        "tags": None,
        "nbf": now,
        "exp": now + 3600,
        "iat": now,
    }).encode()).rstrip(b'=').decode()

    sig = base64.urlsafe_b64encode(
        hashlib.sha256(f"{header}.{payload}".encode()).digest()
    ).rstrip(b'=').decode()

    return f"{header}.{payload}.{sig}"

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def mock_headers(content_length: int = None):
    """Return realistic-looking security headers."""
    ray_id = ''.join(random.choices('0123456789abcdef', k=16)) + '-EWR'
    nel_url = "https://a.nel.example.com/report/v4?s=" + rand_b64(64)
    h = {
        "Content-Type": "application/json; charset=utf-8",
        "Connection": "keep-alive",
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
            "max_age": 604800
        }),
        "Report-To": json.dumps({
            "group": "cf-nel",
            "max_age": 604800,
            "endpoints": [{"url": nel_url}]
        }),
        "Server": "cloudflare",
        "CF-RAY": ray_id,
    }
    if content_length is not None:
        h["Content-Length"] = str(content_length)
    return h

def make_json_response(data, status=200):
    body = json.dumps(data)
    resp = make_response(body, status)
    for k, v in mock_headers(len(body)).items():
        resp.headers[k] = v
    return resp


# ─── Shared state (in-memory, resets on restart) ────────────────────────────

PLAYERS = {}       # player_id -> player dict
INVENTORIES = {}   # player_id -> {entitlement_id: quantity}
USER_DATA = {}     # player_id -> {key_name: value}
TITLE_DATA = {}    # global key -> value

ENV_ID   = "7f3a99dd-5598-4725-98cf-6538d28feb9f"
TITLE_ID = "f3e9fb19"

def get_or_create_player(external_id: str, service: str = "STEAM"):
    for pid, p in PLAYERS.items():
        if p["ExternalProviderId"] == external_id:
            return pid, p
    pid = rand_uuid()
    username = f"player_{random.randint(1000,9999)}"
    PLAYERS[pid] = {
        "ExternalProviderId": external_id,
        "ExternalProviderUsername": username,
        "IsPrimaryId": True,
        "PlayerId": pid,
        "Tags": None,
    }
    INVENTORIES[pid] = {
        "d4a0fad9-4602-435d-b379-cd5f69fb4321": 8,   # TechPoints
        "078b85fb-c0d9-44d5-a3ca-e325819b13cd": 8,   # StrangeWood
        "5150d276-db1a-4263-bff4-edbe7b55f841": 8,   # VibratingSpring
    }
    USER_DATA[pid] = {}
    return pid, PLAYERS[pid]


# ═══════════════════════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/v2/player/client/auth/begin/STEAM", methods=["GET"])
def auth_begin_steam():
    nonce = rand_b64(28)
    data = {"Nonce": nonce}
    return make_json_response(data, 200)

@app.route("/v2/player/client/auth/complete/STEAM", methods=["POST"])
def auth_complete_steam():
    external_id = str(random.randint(76561190000000000, 76561199999999999))
    pid, player = get_or_create_player(external_id)
    now_ms = int(time.time() * 1000)
    token = fake_jwt(pid, ENV_ID, external_id)
    data = {
        "ExternalProviderId": external_id,
        "ExternalProviderUsername": player["ExternalProviderUsername"],
        "IsPrimaryId": True,
        "PlayerId": pid,
        "Tags": None,
        "Token": token,
        "ExpirationTime": now_ms + 3600000,
    }
    return make_json_response(data, 201)


# ═══════════════════════════════════════════════════════════════════════════
#  TITLE DATA  (game config / schedule data)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/v1/title-data/client", methods=["GET"])
def get_title_data():
    data = {
        "Results": [
            {"key": "MOTD", "data": "WELCOME TO THE GAME!\n\nNEW CONTENT AVAILABLE NOW."},
            {"key": "CityEventCountdownTimer", "data": "5/1/2026 6:00:00 PM"},
            {"key": "ActivationReferenceDate", "data": "4/17/2026 5:00:00 PM"},
            {"key": "COC", "data": (
                "-NO RACISM, SEXISM, HOMOPHOBIA, OR BIGOTRY\n"
                "-NO CHEATS OR MODS\n"
                "-DO NOT HARASS OTHER PLAYERS\n"
                "-PLEASE BE NICE AND HAVE A GOOD TIME"
            )},
            {"key": "GorillanalyticsChance", "data": "4320"},
            {"key": "AutoMuteCheckedHours", "data": json.dumps({"hours": 169})},
            {"key": "EnableCustomAuthentication", "data": "true"},
        ]
    }
    return make_json_response(data, 200)


# ═══════════════════════════════════════════════════════════════════════════
#  INVENTORY
# ═══════════════════════════════════════════════════════════════════════════

ENTITLEMENT_META = {
    "d4a0fad9-4602-435d-b379-cd5f69fb4321": {"in_game_id": "SI_TECH_POINTS",      "name": "SI_TechPoints"},
    "078b85fb-c0d9-44d5-a3ca-e325819b13cd": {"in_game_id": "SI_STRANGE_WOOD",     "name": "SI_StrangeWood"},
    "5150d276-db1a-4263-bff4-edbe7b55f841": {"in_game_id": "SI_VIBRATING_SPRING", "name": "SI_VibratingSpring"},
    "8040ba58-afaa-44d3-bc0a-4d7864abf45d": {"in_game_id": "SI_BOUNCY_SAND",      "name": "SI_BouncySand"},
    "11844689-b2d0-4f02-923f-3bf49ba3aac6": {"in_game_id": "SI_FLOPPY_METAL",     "name": "SI_FloppyMetal"},
    "427839b6-58a4-4e8b-9cb4-3d48cb1fb513": {"in_game_id": "SI_WEIRD_GEAR",       "name": "SI_WeirdGear"},
    "88342aff-549c-42dc-9998-ccc8160ba254": {"in_game_id": "GR_RESEARCH_POINTS",  "name": "GR_ResearchPoints"},
}

@app.route("/v1/Inventory/client", methods=["GET"])
def get_inventory():
    # Try to get player from auth header
    pid = _player_from_request() or list(PLAYERS.keys())[0] if PLAYERS else rand_uuid()
    inv = INVENTORIES.get(pid, {})
    entitlements = []
    for eid, qty in inv.items():
        meta = ENTITLEMENT_META.get(eid, {"in_game_id": eid, "name": eid})
        entitlements.append({
            "entitlement_id": eid,
            "in_game_id": meta["in_game_id"],
            "name": meta["name"],
            "quantity": qty,
        })
    data = {
        "Results": {
            pid: {
                "platform": "STEAM",
                "isPrimary": True,
                "entitlements": entitlements,
            }
        }
    }
    return make_json_response(data, 200)


# ═══════════════════════════════════════════════════════════════════════════
#  PROGRESSION TREE
# ═══════════════════════════════════════════════════════════════════════════

def _make_node(name, cost_pts=8, unlocked=False, prereq_node=None):
    node = {
        "id": rand_uuid(),
        "name": name,
        "tree_id": rand_uuid(),
        "prerequisite_entitlements": None,
        "prerequisite_levels": None,
        "prerequisite_nodes": (
            {"type": "AND", "nodes": [{"node_id": prereq_node}]} if prereq_node else None
        ),
        "transaction": None,
        "cost": {
            "SI_TechPoints": {
                "Entitlement": {
                    "entitlement_id": "d4a0fad9-4602-435d-b379-cd5f69fb4321",
                    "name": "SI_TechPoints",
                    "in_game_id": "SI_TECH_POINTS",
                    "type": "CURRENCY",
                },
                "Delta": cost_pts,
            }
        },
        "unlocked": unlocked,
    }
    return node

@app.route("/v1/progression-tree/client", methods=["GET"])
def get_progression_tree():
    pid = _player_from_request() or (list(PLAYERS.keys())[0] if PLAYERS else rand_uuid())
    tree_id = rand_uuid()
    nodes = [
        _make_node("Initialize",    cost_pts=0,  unlocked=True),
        _make_node("Stilt_Unlock",  cost_pts=8),
        _make_node("Stilt_Short",   cost_pts=12),
        _make_node("Stilt_Long",    cost_pts=12),
        _make_node("Thruster_Unlock", cost_pts=8),
        _make_node("Thruster_Jet",  cost_pts=6),
        _make_node("Platform_Unlock", cost_pts=8),
        _make_node("Platform_Cooldown", cost_pts=6),
        _make_node("Tentacle_Unlock", cost_pts=16),
        _make_node("Tentacle_Efficiency", cost_pts=12),
        _make_node("Blaster_Standard_Unlock", cost_pts=16),
        _make_node("Blaster_Charge_Unlock", cost_pts=24),
        _make_node("AirControl_AirJuke_Unlock", cost_pts=16),
        _make_node("AirControl_AirGrab_Unlock", cost_pts=24),
    ]
    # Fix tree_ids to be consistent
    for n in nodes:
        n["tree_id"] = tree_id

    data = {
        "Results": [
            {
                "Tree": {
                    "id": tree_id,
                    "title_id": TITLE_ID,
                    "env_id": ENV_ID,
                    "name": "SI_Gadgets",
                    "track_id": None,
                    "created_at": "2025-10-02T15:53:15.278Z",
                },
                "NodeDefinitions": nodes,
                "PlayerId": pid,
                "InventoryRefreshRequired": False,
                "Track": None,
            }
        ]
    }
    return make_json_response(data, 200)


# ═══════════════════════════════════════════════════════════════════════════
#  USER DATA (per-player key-value store)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/v1/userdata/client", methods=["GET"])
def get_user_data():
    key_name = request.args.get("key_name", "")
    pid = _player_from_request() or (list(PLAYERS.keys())[0] if PLAYERS else rand_uuid())
    value = USER_DATA.get(pid, {}).get(key_name, "")
    data = {
        "id": rand_uuid(),
        "metadata_id": rand_uuid(),
        "key_name": key_name,
        "user_id": pid,
        "value": value,
        "generation": 0,
        "created_by": "",
        "last_written_by": "",
    }
    return make_json_response(data, 200)

@app.route("/v1/userdata/client", methods=["POST", "PUT"])
def set_user_data():
    pid = _player_from_request() or (list(PLAYERS.keys())[0] if PLAYERS else rand_uuid())
    body = request.get_json(silent=True) or {}
    key_name = body.get("key_name", request.args.get("key_name", ""))
    value = body.get("value", "")
    if pid not in USER_DATA:
        USER_DATA[pid] = {}
    USER_DATA[pid][key_name] = value
    data = {
        "id": rand_uuid(),
        "metadata_id": rand_uuid(),
        "key_name": key_name,
        "user_id": pid,
        "value": value,
        "generation": 1,
        "created_by": pid,
        "last_written_by": pid,
    }
    return make_json_response(data, 201)


# ═══════════════════════════════════════════════════════════════════════════
#  ANALYTICS / TELEMETRY  (accepts anything, returns event IDs)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/v1/client/analytics/event/batch", methods=["POST"])
def analytics_batch():
    body = request.get_json(silent=True) or {}
    events = body.get("Events", [])
    result = []
    for evt in events:
        evt_name = evt.get("EventName", "unknown_event")
        result.append({"EventId": f"{evt_name}-{now_iso()}"})
    if not result:
        result = [{"EventId": f"generic_event-{now_iso()}"}]
    return make_json_response(result, 201)

@app.route("/v1/client/analytics/ev", methods=["POST"])
def analytics_single():
    return make_json_response([{"EventId": f"event-{now_iso()}"}], 201)


# ═══════════════════════════════════════════════════════════════════════════
#  PLAYER / ACCOUNT
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/v1/userdata/client/me", methods=["GET"])
def get_me():
    pid = _player_from_request() or (list(PLAYERS.keys())[0] if PLAYERS else rand_uuid())
    player = PLAYERS.get(pid, {
        "ExternalProviderId": str(random.randint(76561190000000000, 76561199999999999)),
        "ExternalProviderUsername": f"player_{random.randint(1000,9999)}",
        "IsPrimaryId": True,
        "PlayerId": pid,
        "Tags": None,
    })
    return make_json_response(player, 200)

@app.route("/v1/title-data/client/<key>", methods=["GET"])
def get_title_data_key(key):
    val = TITLE_DATA.get(key, f"default_value_for_{key}")
    return make_json_response({"key": key, "data": val}, 200)


# ═══════════════════════════════════════════════════════════════════════════
#  CATCH-ALL  — accept everything, return 200 with a generic success body
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.route("/<path:path>",            methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def catch_all(path):
    body = request.get_json(silent=True) or {}
    data = {
        "success": True,
        "path": f"/{path}",
        "method": request.method,
        "requestId": rand_uuid(),
        "timestamp": now_iso(),
        "data": {},
    }
    # Echo back any body fields under "data" so clients feel heard
    if body:
        data["data"] = body
    return make_json_response(data, 200)


# ─── Utility ────────────────────────────────────────────────────────────────

def _player_from_request():
    """Try to extract a player ID from the Authorization header (fake JWT)."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        parts = token.split(".")
        if len(parts) == 3:
            try:
                payload_json = base64.urlsafe_b64decode(parts[1] + "==").decode()
                payload = json.loads(payload_json)
                pid = payload.get("sub")
                if pid and pid in PLAYERS:
                    return pid
            except Exception:
                pass
    return None


if __name__ == "__main__":
    print("=== Mock Game Backend ===")
    print("Running on http://0.0.0.0:5000")
    print("All routes return 200/201 with realistic headers.")
    app.run(host="0.0.0.0", port=5000, debug=True)
