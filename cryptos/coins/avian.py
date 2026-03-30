from .base import BaseCoin
from ..transaction import SIGHASH_ALL, SIGHASH_FORKID
from ..main import b58check_to_bin
from ..py3specials import bin_to_b58check
from ..explorers import avn_explorer

class Avian(BaseCoin):
    coin_symbol = "avn"
    display_name = "Avian"
    segwit_supported = False
    magicbyte = 60
    script_magicbyte = 122
    wif_prefix = 0x80
    hd_path = 921
    explorer = avn_explorer
    hashcode = SIGHASH_ALL | SIGHASH_FORKID
