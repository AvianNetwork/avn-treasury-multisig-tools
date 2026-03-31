import os
import shutil
import time
from typing import Any, cast
import binascii

from cryptos.coins.avian import Avian
from cryptos.main import compress, decompress
from cryptos.py3specials import safe_hexlify
from cryptos.transaction import (
    apply_multisignatures,
    deserialize,
    deserialize_script,
    ecdsa_tx_sign,
    serialize,
    signature_form,
    verify_tx_input,
)

coin = Avian()


def _load_dotenv_if_present() -> None:
    """Load environment variables from a .env file next to this script (optional)."""

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.isfile(env_path):
        return

    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_path, override=False)
        return
    except Exception:
        # Fallback: minimal KEY=VALUE parser (no export, no quotes).
        pass

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # If .env exists but can't be read/parsed, keep going with OS env.
        return

# You can override these at runtime:
#   set AVN_REDEEM_SCRIPT=<hex redeemScript>
#   set AVN_PRIVKEYS=<wif1>,<wif2>,<wif3>[,<wif4>]
DEFAULT_REDEEM_SCRIPT = "532103e141ad26ed1d8032de313c387e431a1e0cb7cae9e731e7d5c2e31ee246f00d7b2103ccb9dc44ede2444e58bfe0b0017371f02972fedf3e6268b2ac11027dd84627e6210306dee7c0938fd26fc982ba91c7b72a3c4aa84033aee40535192baa2ea091e31521020f0cb6fc2a969b14cd225c22af152ace0dc6e1643e13f377e9c1340a7fc2825354ae"


def _redeem_pubkeys_and_m(redeem_script_hex: str):
    tokens = cast(list[Any], deserialize_script(redeem_script_hex))
    if not tokens or not isinstance(tokens[0], int):
        raise ValueError("Unexpected redeemScript format")
    m_required = tokens[0]
    pubs = [t.lower() for t in tokens if isinstance(t, str) and len(t) in (66, 130)]
    if not pubs or not (1 <= m_required <= len(pubs)):
        raise ValueError("Could not extract pubkeys/M from redeemScript")
    return pubs, m_required


def _map_privkeys_to_pubkeys(privkeys_wif: list[str], redeem_pubs: list[str]):
    redeem_set = {p.lower() for p in redeem_pubs}
    out: dict[str, str] = {}
    for wif in privkeys_wif:
        pub = coin.privtopub(wif)
        if isinstance(pub, bytes):
            pub = safe_hexlify(pub)
        pub = str(pub).lower()

        candidates: set[str] = {pub}
        try:
            comp = compress(pub)
            if isinstance(comp, str):
                candidates.add(comp.lower())
        except Exception:
            pass
        try:
            decomp = decompress(pub)
            if isinstance(decomp, str):
                candidates.add(decomp.lower())
        except Exception:
            pass

        for cand in candidates:
            if cand in redeem_set:
                out[cand] = wif
    return out


dirname = os.path.dirname(__file__)
generateDirectory = os.path.join(dirname, "generate")
signedDirectory = os.path.join(dirname, "signed")


