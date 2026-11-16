#!/usr/bin/env python3
"""TinyADA API tests: python3 test_server.py

Runs the service in this process on a free port with a throwaway data folder, next to a stand-in for the GmCat account
service, GmCat Drop's $GMGM checker and the $handle service (nothing real is contacted). Wallet signatures for the
"Verified owner" badge are made by test_sign_payment.mjs with the official Cardano libraries.
"""
import http.client
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


STUB_PORT, PORT = free_port(), free_port()
TMP = tempfile.mkdtemp(prefix="tiny-test-")
os.environ.update(TINY_DATA=TMP, TINY_PORT=str(PORT), TINY_HANDLE_API="http://127.0.0.1:%d" % STUB_PORT,
                  TINY_GMGM_API="http://127.0.0.1:%d" % STUB_PORT, TINY_GMGM_SECRET="gmgm-test-secret", TINY_COOKIE_SECURE="0",
                  TINY_ADMIN_KEY_SHA256=__import__("hashlib").sha256(b"admin-test-key").hexdigest(), TINY_LINK_BASE="https://tiny.gmcat.io/")
import server  # noqa: E402

ADA = "addr1qypypzafqzfs0jhedp8nmfs4j4lt3xtv7lgftuwcpng0fszj68scklk79nr4rrjsnalus2qhx70rrlk3vhdezlyg0p3sluwxhm"
BTC = "1BkoLLQfrXjynKynL9AdjdVFBvsaU9HKhm"
ETH = "0x4E879F40D85F260509dDAb111339b6E62DacfC12"
REF_A, REF_W, REF_GONE = "acctrefAAAAAAAAAAAAAAAAAAAA", "acctrefWWWWWWWWWWWWWWWWWWWW", "acctrefGONEGONEGONEGONEGONE"
STUB = {"quotes": {}, "status": {}, "calls": []}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, data):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        STUB["calls"].append(("GET", self.path))
        if self.path.startswith("/handles/"):
            return self.reply(200, {"resolved_addresses": {"ada": ADA}}) if self.path == "/handles/sam" else self.reply(404, {})
        if self.path.startswith("/api/connect/accounts/"):
            return self.reply(410 if REF_GONE in self.path else 200, {})
        if self.path.startswith("/api/partner/quotes/"):
            qid = self.path.rsplit("/", 1)[1]
            return self.reply(200, {"id": qid, "status": STUB["status"].get(qid, "open"), "tx": "tx123"})
        self.reply(404, {})

    def do_POST(self):
        d = self.body()
        STUB["calls"].append(("POST", self.path, d))
        if self.path == "/api/connect/exchange":
            return self.reply(200, {"account_ref": REF_A, "name": "Sam"}) if d.get("code") == "good-code-0123456789abcdef" else self.reply(400, {})
        if self.path == "/api/connect/wallet/sign-in":
            return self.reply(200, {"account_ref": REF_W, "wallet": "stake1u9fdrcvt0m0ze3633egf7l7g9qtn0833lmgktku30jy8sccw4qlvt"})
        if self.path == "/api/partner/quotes":
            if self.headers.get("Authorization") != "Bearer gmgm-test-secret":
                return self.reply(401, {"error": "unknown partner"})
            qid = "quote%08d" % len(STUB["quotes"])
            STUB["quotes"][qid] = d
            return self.reply(201, {"id": qid, "address": "addr1paytest", "amount": 123456, "usd": d["usd"], "expires_at": int(time.time()) + 1800, "gmgm_usd": 0.0001})
        self.reply(404, {})


def start():
    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", STUB_PORT), Stub).serve_forever, daemon=True).start()
    server.CONNECT = {"secret": "connect-test-secret", "api": "http://127.0.0.1:%d" % STUB_PORT, "authorize": "https://account.gmcat.io/connect",
                      "return": "https://tiny.gmcat.io/api/tiny/gmcat/return", "manage": "https://account.gmcat.io/profile/"}
    server.init()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def req(method, path, body=None, ip="10.0.0.1", headers=None, cookie=None, raw=False):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"X-Real-IP": ip, "Content-Type": "application/json"}
    if cookie:
        h["Cookie"] = cookie
    h.update(headers or {})
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = c.getresponse()
    data = r.read()
    out = (r.status, json.loads(data) if data and r.getheader("Content-Type", "").startswith("application/json") else data, r)
    c.close()
    return out


def admin(action, body):
    return req("POST", "/api/tiny/admin/" + action, body, headers={"X-Admin-Key": "admin-test-key"})


def _have_signer():
    """The wallet-signature tests need node + the EMURGO Cardano libraries (npm i @emurgo/cardano-serialization-lib-nodejs
    @emurgo/cardano-message-signing-nodejs). Without them those tests are skipped, not failed."""
    try:
        subprocess.check_output(["node", str(HERE / "test_sign_payment.mjs"), "probe"], stderr=subprocess.DEVNULL, timeout=60)
        return True
    except Exception:
        return False


HAVE_SIGNER = _have_signer()


def sign(message):
    return json.loads(subprocess.check_output(["node", str(HERE / "test_sign_payment.mjs"), message], text=True))


