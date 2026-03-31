import json
import os
import time
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from cryptos.coins.avian import Avian

coin = Avian()


def _load_dotenv_if_present() -> None:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_path, override=False)
    except Exception:
        return


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _rpc_endpoint() -> tuple[str, HTTPBasicAuth | None]:
    url = os.environ.get("AVN_RPC_URL")
    if url:
        user = os.environ.get("AVN_RPC_USER")
        password = os.environ.get("AVN_RPC_PASSWORD")
        auth = HTTPBasicAuth(user, password) if user and password else None
        return url, auth

    host = os.environ.get("AVN_RPC_HOST")
    port = os.environ.get("AVN_RPC_PORT")
    if not host and not port:
        return "", None

    host = host or "127.0.0.1"
    port = int(port or "8766")
    user = os.environ.get("AVN_RPC_USER")
    password = os.environ.get("AVN_RPC_PASSWORD")
    auth = HTTPBasicAuth(user, password) if user and password else None
    return f"http://{host}:{port}/", auth


def _rpc_call(url: str, auth: HTTPBasicAuth | None, method: str, params: list[Any]) -> Any:
    payload = {"jsonrpc": "1.0", "id": "pybitcointools", "method": method, "params": params}
    resp = requests.post(url, json=payload, auth=auth, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"RPC error: {data['error']}")
    return data.get("result")


def _broadcast_via_rpc(tx_hex: str) -> str:
    url, auth = _rpc_endpoint()
    if not url:
        raise RuntimeError("RPC broadcast not configured (set AVN_RPC_URL or AVN_RPC_HOST/AVN_RPC_PORT)")
    # Optional: some nodes support allowhighfees or maxfeerate args, but keep minimal.
    result = _rpc_call(url, auth, "sendrawtransaction", [tx_hex])
    if result is None:
        raise RuntimeError("RPC sendrawtransaction returned null")
    return str(result)


def _looks_like_txid(value: str) -> bool:
    v = value.strip().lower()
    if len(v) != 64:
        return False
    return all(c in "0123456789abcdef" for c in v)


def _extract_txid_or_error(payload: Any) -> tuple[str | None, str | None]:
    """Normalize various pushtx response shapes into (txid, error_message)."""

    if payload is None:
        return None, "Empty response"

    # JSON-RPC style
    if isinstance(payload, dict) and ("result" in payload or "error" in payload):
        if payload.get("result") is not None:
            return str(payload.get("result")), None
        err = payload.get("error")
        if isinstance(err, dict) and "message" in err:
            return None, str(err.get("message"))
        return None, str(err) if err is not None else "Unknown JSON-RPC error"

    # Common explorer/API shapes
    if isinstance(payload, dict):
        if "txid" in payload and payload.get("txid"):
            return str(payload.get("txid")), None

        data = payload.get("data") if "data" in payload else None
        if isinstance(data, dict) and data.get("txid"):
            return str(data.get("txid")), None

        if payload.get("status") == "success" and isinstance(data, dict) and data.get("txid"):
            return str(data.get("txid")), None

        # Fall back to any obvious error fields
        for key in ("message", "error", "errors"):
            if key in payload and payload.get(key):
                return None, str(payload.get(key))

    # Plain string
    if isinstance(payload, str):
        if _looks_like_txid(payload):
            return payload.strip(), None
        return None, payload.strip() or "Unknown error"

    return None, f"Unexpected response type: {type(payload).__name__}"

dirname = os.path.dirname(__file__)
signedDirectory = os.path.join(dirname, "signed")
broadcastDirectory = os.path.join(dirname, "broadcast")

_load_dotenv_if_present()
isExist = os.path.exists(broadcastDirectory)
if not isExist:
   os.makedirs(broadcastDirectory)

start_time = time.time()
# Broadcast selection:
# - default: use RPC if configured; otherwise explorer
# - force explorer: AVN_BROADCAST_METHOD=explorer
# - force rpc: AVN_BROADCAST_METHOD=rpc
broadcast_method = (os.environ.get("AVN_BROADCAST_METHOD") or "").strip().lower()
rpc_url, _rpc_auth = _rpc_endpoint()
rpc_is_configured = bool(rpc_url)
use_rpc = (broadcast_method == "rpc") or (broadcast_method == "" and rpc_is_configured)
use_explorer = (broadcast_method == "explorer") or (broadcast_method == "" and not rpc_is_configured)

if not os.path.isdir(signedDirectory):
    print(f"Signed directory not found: {signedDirectory}")
    raise SystemExit(2)

# iterate over files in that directory
for filename in os.listdir(signedDirectory):
    f = os.path.join(signedDirectory, filename)
    # checking if it is a file
    if not os.path.isfile(f):
        continue
    with open(f, 'r') as file:
        tx = file.read().replace('\n', '')

    if not isinstance(tx, str) or not tx.strip() or not all(c in "0123456789abcdefABCDEF" for c in tx.strip()):
        print(f"Skipping {filename}: does not look like raw hex")
        continue
    tx = tx.strip()

    rpc_err: str | None = None
    explorer_err: str | None = None
    txid: str | None = None

    if use_rpc:
        try:
            txid = _broadcast_via_rpc(tx)
        except Exception as e:
            rpc_err = str(e)

    if txid is None and use_explorer:
        resp = coin.pushtx(tx)

        payload: Any
        status_code = None
        text = None
        try:
            status_code = getattr(resp, "status_code", None)
            text = getattr(resp, "text", None)
            if hasattr(resp, "json"):
                payload = resp.json()
            elif isinstance(resp, (dict, list, str)):
                payload = resp
            else:
                payload = text
        except Exception:
            payload = text

        txid, err = _extract_txid_or_error(payload)
        if err:
            if status_code is not None:
                explorer_err = f"HTTP {status_code}: {err}"
            else:
                explorer_err = err
            if _env_bool("AVN_BROADCAST_DEBUG", False) and text and isinstance(text, str) and text.strip():
                preview = text.strip().replace("\n", " ")
                if len(preview) > 300:
                    preview = preview[:300] + "..."
                print(f"Response: {preview}")

    if txid is None:
        if rpc_err and explorer_err:
            print(f"Error broadcasting {filename}: RPC failed ({rpc_err}); explorer failed ({explorer_err})")
        elif rpc_err:
            print(f"Error broadcasting {filename}: RPC failed ({rpc_err})")
        elif explorer_err:
            print(f"Error broadcasting {filename}: explorer failed ({explorer_err})")
        else:
            print(f"Error broadcasting {filename}: unknown failure")
        continue

    print("Transaction sent: ", txid)
    os.replace(os.path.join(signedDirectory, filename), os.path.join(broadcastDirectory, filename))
