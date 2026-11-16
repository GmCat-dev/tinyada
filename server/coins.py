"""Which coin an address belongs to, with its built-in typo check (checksum). Standard library only.

The browser runs the same rules (web/js/tiny-core.js); this copy makes sure the server never stores
an address that fails them. detect(text) -> list of coin ids the text is a valid address for (usually one; "3..." can be
Bitcoin or Litecoin). check(coin, text) -> (normalised address, None) or (None, plain-language reason).

Coins: ADA (Shelley addr1..., Byron Ae2/DdzFF...), BTC, ETH (any EVM chain), SOL, LTC, DOGE.
Cardano $handles are resolved separately (server.py) and stored as the handle, not as an address.
"""
import hashlib
import re
import zlib

COINS = {
    "ADA": {"name": "Cardano", "symbol": "ADA", "uri": "web+cardano"},
    "BTC": {"name": "Bitcoin", "symbol": "BTC", "uri": "bitcoin"},
    "ETH": {"name": "Ethereum", "symbol": "ETH", "uri": "ethereum"},
    "SOL": {"name": "Solana", "symbol": "SOL", "uri": "solana"},
    "LTC": {"name": "Litecoin", "symbol": "LTC", "uri": "litecoin"},
    "DOGE": {"name": "Dogecoin", "symbol": "DOGE", "uri": "dogecoin"},
}
ORDER = ["ADA", "BTC", "ETH", "SOL", "LTC", "DOGE"]
HANDLE_RE = re.compile(r"^\$[a-z0-9_.-]{1,15}$")

# ---------------------------------------------------------------- bech32 / bech32m (BIP-173 / BIP-350)
_CH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32, BECH32M = 1, 0x2BC830A3


def _polymod(v):
    g = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    c = 1
    for x in v:
        b = c >> 25
        c = (c & 0x1FFFFFF) << 5 ^ x
        for i in range(5):
            c ^= g[i] if (b >> i) & 1 else 0
    return c


def _expand(h):
    return [ord(x) >> 5 for x in h] + [0] + [ord(x) & 31 for x in h]


def _convert(data, f, t, pad):
    acc = bits = 0
    out = []
    m = (1 << t) - 1
    for v in data:
        acc = (acc << f) | v
        bits += f
        while bits >= t:
            bits -= t
            out.append((acc >> bits) & m)
    if pad:
        if bits:
            out.append((acc << (t - bits)) & m)
    elif bits >= f or ((acc << (t - bits)) & m):
        return None
    return out


def bech32_parse(s):
    """-> (hrp, 5-bit data without checksum, spec) or None. Mixed case is refused, as the standard says."""
    if s != s.lower() and s != s.upper():
        return None
    s = s.lower()
    pos = s.rfind("1")
    if pos < 1 or pos + 7 > len(s) or any(c not in _CH for c in s[pos + 1:]) or any(ord(c) < 33 or ord(c) > 126 for c in s):
        return None
    hrp, data = s[:pos], [_CH.index(c) for c in s[pos + 1:]]
    const = _polymod(_expand(hrp) + data)
    spec = BECH32 if const == BECH32 else BECH32M if const == BECH32M else None
    if spec is None:
        return None
    return hrp, data[:-6], spec


def bech32_bytes(s):
    p = bech32_parse(s)
    if not p or p[2] != BECH32:
        return None, None
    b = _convert(p[1], 5, 8, False)
    return p[0], (bytes(b) if b is not None else None)


def segwit(hrp_want, s):
    p = bech32_parse(s)
    if not p or p[0] != hrp_want or not p[1]:
        return False
    ver, prog = p[1][0], _convert(p[1][1:], 5, 8, False)
    if prog is None or ver > 16 or not (2 <= len(prog) <= 40):
        return False
    if ver == 0 and (p[2] != BECH32 or len(prog) not in (20, 32)):
        return False
    if ver != 0 and p[2] != BECH32M:
        return False
    return len(s) <= 90


# ---------------------------------------------------------------- base58
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s):
    n = 0
    for c in s:
        i = _B58.find(c)
        if i < 0:
            return None
        n = n * 58 + i
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def b58check(s):
    """-> (version byte, payload) or None."""
    b = b58decode(s)
    if not b or len(b) != 25:
        return None
    if hashlib.sha256(hashlib.sha256(b[:-4]).digest()).digest()[:4] != b[-4:]:
        return None
    return b[0], b[1:-4]


