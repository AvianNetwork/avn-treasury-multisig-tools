import os
import json
import time
from typing import Any

from cryptos.coins.avian import Avian
from cryptos.transaction import serialize

coin = Avian()

DEFAULT_REDEEM_SCRIPT = '532103e141ad26ed1d8032de313c387e431a1e0cb7cae9e731e7d5c2e31ee246f00d7b2103ccb9dc44ede2444e58bfe0b0017371f02972fedf3e6268b2ac11027dd84627e6210306dee7c0938fd26fc982ba91c7b72a3c4aa84033aee40535192baa2ea091e31521020f0cb6fc2a969b14cd225c22af152ace0dc6e1643e13f377e9c1340a7fc2825354ae'
DEFAULT_DEST_ADDRESS = "RLrUNsda3Dqf6NBgChBUj26yg4jTkAYi5U"


def _load_dotenv_if_present() -> None:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_path, override=False)
    except Exception:
        return


_load_dotenv_if_present()

MAX_INPUTS = int(os.environ.get("AVN_MAX_INPUTS", "100"))
TOTAL_PAYMENTS = int(os.environ.get("AVN_TOTAL_PAYMENTS", "300000000000000"))
FEE = int(os.environ.get("AVN_FEE", "100000"))
REDEEM_SCRIPT = os.environ.get("AVN_REDEEM_SCRIPT", DEFAULT_REDEEM_SCRIPT)
DEST_ADDRESS = os.environ.get("AVN_DEST_ADDRESS", DEFAULT_DEST_ADDRESS)


def _resolve_utxo_json_path(path: str) -> str:
    if os.path.isfile(path):
        return path

    # If the user provided a bare filename (or default), prefer keeping UTXO dumps under inputs/.
    if os.path.dirname(path) == "":
        candidate = os.path.join(os.path.dirname(__file__), "inputs", path)
        if os.path.isfile(candidate):
            return candidate

    return path


UTXO_JSON = _resolve_utxo_json_path(os.environ.get("AVN_UTXO_JSON", os.path.join("inputs", "utxos.json")))

if not os.path.isfile(UTXO_JSON):
    raise FileNotFoundError(
        f"UTXO JSON not found: {UTXO_JSON}. "
        "Run fetch_avn_utxos.py first, or set AVN_UTXO_JSON to the correct path."
    )

with open(UTXO_JSON, 'r') as data_file:
    data: list[dict[str, Any]] = json.load(data_file)

start_time = time.time()

inputCounter=0
totalAmount=0
txCounter=1
txAmount=0
ins = []
dirname = os.path.dirname(__file__)
directory = os.path.join(dirname,"generate")
os.makedirs(directory, exist_ok=True)
for item in data:
    txAmount+=item['satoshis']
    inputCounter += 1
    output = item['txid']+':'+str(item['outputIndex'])
    ins.append(dict(output=output,value=item['satoshis'],script=REDEEM_SCRIPT))
    totalAmount += item['satoshis']-FEE
    if inputCounter >= MAX_INPUTS:
        outs = [{'value': txAmount-FEE, 'address': DEST_ADDRESS}]
        tx = coin.mktx(ins,outs)
        filename = "tx{0}.txt".format(str(txCounter).zfill(4))
        with open(os.path.join(directory, filename), "w") as f:
            f.write(serialize(tx))
        txCounter= txCounter+1
        ins=[]
        txAmount = 0
        inputCounter = 0
    if totalAmount >= TOTAL_PAYMENTS:
        outs = [{'value': txAmount-FEE, 'address': DEST_ADDRESS}]
        tx = coin.mktx(ins,outs)
        filename = "tx{0}.txt".format(str(txCounter).zfill(4))
        with open(os.path.join(directory, filename), "w") as f:
            f.write(serialize(tx))
        break
print("--- %s seconds ---" % (time.time() - start_time))
