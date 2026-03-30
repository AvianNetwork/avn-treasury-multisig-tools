import argparse
import json
import os
import sys
import time
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.auth import HTTPBasicAuth


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


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    netloc = hostname
    if parts.port is not None:
        netloc = f"{hostname}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _rpc_endpoint() -> tuple[str, HTTPBasicAuth | None]:
    url = os.environ.get("AVN_RPC_URL")
    if url:
        user = os.environ.get("AVN_RPC_USER")
        password = os.environ.get("AVN_RPC_PASSWORD")
        auth = HTTPBasicAuth(user, password) if user and password else None
        return url, auth

    host = os.environ.get("AVN_RPC_HOST", "127.0.0.1")
    port = int(os.environ.get("AVN_RPC_PORT", "8766"))
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


def _iter_address_utxos(
    *,
    url: str,
    auth: HTTPBasicAuth | None,
    addresses: list[str],
    asset_name: str | None,
    chain_info: bool,
    limit: int,
    offset: int,
    sleep_seconds: float,
) -> Iterable[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be > 0 when using pagination")

    while True:
        params_obj: dict[str, Any] = {
            "addresses": addresses,
            "chainInfo": chain_info,
            "limit": limit,
            "offset": offset,
        }
        if asset_name is not None:
            params_obj["assetName"] = asset_name

        if _env_bool("AVN_RPC_DEBUG", False):
            print(f"Fetching UTXOs {_redact_url(url)} with params: {params_obj}", file=sys.stderr)
        result = _rpc_call(url, auth, "getaddressutxos", [params_obj])

        utxo_list: list[Any]
        if isinstance(result, list):
            utxo_list = result
        elif isinstance(result, dict) and isinstance(result.get("utxos"), list):
            utxo_list = result["utxos"]
        else:
            raise RuntimeError("Unexpected getaddressutxos result shape")

        if not utxo_list:
            return

        for utxo in utxo_list:
            if isinstance(utxo, dict):
                yield utxo

        if len(utxo_list) < limit:
            return

        offset += limit
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)


def main() -> int:
    _load_dotenv_if_present()

    parser = argparse.ArgumentParser(
        description=(
            "Fetch UTXOs via Avian JSON-RPC getaddressutxos using limit/offset pagination, "
            "and write them to a JSON file for create_avn_tx.py"
        )
    )
    parser.add_argument(
        "--out",
        default=os.environ.get("AVN_UTXO_JSON"),
        help=(
            "Output JSON path. Defaults to AVN_UTXO_JSON if set; otherwise inputs/<address>.json (single address) "
            "or inputs/utxos.json (multiple addresses)."
        ),
    )
    parser.add_argument(
        "--addresses",
        default=os.environ.get("AVN_SOURCE_ADDRESSES") or os.environ.get("AVN_SOURCE_ADDRESS", ""),
        help="Comma-separated base58 addresses",
    )
    parser.add_argument("--limit", type=int, default=int(os.environ.get("AVN_RPC_LIMIT", "5000")))
    parser.add_argument("--offset", type=int, default=int(os.environ.get("AVN_RPC_OFFSET", "0")))
    parser.add_argument("--asset", default=os.environ.get("AVN_RPC_ASSET_NAME"))
    parser.add_argument("--chaininfo", action="store_true", default=_env_bool("AVN_RPC_CHAININFO", False))
    parser.add_argument("--sleep", type=float, default=float(os.environ.get("AVN_RPC_SLEEP", "0")))
    parser.add_argument(
        "--max-satoshis",
        type=int,
        default=int(os.environ.get("AVN_TOTAL_PAYMENTS", "0")),
        help=(
            "Stop after fetched UTXOs reach this total satoshi amount (default: AVN_TOTAL_PAYMENTS; 0 = no limit)"
        ),
    )
    parser.add_argument(
        "--flush-every",
        type=int,
        default=int(os.environ.get("AVN_RPC_FLUSH_EVERY", "1000")),
        help="Flush output file every N UTXOs (default: 1000)",
    )
    args = parser.parse_args()

    addresses = _split_csv(args.addresses)
    if not addresses:
        print("Error: no addresses provided. Set AVN_SOURCE_ADDRESSES (or pass --addresses).", file=sys.stderr)
        return 2

    if not args.out:
        if len(addresses) == 1:
            args.out = os.path.join("inputs", f"{addresses[0]}.json")
        else:
            args.out = os.path.join("inputs", "utxos.json")

    url, auth = _rpc_endpoint()

    out_path = args.out
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    total = 0
    total_satoshis = 0
    max_satoshis = int(args.max_satoshis) if int(args.max_satoshis) > 0 else None
    started = time.time()
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("[")
            first = True

            for utxo in _iter_address_utxos(
                url=url,
                auth=auth,
                addresses=addresses,
                asset_name=args.asset,
                chain_info=bool(args.chaininfo),
                limit=int(args.limit),
                offset=int(args.offset),
                sleep_seconds=float(args.sleep),
            ):
                if not first:
                    f.write(",")
                else:
                    first = False

                json.dump(utxo, f, separators=(",", ":"))
                total += 1

                sat = utxo.get("satoshis")
                if sat is not None:
                    try:
                        total_satoshis += int(sat)
                    except Exception:
                        pass

                if args.flush_every > 0 and total % int(args.flush_every) == 0:
                    f.flush()
                    elapsed = time.time() - started
                    print(
                        f"Fetched {total} UTXOs / {total_satoshis} sats so far ({elapsed:.1f}s)",
                        file=sys.stderr,
                    )

                if max_satoshis is not None and total_satoshis >= max_satoshis:
                    break

            f.write("]")
            f.flush()
    except KeyboardInterrupt:
        # Try to close the JSON array so the output is usable even if stopped early.
        try:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write("]")
        except Exception:
            pass
        elapsed = time.time() - started
        print(f"Interrupted. Wrote partial JSON with {total} UTXOs -> {out_path} ({elapsed:.1f}s)", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"Error fetching UTXOs: {e}", file=sys.stderr)
        return 1

    elapsed = time.time() - started
    if max_satoshis is not None and total_satoshis >= max_satoshis:
        print(f"Reached {total_satoshis} sats (limit {max_satoshis}); stopped early", file=sys.stderr)
    print(f"Wrote {total} UTXOs ({total_satoshis} sats) -> {out_path} ({elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
