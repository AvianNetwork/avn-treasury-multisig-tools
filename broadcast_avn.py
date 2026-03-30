import json
import os
import time

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

dirname = os.path.dirname(__file__)
signedDirectory = os.path.join(dirname, "signed")
broadcastDirectory = os.path.join(dirname, "broadcast")

_load_dotenv_if_present()
isExist = os.path.exists(broadcastDirectory)
if not isExist:
   os.makedirs(broadcastDirectory)

start_time = time.time()
# iterate over files in that directory
for filename in os.listdir(signedDirectory):
    f = os.path.join(signedDirectory, filename)
    # checking if it is a file
    if not os.path.isfile(f):
        continue
    with open(f, 'r') as file:
        tx = file.read().replace('\n', '')

    resp = coin.pushtx(tx)
    broadcastResult = json.loads(resp.text)
    if broadcastResult['result'] == None:
        print("Error: ", broadcastResult['error']['message'])
    else:
        print("Transaction sent: ", broadcastResult['result'])
        os.replace(os.path.join(signedDirectory, filename), os.path.join(broadcastDirectory, filename))
