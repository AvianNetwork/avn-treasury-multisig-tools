from cryptos.electrumx_client import rpc_send

host = "electrum-us.avn.network"
port = 50001
method = "blockchain.address.listunspent"
params = ["532103e141ad26ed1d8032de313c387e431a1e0cb7cae9e731e7d5c2e31ee246f00d7b2103ccb9dc44ede2444e58bfe0b0017371f02972fedf3e6268b2ac11027dd84627e6210306dee7c0938fd26fc982ba91c7b72a3c4aa84033aee40535192baa2ea091e31521020f0cb6fc2a969b14cd225c22af152ace0dc6e1643e13f377e9c1340a7fc2825354ae"]

rpc_send(host, port, method, params)
print('yes')
import time
time.sleep(2)
#print(result)