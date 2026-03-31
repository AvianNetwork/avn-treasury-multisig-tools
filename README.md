# AVN Treasury Multisig Tools (3-of-5)

This repository is a **small workflow toolset** used to create, sign, and broadcast **Avian (AVN)** transactions from the dev-fee / treasury wallet, which is typically a **P2SH multisig (e.g. 3-of-5)**.

The codebase contains a bundled/forked copy of the `cryptos` library (originally from the pybitcointools / Pycryptotools ecosystem), but the main entrypoints you’ll use are the scripts in the repository root.

## What it does

Typical flow:

1) Build one or more **unsigned** AVN transactions into `generate/`
2) Sign every tx in `generate/` with **multiple WIF keys** (any 3 matching keys for a 3-of-5) into `signed/`
3) Broadcast every tx in `signed/` and move them into `broadcast/`

## Scripts

- `fetch_avn_utxos.py` — pulls UTXOs from an Avian full node via `getaddressutxos` (supports `limit`/`offset`) and writes the JSON used by `create_avn_tx.py`
- `create_avn_tx.py` — creates unsigned tx files in `generate/` (driven by a UTXO JSON file)
- `sign_avn.py` — signs every tx in `generate/` into `signed/` using keys from `.env`
- `broadcast_avn.py` — broadcasts every tx in `signed/` and moves them into `broadcast/`
- `reset_folders.py` — wipes contents of `generate/`, `signed/`, and `broadcast/` (cross-platform)

## Safety notes

- **Never commit private keys.** Put secrets in `.env` (this repo ignores `.env`).
- Always inspect/verify a raw transaction before broadcasting.
- Multisig signature ordering matters: signatures must align with the pubkey order in the redeem script.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your `.env`:

1) Copy `.env.example` to `.env`
2) Edit values in `.env`

## Configuration (.env)

Minimum required for signing:

```env
AVN_PRIVKEYS=wif1,wif2,wif3
```

Optional / common settings:

- `AVN_REDEEM_SCRIPT` — redeemScript hex (if not embedded in the unsigned tx inputs)
- `AVN_DEST_ADDRESS` — destination address for `create_avn_tx.py`
- `AVN_UTXO_JSON` — UTXO json filename used by `create_avn_tx.py`
- `AVN_MAX_INPUTS` — max inputs per generated tx
- `AVN_TOTAL_PAYMENTS` — stop after this total is reached
- `AVN_FEE` — flat fee used by current generation logic

See `.env.example` for the full set.

## Typical workflow

0) Create/update the UTXO JSON (recommended)

Avian wallets with very large histories may require paging when calling `getaddressutxos`. Avian’s RPC supports:

`getaddressutxos {"addresses":["address",...],"chainInfo":bool,"assetName":"str","limit":n,"offset":n}`

This repo includes a helper to fetch UTXOs in pages and write the JSON file consumed by `create_avn_tx.py`:

```bash
python fetch_avn_utxos.py
```

By default it reads `AVN_SOURCE_ADDRESSES` and writes to `AVN_UTXO_JSON`. If not set, it writes to `inputs/utxos.json`.

`inputs/` is intended for large local-only files (like UTXO dumps) and is ignored by git.

RPC access requires an Avian node with `addressindex` enabled. Configure RPC settings and the source address in `.env` (see `.env.example`).

1) Generate unsigned tx files:

```bash
python create_avn_tx.py
```

2) Sign them (reads keys from `.env`):

```bash
python sign_avn.py
```

Sequential multi-signer flow (recommended when each signer holds only one key):

- Signer 1: put unsigned tx files in `generate/`, set `AVN_PRIVKEYS=<your_wif>`, run `python sign_avn.py`, then send the resulting `signed/` folder to signer 2.
- Signer 2: copy signer 1’s files into `generate/`, set `AVN_PRIVKEYS=<your_wif>`, run `python sign_avn.py`, then send `signed/` to signer 3.
- Signer 3: repeat once more; the resulting `signed/` txs should now have M signatures and be ready to broadcast.

By default `sign_avn.py` allows partial signing when you provide fewer than M keys. You can force full-sign enforcement with `AVN_SIGN_REQUIRE_FULL=true`.

3) Broadcast them:

```bash
python broadcast_avn.py
```

`broadcast_avn.py` will use Avian Core JSON-RPC (`sendrawtransaction`) if RPC is configured (see `.env.example`).
You can force behavior with `AVN_BROADCAST_METHOD=rpc` or `AVN_BROADCAST_METHOD=explorer`.

4) Reset folders for a clean rerun:

```bash
python reset_folders.py --yes
```

To also clear the local UTXO dump folder:

```bash
python reset_folders.py --yes --include-inputs
```

## Notes about the fork

This repo was originally based on a Pycryptotools-style codebase. The library code is still present under `cryptos/` (and a parallel `cryptosx/`), but the primary purpose here is the AVN treasury multisig transaction workflow described above.
