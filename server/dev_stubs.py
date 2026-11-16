#!/usr/bin/env python3
"""LOCAL TESTS ONLY: stand-ins for the GmCat account service, GmCat Drop's $GMGM checker, the $handle service and a
pretend Cardano wallet, so the whole TinyADA flow (sign-in, Plus, Verified owner, payments) can be clicked through in a
browser without touching anything real. Never runs on the Linode.

  python3 dev_stubs.py 4291      then start server.py with TINY_CONNECT_FILE=<written file> (see README)

Pretend wallet: GET /wallet -> {address}; GET /sign?addr=<hex>&msg=<hex> -> CIP-30 style {signature, key} made by the
official Cardano libraries (test_sign_payment.mjs) with one throwaway key.
"""
import json
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4291
ADA = "addr1qypypzafqzfs0jhedp8nmfs4j4lt3xtv7lgftuwcpng0fszj68scklk79nr4rrjsnalus2qhx70rrlk3vhdezlyg0p3sluwxhm"
W = json.loads(subprocess.check_output(["node", str(HERE / "test_sign_payment.mjs"), "init"], text=True))
QUOTES = {}
SIGNER = r"""
import { createRequire } from 'node:module';
const load = createRequire(import.meta.url), Cardano = load('@emurgo/cardano-serialization-lib-nodejs'), MS = load('@emurgo/cardano-message-signing-nodejs');
const [msgHex, priv, addrHex] = process.argv.slice(2);
const privateKey = Cardano.PrivateKey.from_normal_bytes(Buffer.from(priv, 'hex')), publicKey = privateKey.to_public();
const pm = MS.HeaderMap.new(); pm.set_algorithm_id(MS.Label.from_algorithm_id(MS.AlgorithmId.EdDSA)); pm.set_header(MS.Label.new_text('address'), MS.CBORValue.new_bytes(Buffer.from(addrHex, 'hex')));
const um = MS.HeaderMap.new(); um.set_header(MS.Label.new_text('hashed'), MS.CBORValue.new_special(MS.CBORSpecial.new_bool(false)));
const builder = MS.COSESign1Builder.new(MS.Headers.new(MS.ProtectedHeaderMap.new(pm), um), Buffer.from(msgHex, 'hex'), false), signed = builder.build(privateKey.sign(builder.make_data_to_sign().to_bytes()).to_bytes());
const key = MS.COSEKey.new(MS.Label.from_key_type(MS.KeyType.OKP)); key.set_algorithm_id(MS.Label.from_algorithm_id(MS.AlgorithmId.EdDSA));
key.set_header(MS.Label.from_ec_key(MS.ECKey.CRV), MS.CBORValue.from_label(MS.Label.from_curve_type(MS.CurveType.Ed25519))); key.set_header(MS.Label.from_ec_key(MS.ECKey.X), MS.CBORValue.new_bytes(publicKey.as_bytes()));
console.log(JSON.stringify({ signature: Buffer.from(signed.to_bytes()).toString('hex'), key: Buffer.from(key.to_bytes()).toString('hex') }));
"""
(HERE / ".dev_signer.mjs").write_text(SIGNER)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, data, headers=None):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/connect":   # the account page: pretend the person signed in and approved
            self.send_response(302)
            self.send_header("Location", q["return"] + "?" + urllib.parse.urlencode({"state": q["state"], "code": "dev-code-0123456789abcdef"}))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if u.path == "/wallet":
            return self.reply(200, {"address": W["address"], "hex": W["hex"]})
        if u.path == "/sign":
            out = subprocess.check_output(["node", str(HERE / ".dev_signer.mjs"), q["msg"], W["private"], q["addr"] if len(q["addr"]) > 60 else W["hex"]], text=True)
            return self.reply(200, json.loads(out))
        if u.path.startswith("/handles/"):
            return self.reply(200, {"resolved_addresses": {"ada": ADA}}) if u.path == "/handles/sam" else self.reply(404, {})
        if u.path.startswith("/api/connect/accounts/"):
            return self.reply(200, {})
        if u.path.startswith("/api/partner/quotes/"):
            qid = u.path.rsplit("/", 1)[1]
            QUOTES[qid] = QUOTES.get(qid, 0) + 1
            return self.reply(200, {"id": qid, "status": "paid" if QUOTES[qid] >= 2 else "open", "tx": "devtx"})
        self.reply(404, {})

    def do_POST(self):
        d = self.body()
        if self.path == "/api/connect/exchange":
            return self.reply(200, {"account_ref": "devaccountGMCAT0000000000", "name": "Sam"})
        if self.path == "/api/connect/wallet/sign-in":
            return self.reply(200, {"account_ref": "devaccountWALLET000000000", "wallet": "stake1u9devwallet00000000000000000000000000000000000000"})
        if self.path == "/api/partner/quotes":
            qid = "dq%d" % int(time.time() * 1000)
            return self.reply(201, {"id": qid, "address": "addr1q9devpaymentaddress0000000000000000000000000000000000000000", "amount": 31383195,
                                    "usd": d.get("usd"), "expires_at": int(time.time()) + 1800, "gmgm_usd": 0.0000001})
        self.reply(404, {})


if __name__ == "__main__":
    print("dev stubs on 127.0.0.1:%d (wallet %s…)" % (PORT, W["address"][:20]), flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