def run() -> None:
    _load_dotenv_if_present()
    redeemScript = os.environ.get("AVN_REDEEM_SCRIPT", DEFAULT_REDEEM_SCRIPT)

    _privkeys_env = os.environ.get("AVN_PRIVKEYS", "").strip()
    privkeys = [k.strip() for k in _privkeys_env.split(",") if k.strip()]
    if not privkeys:
        raise SystemExit(
            "Missing private keys. Set AVN_PRIVKEYS to a comma-separated list of WIF keys (e.g. wif1,wif2,wif3)."
        )

    redeem_pubkeys, m_required = _redeem_pubkeys_and_m(redeemScript)
    privkey_by_pubkey = _map_privkeys_to_pubkeys(privkeys, redeem_pubkeys)

    if len(privkey_by_pubkey) == 0:
        raise SystemExit(
            "None of the provided WIF keys match the redeemScript pubkeys. "
            "Double-check AVN_PRIVKEYS and AVN_REDEEM_SCRIPT."
        )

    # Default behavior:
    # - If you provide >= M keys, require fully-signed txs (old behavior)
    # - If you provide < M keys, allow partial signing (multi-person sequential flow)
    _require_full_env = os.environ.get("AVN_SIGN_REQUIRE_FULL", "").strip().lower()
    if _require_full_env in {"1", "true", "yes", "y", "on"}:
        require_full = True
    elif _require_full_env in {"0", "false", "no", "n", "off"}:
        require_full = False
    else:
        require_full = len(privkey_by_pubkey) >= m_required

    os.makedirs(signedDirectory, exist_ok=True)
    os.makedirs(generateDirectory, exist_ok=True)

    for filename in os.listdir(signedDirectory):
        file_path = os.path.join(signedDirectory, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print('Failed to delete %s. Reason: %s' % (file_path, e))

    start_time = time.time()
    for filename in os.listdir(generateDirectory):
        f = os.path.join(generateDirectory, filename)
        if not os.path.isfile(f):
            continue
        with open(f, 'r') as file:
            tx_hex = file.read().replace('\n', '').strip()

        # Use the original unsigned tx bytes for sighash creation.
        # This avoids repeated json_is_base scans when serializing hex-string dicts.
        unsigned_tx_bytes = binascii.unhexlify(tx_hex)
        redeem_script_bytes = binascii.unhexlify(redeemScript)

        tx = cast(dict[str, Any], deserialize(tx_hex))
        sign_time = time.time()
        for i in range(0, len(tx['ins'])):
            current_tokens = cast(list[Any], deserialize_script(tx["ins"][i]["script"]))
            current_norm = [t.lower() if isinstance(t, str) else t for t in current_tokens]

            # Extract any existing signatures (if this input is already partially signed).
            existing_sigs: list[str] = []
            if current_norm and current_norm[-1] == 174:
                existing_sigs = []
            else:
                # Typical P2SH multisig scriptSig: OP_0 <sig...> <redeemScript>
                try:
                    redeem_index = current_norm.index(redeemScript.lower())
                    existing_sigs = [
                        s
                        for s in current_norm[1:redeem_index]
                        if isinstance(s, str) and s and s != redeemScript.lower()
                    ]
                except ValueError:
                    existing_sigs = []

            # Match any existing signatures to pubkeys so we can keep correct ordering.
            sig_by_pub: dict[str, str] = {}
            for sig in existing_sigs:
                for pub in redeem_pubkeys:
                    if pub in sig_by_pub:
                        continue
                    try:
                        if verify_tx_input(tx_hex, i, redeemScript, sig, pub):
                            sig_by_pub[pub] = sig
                            break
                    except Exception:
                        continue

            # Add missing signatures using the keys we have, in redeemScript pubkey order.
            modtx = None
            for pub in redeem_pubkeys:
                if len(sig_by_pub) >= m_required:
                    break
                if pub in sig_by_pub:
                    continue
                priv = privkey_by_pubkey.get(pub)
                if not priv:
                    continue
                # `coin.multisign()` recomputes `signature_form()` on every call.
                # For M-of-N multisig we often sign the same input multiple times;
                # compute the signature preimage once per input for a big speedup.
                if modtx is None:
                    modtx = signature_form(unsigned_tx_bytes, i, redeem_script_bytes, coin.hashcode)
                sig_by_pub[pub] = ecdsa_tx_sign(modtx, priv, coin.hashcode)

            ordered_sigs = [sig_by_pub[p] for p in redeem_pubkeys if p in sig_by_pub]
            if require_full and len(ordered_sigs) < m_required:
                raise RuntimeError(f"Input {i}: only have {len(ordered_sigs)} valid signatures, need {m_required}.")

            # Write whatever signatures we have (up to M). This supports sequential signing:
            # signer1 produces 1-of-3, signer2 produces 2-of-3, signer3 produces 3-of-3.
            apply_multisignatures(tx, i, redeemScript, ordered_sigs[:m_required])

        with open(os.path.join(signedDirectory, filename), "w") as out:
            out.write(serialize(tx))
        print('{0} took {1} seconds'.format(filename, (time.time() - sign_time)))

    seconds = (time.time() - start_time)
    print('Process completed in {0} seconds ({1} minutes)'.format(seconds, seconds / 60))


if __name__ == "__main__":
    run()