# ---------------------------------------------------------------- keccak-256 (for Ethereum's EIP-55 checksum)
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
       0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
       0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
       0x000000000000800A, 0x800000008000000A, 0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def keccak256(data):
    rate = 136
    msg = bytearray(data) + b"\x01"
    while len(msg) % rate:
        msg.append(0)
    msg[-1] |= 0x80
    st = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        for i in range(rate // 8):
            st[i % 5][i // 5] ^= int.from_bytes(msg[off + 8 * i:off + 8 * i + 8], "little")
        for rc in _RC:
            c = [st[x][0] ^ st[x][1] ^ st[x][2] ^ st[x][3] ^ st[x][4] for x in range(5)]
            d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
            st = [[st[x][y] ^ d[x] for y in range(5)] for x in range(5)]
            b = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    b[y][(2 * x + 3 * y) % 5] = _rol(st[x][y], _ROT[x][y])
            st = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
            st[0][0] ^= rc
    return b"".join(st[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


def eip55(hex40):
    h = keccak256(hex40.lower().encode()).hex()
    return "".join(c.upper() if c.isalpha() and int(h[i], 16) >= 8 else c.lower() for i, c in enumerate(hex40))


# ---------------------------------------------------------------- per coin
def cbor_head(b, i):
    """(major, value, next index) of a CBOR item header; small subset (enough for Byron addresses)."""
    ib = b[i]
    major, info = ib >> 5, ib & 31
    i += 1
    if info < 24:
        return major, info, i
    n = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
    if not n or i + n > len(b):
        raise ValueError
    return major, int.from_bytes(b[i:i + n], "big"), i + n


def byron_ok(s):
    """Byron addresses: base58 of CBOR [tag 24 (bytes), crc32 of those bytes]."""
    b = b58decode(s)
    if not b or len(b) < 30:
        return False
    try:
        major, n, i = cbor_head(b, 0)
        if major != 4 or n != 2:
            return False
        major, tag, i = cbor_head(b, i)
        if major != 6 or tag != 24:
            return False
        major, ln, i = cbor_head(b, i)
        if major != 2:
            return False
        payload, i = b[i:i + ln], i + ln
        major, crc, i = cbor_head(b, i)
        return major == 0 and i == len(b) and len(payload) == ln and zlib.crc32(payload) == crc
    except (ValueError, IndexError):
        return False


def check_ada(s):
    low = s.lower()
    if low.startswith("addr_test1") or low.startswith("stake_test1"):
        return None, "That's a Cardano test-network address. People can't send real ADA to it."
    if low.startswith("stake1"):
        return None, "That's a stake (rewards) address. Use a receiving address that starts with addr1."
    if low.startswith("addr1"):
        hrp, raw = bech32_bytes(s)
        if hrp != "addr" or raw is None:
            return None, "This Cardano address has a typo: its built-in check doesn't match."
        kind, net = raw[0] >> 4, raw[0] & 15
        if net != 1 or kind > 7:
            return None, "This isn't a main-network Cardano receiving address."
        want = 29 if kind in (6, 7) else (57 if kind <= 3 else None)
        if want and len(raw) != want or (kind in (4, 5) and len(raw) < 30):
            return None, "This Cardano address is the wrong length. Check you copied all of it."
        return low, None
    if s[:3] in ("Ae2", "Ddz") or s.startswith("DdzFF"):
        return (s, None) if byron_ok(s) else (None, "This older (Byron) Cardano address has a typo: its built-in check doesn't match.")
    return None, "Cardano addresses start with addr1."


def check_btc(s):
    if s.lower().startswith("bc1"):
        return (s.lower(), None) if segwit("bc", s) else (None, "This Bitcoin address has a typo: its built-in check doesn't match.")
    if s.lower().startswith(("tb1", "bcrt1")):
        return None, "That's a Bitcoin test-network address."
    r = b58check(s)
    if r and r[0] in (0x00, 0x05):
        return s, None
    if s[:1] in ("1", "3"):
        return None, "This Bitcoin address has a typo: its built-in check doesn't match."
    return None, "Bitcoin addresses start with 1, 3 or bc1."


def check_ltc(s):
    if s.lower().startswith("ltc1"):
        return (s.lower(), None) if segwit("ltc", s) else (None, "This Litecoin address has a typo: its built-in check doesn't match.")
    r = b58check(s)
    if r and r[0] in (0x30, 0x32, 0x05):
        return s, None
    if s[:1] in ("L", "M", "3"):
        return None, "This Litecoin address has a typo: its built-in check doesn't match."
    return None, "Litecoin addresses start with L, M, 3 or ltc1."


def check_doge(s):
    r = b58check(s)
    if r and r[0] in (0x1E, 0x16):
        return s, None
    if s[:1] in ("D", "A", "9"):
        return None, "This Dogecoin address has a typo: its built-in check doesn't match."
    return None, "Dogecoin addresses start with D, A or 9."


def check_eth(s):
    if not re.match(r"^0[xX][0-9a-fA-F]{40}$", s):
        return None, "Ethereum addresses are 0x followed by 40 letters and numbers (0-9, a-f)."
    body = s[2:]
    if body != body.lower() and body != body.upper() and eip55(body) != body:
        return None, "This Ethereum address has a typo: its capital letters don't match its built-in check."
    return "0x" + eip55(body), None


def check_sol(s):
    if not re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", s):
        return None, "Solana addresses are 32 to 44 letters and numbers."
    b = b58decode(s)
    if not b or len(b) != 32:
        return None, "This Solana address is the wrong length. Check you copied all of it."
    return s, None


_XRP58 = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"


def check_xrp(s):
    """Classic XRP Ledger address: r..., 25 bytes in the XRP base58 alphabet, version 0, double-SHA-256 checksum."""
    if not re.match(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$", s):
        return None, "XRP addresses start with r and are 25 to 35 characters."
    n = 0
    for c in s:
        i = _XRP58.find(c)
        if i < 0:
            return None, "That isn't an XRP address."
        n = n * 58 + i
    b = b"\x00" * (len(s) - len(s.lstrip("r"))) + (n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b"")
    if len(b) != 25 or b[0] != 0 or hashlib.sha256(hashlib.sha256(b[:-4]).digest()).digest()[:4] != b[-4:]:
        return None, "This XRP address has a typo: its built-in check doesn't match."
    return s, None


def check_trx(s):
    r = b58check(s)
    if r and r[0] == 0x41:
        return s, None
    return None, ("This TRON address has a typo: its built-in check doesn't match." if s[:1] == "T" else "TRON addresses start with T.")


CHECKS = {"ADA": check_ada, "BTC": check_btc, "ETH": check_eth, "SOL": check_sol, "LTC": check_ltc, "DOGE": check_doge}


# Where Privacy Plus payments arrive (one wallet per chain, set in the admin dashboard).
# An "evm" address is the same 0x address on every EVM chain listed.
RECEIVE_CHAINS = [
    ("cardano", "Cardano", "ADA", "ADA and $GMGM", check_ada),
    ("bitcoin", "Bitcoin", "BTC", "BTC", check_btc),
    ("evm", "Ethereum, Base, BNB Chain, Polygon", "ETH", "ETH, USDC, USDT, BNB, POL (one 0x address for all of them)", check_eth),
    ("solana", "Solana", "SOL", "SOL, USDC, USDT", check_sol),
    ("tron", "TRON", "TRX", "USDT (TRC-20), TRX", check_trx),
    ("litecoin", "Litecoin", "LTC", "LTC", check_ltc),
    ("dogecoin", "Dogecoin", "DOGE", "DOGE", check_doge),
    ("xrp", "XRP Ledger", "XRP", "XRP", check_xrp),
]


def clean(text):
    return re.sub(r"\s+", "", str(text or ""))[:200]


def check(coin, text):
    s = clean(text)
    if coin not in CHECKS:
        return None, "Pick a coin."
    if not s:
        return None, "Paste an address."
    return CHECKS[coin](s)


def detect(text):
    s = clean(text)
    if not s:
        return []
    return [c for c in ORDER if CHECKS[c](s)[0]]


def payment_bytes(addr):
    """A Shelley address's raw bytes (for wallet-signature checks), or None."""
    if not addr.startswith("addr1"):
        return None
    hrp, raw = bech32_bytes(addr)
    return raw if hrp == "addr" else None