def wallet_session(ip="10.9.0.1"):
    st, ch, _ = req("GET", "/api/tiny/wallet/challenge", ip=ip)
    assert st == 200, ch
    st, d, r = req("POST", "/api/tiny/wallet/verify", {"nonce": ch["nonce"], "address": "e1..", "signature": "aa", "key": "bb"}, ip=ip)
    assert st == 201, d
    return r.getheader("Set-Cookie").split(";")[0]


class T(unittest.TestCase):
    def test_01_config_starts_with_plus_off(self):
        st, d, _ = req("GET", "/api/tiny/config")
        self.assertEqual(st, 200)
        self.assertEqual(d["premium"], "off")
        self.assertNotIn("prices", d)
        self.assertEqual([c["id"] for c in d["coins"]], ["ADA", "BTC", "ETH", "SOL", "LTC", "DOGE"])

    def test_02_free_link_round_trip(self):
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "ADA", "address": ADA, "keep": "7d", "amount": "5", "memo": "Coffee for Sam"}, ip="10.1.0.1")
        self.assertEqual(st, 201, d)
        self.assertRegex(d["code"], r"^[23456789abcdefghjkmnpqrstuvwxyz]{6}$")
        self.assertTrue(d["link"].startswith("https://tiny.gmcat.io/"))
        self.assertTrue(d["delete_token"])
        st, v, _ = req("GET", "/api/tiny/l/" + d["code"])
        self.assertEqual(st, 200)
        self.assertEqual(v["items"][0]["address"], ADA)
        self.assertEqual(v["items"][0]["amount"], "5")
        self.assertEqual(v["items"][0]["uri"], "web+cardano")
        self.assertFalse(v["plus"])
        self.assertNotIn("visits", v)   # counts are only for owners
        # same address + amount + note -> the same link, no new delete token, kept at least as long as asked
        st, d2, _ = req("POST", "/api/tiny/links", {"coin": "ADA", "address": ADA, "keep": "inuse", "amount": "5", "memo": "Coffee for Sam"}, ip="10.1.0.2")
        self.assertEqual(st, 200)
        self.assertEqual(d2["code"], d["code"])
        self.assertTrue(d2["existing"])
        self.assertNotIn("delete_token", d2)
        self.assertEqual(d2["mode"], "inuse")
        st, d3, _ = req("POST", "/api/tiny/links", {"coin": "ADA", "address": ADA, "keep": "1d", "amount": "5", "memo": "Coffee for Sam"}, ip="10.1.0.2")
        self.assertEqual(d3["mode"], "inuse")   # never shortened
        # a different amount is a different link
        st, d4, _ = req("POST", "/api/tiny/links", {"coin": "ADA", "address": ADA, "keep": "1d", "amount": "6"}, ip="10.1.0.2")
        self.assertEqual(st, 201)
        self.assertNotEqual(d4["code"], d["code"])
        # delete needs the right token
        self.assertEqual(req("DELETE", "/api/tiny/l/" + d4["code"], headers={"X-Delete-Token": "nope"})[0], 403)
        self.assertEqual(req("DELETE", "/api/tiny/l/" + d4["code"], headers={"X-Delete-Token": d4["delete_token"]})[0], 200)
        self.assertEqual(req("GET", "/api/tiny/l/" + d4["code"])[0], 404)

    def test_03_bad_addresses_are_refused(self):
        cases = [("BTC", BTC[:-1] + "n", "typo"), ("ETH", ETH[:-1] + "3", "capital"), ("ADA", "addr_test1qz" + "q" * 50, "test-network"),
                 ("ADA", "stake1u9fdrcvt0m0ze3633egf7l7g9qtn0833lmgktku30jy8sccw4qlvt", "stake"), ("SOL", "abc", "32 to 44"),
                 ("XRP", "rXXXX", "Pick a coin")]
        for coin, addr, word in cases:
            st, d, _ = req("POST", "/api/tiny/links", {"coin": coin, "address": addr, "keep": "1d"}, ip="10.2.0.1")
            self.assertEqual(st, 400, (coin, d))
            self.assertIn(word, d["error"])
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "BTC", "address": BTC, "keep": "forever"}, ip="10.2.0.1")
        self.assertEqual(st, 400)   # free links can't be permanent
        for amt in ("-1", "abc", "0", "1.123456789"):
            st, d, _ = req("POST", "/api/tiny/links", {"coin": "BTC", "address": BTC, "keep": "1d", "amount": amt}, ip="10.2.0.1")
            self.assertEqual(st, 400, amt)

    def test_04_handles(self):
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "ADA", "handle": "$sam", "keep": "30d"}, ip="10.3.0.1")
        self.assertEqual(st, 201, d)
        st, v, _ = req("GET", "/api/tiny/l/" + d["code"])
        self.assertEqual(v["items"][0]["handle"], "$sam")
        self.assertEqual(v["items"][0]["address"], ADA)
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "ADA", "handle": "$nobodyhere", "keep": "30d"}, ip="10.3.0.1")
        self.assertEqual(st, 400)
        self.assertIn("couldn't find", d["error"])
        self.assertEqual(req("GET", "/api/tiny/handle/sam")[1]["address"], ADA)

    def test_05_rate_limit(self):
        for i in range(20):
            st, d, _ = req("POST", "/api/tiny/links", {"coin": "BTC", "address": BTC, "keep": "1d", "amount": str(i + 1)}, ip="10.4.0.1")
            self.assertIn(st, (200, 201))
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "BTC", "address": BTC, "keep": "1d", "amount": "99"}, ip="10.4.0.1")
        self.assertEqual(st, 429)
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "BTC", "address": BTC, "keep": "1d", "amount": "99"}, ip="10.4.0.2")
        self.assertEqual(st, 201)

    def test_06_reports_hide_and_admin_restores(self):
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "ETH", "address": ETH, "keep": "1d"}, ip="10.5.0.1")
        code = d["code"]
        for i in range(3):
            self.assertEqual(req("POST", "/api/tiny/l/%s/report" % code, {"reason": "scam", "details": "<b>fake</b>"}, ip="10.5.1.%d" % i)[0], 200)
        self.assertEqual(req("GET", "/api/tiny/l/" + code)[0], 451)
        st, o, _ = req("GET", "/api/tiny/admin/overview", headers={"X-Admin-Key": "admin-test-key"})
        self.assertTrue(any(r["code"] == code and r["reporters"] == 3 for r in o["reports"]))
        self.assertEqual(req("GET", "/api/tiny/admin/overview", headers={"X-Admin-Key": "wrong"})[0], 403)
        self.assertEqual(admin("restore", {"code": code})[0], 200)
        self.assertEqual(req("GET", "/api/tiny/l/" + code)[0], 200)
        # a hidden link is not handed out again by "same address, same link"
        admin("hold", {"code": code})
        self.assertEqual(req("POST", "/api/tiny/links", {"coin": "ETH", "address": ETH, "keep": "1d"}, ip="10.5.0.1")[0], 451)

    def test_07_expiry_and_keep_while_in_use(self):
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "BTC", "address": BTC, "keep": "inuse", "memo": "inuse test"}, ip="10.6.0.1")
        code = d["code"]
        with server.db() as con:   # pretend nobody opened it for 5 months
            con.execute("UPDATE links SET last_visit = ?, expires = ? WHERE code = ?", (server.now() - 150 * 86400, server.now() + 30 * 86400, code))
        req("GET", "/api/tiny/l/" + code)   # a visit pushes it out to 180 days again
        with server.db() as con:
            exp = con.execute("SELECT expires FROM links WHERE code = ?", (code,)).fetchone()[0]
        self.assertGreater(exp, server.now() + 179 * 86400)
        with server.db() as con:
            con.execute("UPDATE links SET expires = ? WHERE code = ?", (server.now() - 1, code))
        server.cleanup_once()
        with server.db() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone())

    def test_08_cross_site_writes_refused(self):
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "BTC", "address": BTC, "keep": "1d"}, headers={"Origin": "https://evil.example", "Host": "tiny.gmcat.io"})
        self.assertEqual(st, 403)

    def test_09_signin_closed_while_plus_off(self):
        admin("settings", {"premium": "off"})
        self.assertEqual(req("GET", "/api/tiny/wallet/challenge")[0], 403)
        st, _, r = req("GET", "/api/tiny/gmcat/start?mode=email")
        self.assertEqual(st, 302)
        self.assertIn("signin-error=off", r.getheader("Location"))

    def test_10_gmcat_account_sign_in(self):
        admin("settings", {"premium": "testing"})
        st, _, r = req("GET", "/api/tiny/gmcat/start?mode=email")
        loc = r.getheader("Location")
        self.assertTrue(loc.startswith("https://account.gmcat.io/connect?client=tiny&state="), loc)
        self.assertIn("lite=1", loc)
        state = loc.split("state=")[1].split("&")[0]
        cookie = r.getheader("Set-Cookie").split(";")[0]
        # wrong cookie -> refused
        st, _, r2 = req("GET", "/api/tiny/gmcat/return?state=%s&code=good-code-0123456789abcdef" % state, cookie="tiny_connect=other")
        self.assertIn("signin-error=expired", r2.getheader("Location"))
        st, _, r = req("GET", "/api/tiny/gmcat/start")
        state = r.getheader("Location").split("state=")[1].split("&")[0]
        cookie = r.getheader("Set-Cookie").split(";")[0]
        st, _, r = req("GET", "/api/tiny/gmcat/return?state=%s&code=good-code-0123456789abcdef" % state, cookie=cookie)
        self.assertEqual(r.getheader("Location"), "/plus/")
        sess = [c for c in r.msg.get_all("Set-Cookie") if c.startswith("tiny_s=")][0]
        self.assertIn("HttpOnly", sess)
        st, me, _ = req("GET", "/api/tiny/me", cookie=sess.split(";")[0])
        self.assertTrue(me["signed_in"])
        self.assertEqual(me["label"], "Sam")
        self.assertFalse(me["plus"])
        # sign out ends only this session
        st, _, r = req("DELETE", "/api/tiny/session", cookie=sess.split(";")[0])
        self.assertEqual(req("GET", "/api/tiny/me", cookie=sess.split(";")[0])[1]["signed_in"], False)

    def test_11_plus_pages_names_verify_and_payments(self):
        if not HAVE_SIGNER:
            self.skipTest("needs node + the EMURGO Cardano libraries (see _have_signer)")
        admin("settings", {"premium": "testing"})
        ck = wallet_session()
        items = [{"coin": "ADA", "address": ADA, "label": "Tips"}, {"coin": "BTC", "address": BTC}]
        self.assertEqual(req("POST", "/api/tiny/plus/links", {"items": items}, cookie=ck)[0], 402)   # no Plus yet
        self.assertEqual(admin("gift", {"ref": REF_W, "days": 30})[0], 200)
        page = {"items": items, "title": "Sam's tip jar", "bio": "<script>alert(1)</script> Thanks for the coffee",
                "avatar": {"e": "☕", "c": 3}, "socials": [{"url": "https://x.com/GmCatIO"}]}
        st, d, _ = req("POST", "/api/tiny/plus/links", page, cookie=ck)
        self.assertEqual(st, 201, d)
        code = d["code"]
        self.assertEqual(d["mode"], "forever")
        self.assertIsNone(d["expires"])
        self.assertEqual(d["bio"], "<script>alert(1)</script> Thanks for the coffee")   # stored as text; pages escape it
        self.assertEqual(req("POST", "/api/tiny/plus/links", dict(page, socials=["javascript:alert(1)"]), cookie=ck)[0], 400)
        # visits are counted per day for owners (not when the owner looks)
        req("GET", "/api/tiny/l/" + code, ip="10.7.0.1")
        req("GET", "/api/tiny/l/" + code, ip="10.7.0.2")
        req("GET", "/api/tiny/l/" + code, cookie=ck)
        st, s, _ = req("GET", "/api/tiny/plus/links/%s/stats" % code, cookie=ck)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["days"][-1]["n"], 2)
        self.assertEqual(len(s["days"]), 60)
        # Verified owner: a wallet that really holds the address signs; anyone else's signature is refused
        w = sign("x")
        st, d, _ = req("PUT", "/api/tiny/plus/links/" + code, dict(page, items=[{"coin": "ADA", "address": w["address"]}, items[1]]), cookie=ck)
        self.assertEqual(st, 200)
        self.assertTrue(d["changed_at"])           # ADA address replaced -> visible notice
        self.assertEqual(d["prev_tails"], [ADA[-6:]])
        st, ch, _ = req("POST", "/api/tiny/plus/verify/challenge", {"code": code, "address": w["address"]}, cookie=ck)
        self.assertEqual(st, 200, ch)
        bad = sign(ch["message"])   # a different wallet
        st, d, _ = req("POST", "/api/tiny/plus/verify", {"nonce": ch["nonce"], "signature": bad["signature"], "key": bad["key"]}, cookie=ck)
        self.assertEqual(st, 400)
        st, ch, _ = req("POST", "/api/tiny/plus/verify/challenge", {"code": code, "address": w["address"]}, cookie=ck)
        signed = sign_exact(ch["message"], w["private"], w["address"])
        st, d, _ = req("POST", "/api/tiny/plus/verify", {"nonce": ch["nonce"], "signature": signed["signature"], "key": signed["key"]}, cookie=ck)
        self.assertEqual(st, 200, d)
        self.assertTrue(d["items"][0]["verified"])
        self.assertFalse(d["items"][1]["verified"])
        st, v, _ = req("GET", "/api/tiny/l/" + code, ip="10.7.0.3")
        self.assertTrue(v["items"][0]["verified"])
        # changing that address drops its badge
        st, d, _ = req("PUT", "/api/tiny/plus/links/" + code, dict(page, items=[{"coin": "ADA", "address": ADA}, items[1]]), cookie=ck)
        self.assertFalse(d["items"][0]["verified"])
        # names
        self.assertFalse(req("GET", "/api/tiny/plus/names/check?name=gmcat", cookie=ck)[1]["available"])
        self.assertFalse(req("GET", "/api/tiny/plus/names/check?name=ab", cookie=ck)[1]["available"])
        self.assertTrue(req("GET", "/api/tiny/plus/names/check?name=sam-tips", cookie=ck)[1]["available"])
        self.assertEqual(req("POST", "/api/tiny/plus/links", dict(page, name="sam-tips"), cookie=ck)[0], 403)   # not owned
        # buying: refused while testing, then works once on + priced
        self.assertEqual(req("POST", "/api/tiny/plus/buy", {"product": "plus"}, cookie=ck)[0], 503)
        admin("settings", {"premium": "on", "plus_usd": "12", "name_usd_3": "40", "name_usd_4": "20", "name_usd_5": "8"})
        st, cfg, _ = req("GET", "/api/tiny/config")
        self.assertTrue(cfg["can_buy"])
        self.assertEqual(cfg["prices"]["plus"], 12.0)
        st, q, _ = req("POST", "/api/tiny/plus/buy", {"product": "name", "name": "sam-tips"}, cookie=ck)
        self.assertEqual(st, 201, q)
        self.assertEqual(q["usd"], 8.0)
        self.assertEqual(STUB["quotes"][q["id"]]["ref"][:5], "tiny-")
        # someone else can't grab a name that is being paid for
        ck2 = wallet_session_other()
        admin("gift", {"ref": "acctrefOTHEROTHEROTHEROTHER", "days": 5})
        self.assertFalse(req("GET", "/api/tiny/plus/names/check?name=sam-tips", cookie=ck2)[1]["available"])
        STUB["status"][q["id"]] = "paid"
        st, s, _ = req("GET", "/api/tiny/plus/buy/" + q["id"], cookie=ck)
        self.assertEqual(s["status"], "paid")
        st, d, _ = req("POST", "/api/tiny/plus/links", dict(page, name="sam-tips"), cookie=ck)
        self.assertEqual(st, 201, d)
        self.assertEqual(d["code"], "@sam-tips")
        self.assertEqual(req("GET", "/api/tiny/l/@sam-tips", ip="10.7.0.9")[1]["title"], "Sam's tip jar")
        # Plus bought: +365 days on top of the gift
        st, q2, _ = req("POST", "/api/tiny/plus/buy", {"product": "plus"}, cookie=ck)
        STUB["status"][q2["id"]] = "paid"
        server.payments_once()   # the background sweep applies it too
        me = req("GET", "/api/tiny/me", cookie=ck)[1]
        self.assertGreater(me["plus_until"], server.now() + 390 * 86400)
        self.assertEqual(me["names"][0]["name"], "sam-tips")
        self.assertEqual(len(me["links"]), 2)
        # Plus runs out: permanent links become "keep while in use"; a lapsed name goes after its grace month
        with server.db() as con:
            con.execute("UPDATE accounts SET plus_until = ? WHERE ref = ?", (server.now() - 10, REF_W))
        server.cleanup_once()
        with server.db() as con:
            modes = {r[0]: (r[1], r[2]) for r in con.execute("SELECT code, mode, expires FROM links WHERE owner = ?", (REF_W,))}
            self.assertTrue(all(m == "inuse" and e > server.now() for m, e in modes.values()), modes)
            con.execute("UPDATE names SET until = ? WHERE name = 'sam-tips'", (server.now() - 31 * 86400,))
        server.cleanup_once()
        self.assertEqual(req("GET", "/api/tiny/l/@sam-tips", ip="10.7.0.9")[0], 404)
        admin("settings", {"premium": "testing"})

    def test_12_account_events(self):
        admin("settings", {"premium": "testing"})
        ck = wallet_session(ip="10.8.0.1")
        admin("gift", {"ref": REF_W, "days": 30})
        st, d, _ = req("POST", "/api/tiny/plus/links", {"items": [{"coin": "ETH", "address": ETH}]}, cookie=ck)
        code = d["code"]
        auth = {"Authorization": "Bearer connect-test-secret"}
        # from the internet (Nginx adds X-Real-IP): refused before the secret is looked at
        self.assertEqual(req("POST", "/api/gmcat/event", {"account_ref": REF_W, "event": "summary"}, headers=auth)[0], 404)
        def ev(event, secret="connect-test-secret"):
            c = http.client.HTTPConnection("127.0.0.1", PORT)
            c.request("POST", "/api/gmcat/event", json.dumps({"account_ref": REF_W, "event": event}), {"Authorization": "Bearer " + secret, "Content-Type": "application/json"})
            r = c.getresponse()
            return r.status, json.loads(r.read())
        self.assertEqual(ev("summary", "wrong")[0], 401)
        st, s = ev("summary")
        self.assertEqual(st, 200)
        self.assertGreaterEqual(s["entries"], 1)
        ev("disconnected")
        self.assertFalse(req("GET", "/api/tiny/me", cookie=ck)[1]["signed_in"])
        self.assertEqual(req("GET", "/api/tiny/l/" + code, ip="10.8.0.2")[0], 200)   # disconnect keeps the data
        st, s = ev("account-deleted")
        self.assertTrue(s["erased"])
        self.assertEqual(req("GET", "/api/tiny/l/" + code, ip="10.8.0.2")[0], 404)   # account deleted -> its links go
        # the daily safety net forgets accounts the account service calls gone (410)
        with server.db() as con:
            con.execute("INSERT INTO accounts (ref, created, seen) VALUES (?, 0, 0)", (REF_GONE,))
        server.sweep_accounts_once()
        with server.db() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM accounts WHERE ref = ?", (REF_GONE,)).fetchone())


class W(unittest.TestCase):
    def test_13_receiving_wallets(self):
        st, o, _ = req("GET", "/api/tiny/admin/overview", headers={"X-Admin-Key": "admin-test-key"})
        self.assertEqual([w["chain"] for w in o["wallets"]], ["cardano", "bitcoin", "evm", "solana", "tron", "litecoin", "dogecoin", "xrp"])
        self.assertEqual(o["settings"]["gmgm_discount"], "25")
        self.assertEqual(admin("wallet", {"chain": "bitcoin", "address": BTC[:-1] + "n"})[0], 400)          # typo refused
        self.assertEqual(admin("wallet", {"chain": "evm", "address": BTC})[0], 400)                          # wrong chain refused
        self.assertEqual(admin("wallet", {"chain": "evm", "address": ETH.lower()})[1]["address"], ETH)     # normalised
        self.assertEqual(admin("wallet", {"chain": "xrp", "address": "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh"})[0], 200)
        self.assertEqual(admin("wallet", {"chain": "xrp", "address": ""})[0], 200)                           # cleared
        st, o, _ = req("GET", "/api/tiny/admin/overview", headers={"X-Admin-Key": "admin-test-key"})
        self.assertEqual([w["address"] for w in o["wallets"] if w["chain"] == "evm"], [ETH])
        self.assertEqual([(l["chain"], l["new"]) for l in o["wallet_log"]][:2], [("xrp", ""), ("xrp", "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh")])
        self.assertEqual(admin("settings", {"gmgm_discount": "95"})[0], 400)
        self.assertEqual(admin("settings", {"gmgm_discount": "30"})[1]["settings"]["gmgm_discount"], "30")
        self.assertEqual(req("POST", "/api/tiny/admin/wallet", {"chain": "bitcoin", "address": BTC}, headers={"X-Admin-Key": "nope"})[0], 403)


def sol_wallet(message=None, priv=None):
    """A throwaway Solana wallet (Node's built-in Ed25519): address + signature of `message` (hex)."""
    js = r"""
const c = require('crypto'); const [msg, priv] = process.argv.slice(1);
const k = priv ? c.createPrivateKey({key: Buffer.from(priv, 'hex'), format: 'der', type: 'pkcs8'}) : c.generateKeyPairSync('ed25519').privateKey;
const pub = Buffer.from(c.createPublicKey(k).export({format: 'jwk'}).x, 'base64url');
console.log(JSON.stringify({pub: pub.toString('hex'), priv: k.export({format: 'der', type: 'pkcs8'}).toString('hex'), sig: msg ? c.sign(null, Buffer.from(msg), k).toString('hex') : ''}));
"""
    out = json.loads(subprocess.check_output(["node", "-e", js, message or "", priv or ""], text=True))
    n, alpha = int(out["pub"], 16), "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    addr = ""
    while n:
        n, r = divmod(n, 58)
        addr = alpha[r] + addr
    out["address"] = "1" * (len(out["pub"]) // 2 - len(bytes.fromhex(out["pub"]).lstrip(b"\x00"))) + addr
    return out


class F(unittest.TestCase):
    def test_30_free_tier_switch(self):
        st, d, _ = req("POST", "/api/tiny/links", {"coin": "BTC", "address": BTC, "keep": "1d", "memo": "free-switch"}, ip="10.30.0.1")
        self.assertEqual(st, 201)
        self.assertEqual(req("GET", "/api/tiny/config")[1]["free"], "on")
        self.assertEqual(admin("settings", {"free": "maybe"})[0], 400)
        admin("settings", {"free": "off"})
        st, e, _ = req("POST", "/api/tiny/links", {"coin": "BTC", "address": BTC, "keep": "1d", "memo": "free-switch-2"}, ip="10.30.0.1")
        self.assertEqual(st, 503)
        self.assertIn("paused", e["error"])
        self.assertEqual(req("GET", "/api/tiny/l/" + d["code"], ip="10.30.0.2")[0], 200)   # existing links still open
        admin("settings", {"free": "on"})


class P(unittest.TestCase):
    """Privacy Plus: one link's upgrades without an account."""

    def setUp(self):
        admin("settings", {"privacy": "off", "pp_keep_usd": "0", "pp_page_usd": "0", "pp_stats_usd": "0"})

    def mk(self, addr, coin="ADA", ip="10.20.0.1", keep="inuse", memo=""):
        st, d, _ = req("POST", "/api/tiny/links", {"coin": coin, "address": addr, "keep": keep, "memo": memo}, ip=ip)
        self.assertEqual(st, 201, d)
        self.assertEqual(d["owner_key"], d["delete_token"])
        return d["code"], d["owner_key"]

    def test_20_off_testing_grant_and_owner_edit(self):
        code, key = self.mk(ADA, memo="pp1")
        self.assertFalse(req("GET", "/api/tiny/l/%s/upgrades" % code)[1]["open"])
        admin("settings", {"privacy": "testing"})
        st, u, _ = req("GET", "/api/tiny/l/%s/upgrades" % code)
        self.assertTrue(u["open"])
        self.assertFalse(u["can_buy"])
        self.assertFalse(u["owner"])
        self.assertEqual([x["id"] for x in u["upgrades"]], ["keep", "page", "stats", "name"])
        self.assertTrue(req("GET", "/api/tiny/l/%s/upgrades" % code, headers={"X-Owner-Key": key})[1]["owner"])
        self.assertEqual(req("POST", "/api/tiny/l/%s/upgrade" % code, {"upgrade": "keep"})[0], 503)   # not on sale while testing
        page = {"items": [{"coin": "ADA", "address": ADA}, {"coin": "BTC", "address": BTC}], "title": "Tips", "bio": "hi", "socials": []}
        self.assertEqual(req("PUT", "/api/tiny/l/" + code, page, headers={"X-Owner-Key": key})[0], 402)   # needs the Tip page upgrade
        self.assertEqual(admin("grant", {"code": "https://tiny.gmcat.io/" + code, "upgrade": "page", "days": 30})[0], 200)
        self.assertEqual(req("PUT", "/api/tiny/l/" + code, page, headers={"X-Owner-Key": "wrong"})[0], 403)
        st, d, _ = req("PUT", "/api/tiny/l/" + code, page, headers={"X-Owner-Key": key})
        self.assertEqual(st, 200, d)
        self.assertEqual(len(d["items"]), 2)
        self.assertTrue(d["page"])
        # an address swap shows the notice
        st, d, _ = req("PUT", "/api/tiny/l/" + code, dict(page, items=[{"coin": "BTC", "address": BTC}]), headers={"X-Owner-Key": key})
        self.assertEqual(d["prev_tails"], [ADA[-6:]])
        # an edited page is no longer the "same address, same link" answer
        st, d2, _ = req("POST", "/api/tiny/links", {"coin": "ADA", "address": ADA, "keep": "inuse", "memo": "pp1"}, ip="10.20.0.9")
        self.assertNotEqual(d2["code"], code)

    def test_21_wallet_always_wins_cardano_and_solana(self):
        if not HAVE_SIGNER:
            self.skipTest("needs node + the EMURGO Cardano libraries (see _have_signer)")
        admin("settings", {"privacy": "testing"})
        w = sign("x")
        code, key = self.mk(w["address"], ip="10.21.0.1")
        st, ch, _ = req("POST", "/api/tiny/l/%s/claim/challenge" % code, {"address": w["address"]})
        self.assertEqual(ch["kind"], "cardano")
        bad = sign(ch["message"])
        self.assertEqual(req("POST", "/api/tiny/l/%s/claim" % code, {"nonce": ch["nonce"], "signature": bad["signature"], "key": bad["key"]})[0], 400)
        st, ch, _ = req("POST", "/api/tiny/l/%s/claim/challenge" % code, {"address": w["address"]})
        sg = sign_exact(ch["message"], w["private"], w["address"])
        st, c, _ = req("POST", "/api/tiny/l/%s/claim" % code, {"nonce": ch["nonce"], "signature": sg["signature"], "key": sg["key"]})
        self.assertEqual(st, 200, c)
        newkey = c["owner_key"]
        self.assertEqual(req("DELETE", "/api/tiny/l/" + code, headers={"X-Owner-Key": key})[0], 403)      # the old key stopped working
        st, v, _ = req("GET", "/api/tiny/l/" + code, ip="10.21.0.2")
        self.assertTrue(v["items"][0]["verified"] and v["claimed"])
        # Solana
        sw = sol_wallet()
        self.assertEqual(server.coins.check("SOL", sw["address"])[0], sw["address"])
        code2, key2 = self.mk(sw["address"], coin="SOL", ip="10.21.0.3")
        st, ch, _ = req("POST", "/api/tiny/l/%s/claim/challenge" % code2, {"address": sw["address"]})
        self.assertEqual(ch["kind"], "solana")
        other = sol_wallet(ch["message"])
        self.assertEqual(req("POST", "/api/tiny/l/%s/claim" % code2, {"nonce": ch["nonce"], "signature": other["sig"]})[0], 400)
        st, ch, _ = req("POST", "/api/tiny/l/%s/claim/challenge" % code2, {"address": sw["address"]})
        good = sol_wallet(ch["message"], sw["priv"])
        st, c, _ = req("POST", "/api/tiny/l/%s/claim" % code2, {"nonce": ch["nonce"], "signature": good["sig"]})
        self.assertEqual(st, 200, c)
        # Bitcoin can't be claimed by wallet: owner key only
        code3, _ = self.mk(BTC, coin="BTC", ip="10.21.0.4", memo="nb")
        self.assertEqual(req("POST", "/api/tiny/l/%s/claim/challenge" % code3, {"address": BTC})[0], 400)
        # a new owner key on request
        st, r, _ = req("POST", "/api/tiny/l/%s/rekey" % code, {}, headers={"X-Owner-Key": newkey})
        self.assertEqual(req("DELETE", "/api/tiny/l/" + code, headers={"X-Owner-Key": newkey})[0], 403)
        self.assertEqual(req("DELETE", "/api/tiny/l/" + code, headers={"X-Owner-Key": r["owner_key"]})[0], 200)

    def test_22_paying_keep_name_stats(self):
        admin("settings", {"privacy": "on", "pp_keep_usd": "2", "pp_page_usd": "4", "pp_stats_usd": "1", "name_usd_5": "8", "gmgm_discount": "25"})
        code, key = self.mk(ETH, coin="ETH", ip="10.22.0.1", keep="7d")
        # anyone can keep it alive (no key); $GMGM is offered with the discount
        st, o, _ = req("POST", "/api/tiny/l/%s/upgrade" % code, {"upgrade": "keep"}, ip="10.22.0.5")
        self.assertEqual(st, 201, o)
        self.assertEqual(o["options"][0]["coin"], "GMGM")
        self.assertEqual(o["options"][0]["discount"], 25)
        self.assertEqual(STUB["quotes"][o["id"]]["usd"], 1.5)   # $2 minus 25%
        self.assertEqual(req("POST", "/api/tiny/l/%s/upgrade" % code, {"upgrade": "stats"}, ip="10.22.0.5")[0], 403)   # owner only
        STUB["status"][o["id"]] = "paid"
        st, s, _ = req("GET", "/api/tiny/orders/" + o["id"])
        self.assertEqual(s.get("status"), "paid", s)
        st, v, _ = req("GET", "/api/tiny/l/" + code, ip="10.22.0.6")
        self.assertEqual(v["supporters"], 1)
        self.assertGreater(v["kept_until"], server.now() + 360 * 86400)
        self.assertGreater(v["expires"], server.now() + 360 * 86400)   # the 7-day link now lasts the year
        # a visit never shortens a kept "in use" link
        code_i, key_i = self.mk(ADA, ip="10.22.0.2", memo="kept")
        admin("grant", {"code": code_i, "upgrade": "keep", "days": 365})
        with server.db() as con:
            con.execute("UPDATE links SET last_visit = 0 WHERE code = ?", (code_i,))
        req("GET", "/api/tiny/l/" + code_i, ip="10.22.0.7")
        with server.db() as con:
            self.assertGreater(con.execute("SELECT expires FROM links WHERE code = ?", (code_i,)).fetchone()[0], server.now() + 360 * 86400)
        # a custom name for the link, then @name opens it
        self.assertTrue(req("GET", "/api/tiny/l/%s/name-check?name=gmcatfan" % code, headers={"X-Owner-Key": key})[1]["available"] is False)
        self.assertTrue(req("GET", "/api/tiny/l/%s/name-check?name=pixelfan" % code, headers={"X-Owner-Key": key})[1]["available"])
        st, o2, _ = req("POST", "/api/tiny/l/%s/upgrade" % code, {"upgrade": "name", "name": "pixelfan"}, headers={"X-Owner-Key": key})
        self.assertEqual(st, 201, o2)
        STUB["status"][o2["id"]] = "paid"
        server.payments_once()
        st, v, _ = req("GET", "/api/tiny/l/@pixelfan", ip="10.22.0.8")
        self.assertEqual(st, 200)
        self.assertEqual(v["code"], code)
        # visit counts once the Stats upgrade is on
        admin("grant", {"code": code, "upgrade": "stats", "days": 30})
        req("GET", "/api/tiny/l/" + code, ip="10.22.0.9")
        st, s, _ = req("GET", "/api/tiny/l/%s/stats" % code, headers={"X-Owner-Key": key})
        self.assertEqual(st, 200)
        self.assertEqual(s["days"][-1]["n"], 1)
        self.assertEqual(req("GET", "/api/tiny/l/%s/stats" % code)[0], 403)
        # deleting the link takes its name with it
        self.assertEqual(req("DELETE", "/api/tiny/l/" + code, headers={"X-Owner-Key": key})[0], 200)
        self.assertEqual(req("GET", "/api/tiny/l/@pixelfan", ip="10.22.0.8")[0], 404)
        st, ov, _ = req("GET", "/api/tiny/admin/overview", headers={"X-Admin-Key": "admin-test-key"})
        self.assertGreaterEqual(len(ov["orders"]), 2)
        admin("settings", {"privacy": "off"})


def wallet_session_other():
    """A second signed-in person (the stand-in account service returns REF_W by default; swap it for one call)."""
    old = Stub.do_POST

    def other(self):
        if self.path == "/api/connect/wallet/sign-in":
            self.body()
            return self.reply(200, {"account_ref": "acctrefOTHEROTHEROTHEROTHER", "wallet": "stake1other"})
        return old(self)
    Stub.do_POST = other
    try:
        return wallet_session(ip="10.9.9.9")
    finally:
        Stub.do_POST = old


def sign_exact(message, private, address):
    """Sign as exactly this base address (its payment key = `private`)."""
    js = r"""
import { createRequire } from 'node:module';
const load = createRequire(import.meta.url), Cardano = load('@emurgo/cardano-serialization-lib-nodejs'), MS = load('@emurgo/cardano-message-signing-nodejs');
const [message, priv, bech] = process.argv.slice(2);
const privateKey = Cardano.PrivateKey.from_normal_bytes(Buffer.from(priv, 'hex')), publicKey = privateKey.to_public(), address = Cardano.Address.from_bech32(bech);
const pm = MS.HeaderMap.new(); pm.set_algorithm_id(MS.Label.from_algorithm_id(MS.AlgorithmId.EdDSA)); pm.set_header(MS.Label.new_text('address'), MS.CBORValue.new_bytes(Buffer.from(address.to_hex(), 'hex')));
const um = MS.HeaderMap.new(); um.set_header(MS.Label.new_text('hashed'), MS.CBORValue.new_special(MS.CBORSpecial.new_bool(false)));
const builder = MS.COSESign1Builder.new(MS.Headers.new(MS.ProtectedHeaderMap.new(pm), um), new TextEncoder().encode(message), false), signed = builder.build(privateKey.sign(builder.make_data_to_sign().to_bytes()).to_bytes());
const key = MS.COSEKey.new(MS.Label.from_key_type(MS.KeyType.OKP)); key.set_algorithm_id(MS.Label.from_algorithm_id(MS.AlgorithmId.EdDSA));
key.set_header(MS.Label.from_ec_key(MS.ECKey.CRV), MS.CBORValue.from_label(MS.Label.from_curve_type(MS.CurveType.Ed25519))); key.set_header(MS.Label.from_ec_key(MS.ECKey.X), MS.CBORValue.new_bytes(publicKey.as_bytes()));
console.log(JSON.stringify({ signature: Buffer.from(signed.to_bytes()).toString('hex'), key: Buffer.from(key.to_bytes()).toString('hex') }));
"""
    f = HERE / ".sign_exact.mjs"
    f.write_text(js)
    try:
        return json.loads(subprocess.check_output(["node", str(f), message, private, address], text=True))
    finally:
        f.unlink()


if __name__ == "__main__":
    start()
    unittest.main(verbosity=2)
