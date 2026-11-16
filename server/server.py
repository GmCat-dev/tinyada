#!/usr/bin/env python3
"""TinyADA: short links for crypto addresses at tiny.gmcat.io (TinyADA.com from 2019, revived 2026).

A small standard-library service behind Nginx on 127.0.0.1:4199 (same pattern as Pawste and Drop).

Free (no account):
  GET    /api/tiny/config                    what the pages should offer (Plus switch, prices, coins)
  POST   /api/tiny/links {coin, address|handle, amount, memo, keep}   -> {code, link, expires, mode, delete_token}
         keep: 1d | 7d | 30d | inuse ("keep while in use": deleted after INUSE_DAYS without a visit).
         The same address (+ amount + note) always gets the same free link: a second request returns the first link
         (and keeps it at least as long as asked), so nobody can mint thousands of links for one address.
  GET    /api/tiny/l/<code>                  the link page's data; counts a visit (link previews never run the page
                                             script, so they don't count) and keeps "in use" links alive
  DELETE /api/tiny/l/<code>                  delete a free link                                   [X-Delete-Token]
  POST   /api/tiny/l/<code>/report {reason, details}   3 reports from different visitors hide a link
  GET    /api/tiny/handle/<name>             a Cardano $handle's current address (api.handle.me, cached)
Signed in (GmCat account / email / wallet, all through account.gmcat.io; cookie tiny_s):
  GET    /api/tiny/gmcat/start?mode=account|email      GET /api/tiny/gmcat/return
  GET    /api/tiny/wallet/challenge                    POST /api/tiny/wallet/verify {nonce, address, signature, key}
  GET    /api/tiny/me                        account, Plus, links, names, open payments
  DELETE /api/tiny/session                   sign out of TinyADA only
Plus (needs an active Plus; links stay permanent while it lasts):
  POST   /api/tiny/plus/links {name?, items[], title, bio, avatar, socials}    tip page / custom name / permanent link
  PUT    /api/tiny/plus/links/<code>         edit (an address change is shown on the page for 30 days)
  DELETE /api/tiny/plus/links/<code>
  GET    /api/tiny/plus/links/<code>/stats   visits per day, last 60 days
  POST   /api/tiny/plus/verify/challenge {code, address}   POST /api/tiny/plus/verify {nonce, signature, key}
  GET    /api/tiny/plus/names/check?name=    available? price?
  POST   /api/tiny/plus/buy {product: plus|name, name}     a $GMGM payment request through GmCat Drop's checker
  GET    /api/tiny/plus/buy/<id>             paid yet? (paid = applied right away)
For the account service on this machine only (refused when Nginx forwarded it):
  POST   /api/gmcat/event {account_ref, event: summary|disconnected|account-deleted}     [Bearer connect secret]
Admin (the owner's dashboard forwards these with the admin key; only its SHA-256 lives here, TINY_ADMIN_KEY_SHA256):
  GET    /api/tiny/admin/overview            POST /api/tiny/admin/settings {premium, teaser, prices}
  POST   /api/tiny/admin/hold|restore|delete {code}   /dismiss {report}   /gift {ref, days}   /release-name {name}

THE PLUS SWITCH (settings.premium, changed from the admin dashboard): off = no sign-in, nothing about Plus anywhere;
testing = /plus/ works for anyone who knows it (sign-in allowed, buying off, Plus only by HQ gift), no public links;
on = Plus is public and can be bought (once prices are set and Drop's $GMGM checker is connected).
settings.teaser = show a "Plus is coming" card on the home page while premium isn't on.

Privacy: no IP addresses stored (salted in-memory hashes for rate limits), delete tokens and session tokens stored as
SHA-256, visit counts are plain numbers per day. Data: TINY_DATA/tiny.db (SQLite). Expired links are deleted every minute.
Dev mode (TINY_DEV_STATIC=<dist/tiny>): also serves the built site, for local tests.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coins  # noqa: E402
import cose   # noqa: E402
import payments  # noqa: E402  (the payment socket: GmCat Pay plugs in there later)

DATA = Path(os.environ.get("TINY_DATA", "/var/lib/gmcat-tinyada"))
PORT = int(os.environ.get("TINY_PORT", "4199"))
ADMIN_SHA = os.environ.get("TINY_ADMIN_KEY_SHA256", "").strip().lower()
DEV_STATIC = os.environ.get("TINY_DEV_STATIC", "")
LINK_BASE = os.environ.get("TINY_LINK_BASE", "https://tiny.gmcat.io/")
HANDLE_API = os.environ.get("TINY_HANDLE_API", "https://api.handle.me").rstrip("/")
GMGM_API = os.environ.get("TINY_GMGM_API", "http://127.0.0.1:4196").rstrip("/")
GMGM_SECRET = os.environ.get("TINY_GMGM_SECRET", "")
COOKIE_SECURE = os.environ.get("TINY_COOKIE_SECURE", "1") != "0"

DAY = 86400
INUSE_DAYS = 180
KEEP = {"1d": DAY, "7d": 7 * DAY, "30d": 30 * DAY, "inuse": INUSE_DAYS * DAY}
KEEP_RANK = {"1d": 1, "7d": 2, "30d": 3, "inuse": 4, "forever": 5}
CHANGE_NOTICE_DAYS = 30
NAME_GRACE_DAYS = 30
SESSION_DAYS = 60
MAX_ITEMS = 8
MAX_SOCIALS = 5
REPORTS_TO_HIDE = 3
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"   # no look-alikes (0/o, 1/l/i)
CODE_LEN = 6
CODE_RE = re.compile(r"^[%s]{%d}$" % (ALPHABET, CODE_LEN))
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{1,18}[a-z0-9])$")
LINK_RE = re.compile(r"^(?:[%s]{%d}|@[a-z0-9_-]{3,20})$" % (ALPHABET, CODE_LEN))
REF_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
REASONS = {"scam", "impersonation", "spam", "illegal", "other"}
AVATARS = ["☕", "🐾", "🐱", "🌙", "⭐", "🎨", "🎮", "🎵", "💎", "🌱", "🔥", "🍀", "🚀", "🌈", "📚", "🧡"]
AVATAR_COLORS = 8
RESERVED = {"admin", "api", "app", "about", "account", "blog", "cardano", "contact", "dev", "drop", "faq", "gmcat", "gmgm",
            "help", "home", "info", "login", "mail", "me", "mod", "moderator", "new", "official", "overlay", "paw", "pawste",
            "pay", "plus", "print", "privacy", "root", "security", "settings", "shop", "signin", "signup", "staff",
            "status", "support", "system", "team", "terms", "tiny", "tinyada", "tools", "verify", "wallet", "why", "www"}
LIMITS = {"claim": (20, 3600), "order": (10, 3600), "create": (20, 3600), "miss": (120, 3600), "report": (10, 3600), "handle": (60, 3600), "edit": (120, 3600),
          "verify": (30, 3600), "buy": (10, 3600), "signin": (30, 3600), "name": (120, 3600)}
DEFAULTS = {"premium": "off", "teaser": "0", "plus_usd": "0", "name_usd_3": "0", "name_usd_4": "0", "name_usd_5": "0", "gmgm_discount": "25",
            "free": "on", "privacy": "off", "pp_keep_usd": "0", "pp_page_usd": "0", "pp_stats_usd": "0"}
# Privacy Plus: upgrades bought for ONE link, no account. Each lasts a year from when it's paid (or from
# when the current one ends). "keep" can be paid by anyone (fans keeping a creator's link alive); the rest need the owner
# (owner key, or a wallet signature from an address on the link: the wallet always wins).
UPGRADES = {
    "keep": {"owner": False, "price": "pp_keep_usd", "label": "Keep it for a year", "about": "Stays up for a year, visited or not. Anyone can pay this."},
    "page": {"owner": True, "price": "pp_page_usd", "label": "Tip page for a year", "about": "Up to 8 coins, a title, picture, short bio and social links. Edit any time, even the address (visitors are told when it changes)."},
    "stats": {"owner": True, "price": "pp_stats_usd", "label": "Visit counts for a year", "about": "How many people opened the link each day. No personal tracking."},
    "name": {"owner": True, "price": None, "label": "Custom name for a year", "about": "tiny.gmcat.io/@yourname opens this link."},
}
WALLET_CHAINS = {c[0]: c for c in coins.RECEIVE_CHAINS}   # receiving wallets for Privacy Plus (not used for payments yet)

SALT = secrets.token_bytes(32)          # new every start: visitor hashes can't be linked across restarts
HITS, HITS_LOCK, DB_LOCK = {}, threading.Lock(), threading.Lock()
CHALLENGES, HANDLES = {}, {}            # in memory: wallet/verify challenges (10 min), $handle answers (10 min)
CONNECT = None


def now():
    return int(time.time())


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def db():
    # autocommit: every change is saved before the reply goes out (writes are serialised by DB_LOCK)
    con = sqlite3.connect(str(DATA / "tiny.db"), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def init():
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS links (
            code TEXT PRIMARY KEY, owner TEXT, mode TEXT NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL,
            expires INTEGER, last_visit INTEGER NOT NULL, visits INTEGER NOT NULL DEFAULT 0, dedupe TEXT, delete_hash TEXT,
            held INTEGER NOT NULL DEFAULT 0, items TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '',
            avatar TEXT NOT NULL DEFAULT '', socials TEXT NOT NULL DEFAULT '[]', verified TEXT NOT NULL DEFAULT '[]',
            changed_at INTEGER, prev_tails TEXT NOT NULL DEFAULT '[]');
        CREATE INDEX IF NOT EXISTS links_expires ON links(expires);
        CREATE INDEX IF NOT EXISTS links_dedupe ON links(dedupe);
        CREATE INDEX IF NOT EXISTS links_owner ON links(owner);
        CREATE TABLE IF NOT EXISTS names (name TEXT PRIMARY KEY, owner TEXT NOT NULL, created INTEGER NOT NULL, until INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS accounts (ref TEXT PRIMARY KEY, label TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL,
            seen INTEGER NOT NULL, plus_until INTEGER NOT NULL DEFAULT 0, checked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, ref TEXT NOT NULL, created INTEGER NOT NULL,
            expires INTEGER NOT NULL, via TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS daily (code TEXT NOT NULL, day INTEGER NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (code, day));
        CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, created INTEGER NOT NULL,
            reason TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', visitor TEXT NOT NULL, open INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, ref TEXT NOT NULL, product TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
            usd REAL NOT NULL, amount INTEGER NOT NULL, address TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open', paid_at INTEGER, tx TEXT);
        CREATE TABLE IF NOT EXISTS stats (k TEXT PRIMARY KEY, v INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, code TEXT NOT NULL, upgrade TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
            usd REAL NOT NULL, options TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open',
            paid_at INTEGER, tx TEXT, provider TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS orders_open ON orders(status, created);
        CREATE TABLE IF NOT EXISTS wallets (chain TEXT PRIMARY KEY, address TEXT NOT NULL, updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS wallet_log (id INTEGER PRIMARY KEY AUTOINCREMENT, chain TEXT NOT NULL, old TEXT NOT NULL, new TEXT NOT NULL, at INTEGER NOT NULL);
        """)
        cols = [r[1] for r in con.execute("PRAGMA table_info(links)")]
        for col, ddl in (("features", "TEXT NOT NULL DEFAULT '{}'"), ("supporters", "INTEGER NOT NULL DEFAULT 0"), ("claimed", "INTEGER NOT NULL DEFAULT 0")):
            if col not in cols:   # Privacy Plus (2026-11-16)
                con.execute("ALTER TABLE links ADD COLUMN %s %s" % (col, ddl))


def bump(con, key, n=1):
    con.execute("INSERT INTO stats (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = v + ?", (key, n, n))


def settings(con):
    s = dict(DEFAULTS)
    s.update({r["k"]: r["v"] for r in con.execute("SELECT k, v FROM settings")})
    return s


def price(s, key):
    try:
        return max(0.0, round(float(s.get(key) or 0), 2))
    except ValueError:
        return 0.0


def name_price(s, name):
    return price(s, "name_usd_3" if len(name) == 3 else "name_usd_4" if len(name) == 4 else "name_usd_5")


def load_connect():
    path = os.environ.get("TINY_CONNECT_FILE")
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        cfg = json.load(f)
    if not (cfg.get("secret") and cfg.get("api") and cfg.get("authorize") and cfg.get("return")):
        return None
    cfg.setdefault("manage", "https://account.gmcat.io/profile/")
    return cfg


def call(base, secret, method, path, body=None, timeout=8):
    """Server-to-server JSON call (account service, Drop's payment checker). (status, json); status 0 = unreachable."""
    req = urllib.request.Request(base.rstrip("/") + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json", "User-Agent": "gmcat-tinyada/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except Exception:
        return 0, {}


def plus_active(acct):
    return bool(acct) and acct["plus_until"] > now()


# ---------------------------------------------------------------- items, cleaning
def clean_text(s, n):
    s = re.sub(r"[\u0000-\u001f\u007f​-‏‪-‮⁦-⁩]", " ", str(s or ""))
    return re.sub(r" {2,}", " ", s).strip()[:n]


def clean_amount(v):
    if v in (None, ""):
        return ""
    try:
        d = Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError("The amount should be a number, like 5 or 0.25.")
    if not d.is_finite() or d <= 0 or d > Decimal("1000000000") or -d.as_tuple().exponent > 8:
        raise ValueError("The amount should be more than 0, with at most 8 decimal places.")
    return format(d.normalize(), "f")


def resolve_handle(name):
    """'$name' -> current ADA address or None. Cached for 10 minutes."""
    key = name.lower().lstrip("$")
    hit = HANDLES.get(key)
    if hit and hit[0] > now():
        return hit[1]
    addr = None
    try:
        req = urllib.request.Request(HANDLE_API + "/handles/" + urllib.parse.quote(key), headers={"User-Agent": "gmcat-tinyada/1", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read() or b"{}")
        a = ((d.get("resolved_addresses") or {}).get("ada") or "").strip()
        if a and coins.check("ADA", a)[0]:
            addr = coins.check("ADA", a)[0]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return None   # not sure: don't cache
    except Exception:
        return None
    if len(HANDLES) > 5000:
        HANDLES.clear()
    HANDLES[key] = (now() + 600, addr)
    return addr


def clean_item(d):
    """One coin entry -> dict, or raises ValueError with a plain reason."""
    if not isinstance(d, dict):
        raise ValueError("Something was missing.")
    coin = str(d.get("coin") or "")
    raw = coins.clean(d.get("handle") or d.get("address"))
    out = {"coin": coin}
    if raw.startswith("$"):
        if coin != "ADA" or not coins.HANDLE_RE.match(raw.lower()):
            raise ValueError("That doesn't look like a Cardano $handle.")
        addr = resolve_handle(raw)
        if not addr:
            raise ValueError("We couldn't find the address for %s. Check the spelling, or paste the address instead." % raw.lower())
        out.update(handle=raw.lower(), address=addr)
    else:
        addr, why = coins.check(coin, raw)
        if not addr:
            raise ValueError(why)
        out["address"] = addr
    amount = clean_amount(d.get("amount"))
    if amount:
        out["amount"] = amount
    memo = clean_text(d.get("memo"), 80)
    if memo:
        out["memo"] = memo
    label = clean_text(d.get("label"), 40)
    if label:
        out["label"] = label
    return out


def clean_socials(v):
    out = []
    for s in (v if isinstance(v, list) else [])[:MAX_SOCIALS]:
        url = str((s or {}).get("url") if isinstance(s, dict) else s or "").strip()[:200]
        if not url:
            continue
        if not re.match(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#][^\s<>\"']*)?$", url):
            raise ValueError("Links must be full web addresses starting with https://")
        out.append({"url": url, "label": clean_text((s or {}).get("label") if isinstance(s, dict) else "", 30)})
    return out


def clean_avatar(v):
    if not isinstance(v, dict) or v.get("e") not in AVATARS:
        return ""
    try:
        c = int(v.get("c") or 0) % AVATAR_COLORS
    except (TypeError, ValueError):
        c = 0
    return json.dumps({"e": v["e"], "c": c}, ensure_ascii=False)


def tail(addr):
    return addr[-6:]


def feats(row):
    try:
        return json.loads(row["features"] or "{}")
    except (ValueError, IndexError, KeyError):
        return {}


def has(row, feature):
    return feats(row).get(feature, 0) > now()


def discount_pct():
    with db() as con:
        try:
            return int(float(settings(con)["gmgm_discount"]))
        except ValueError:
            return 0


PAY = payments.DropGmgm(GMGM_API, GMGM_SECRET, discount_pct)


def apply_edit(con, row, items, title, bio, avatar, socials, extra_sql="", extra_args=()):
    """Save new content on a link. Removing an address shows a 30-day notice with its ending and drops its Verified tick."""
    t = now()
    before = {it["address"] for it in json.loads(row["items"])}
    after = {it["address"] for it in items}
    gone = before - after
    changed_at, tails = row["changed_at"], json.loads(row["prev_tails"])
    if gone:
        changed_at = t
        tails = (sorted(tail(a) for a in gone) + tails)[:6]
    verified = [a for a in json.loads(row["verified"]) if a in after]
    con.execute("UPDATE links SET items = ?, title = ?, bio = ?, avatar = ?, socials = ?, updated = ?, changed_at = ?, prev_tails = ?, verified = ?, dedupe = NULL"
                + extra_sql + " WHERE code = ?",
                (json.dumps(items, ensure_ascii=False), title, bio, avatar, json.dumps(socials, ensure_ascii=False), t, changed_at,
                 json.dumps(tails), json.dumps(verified), *extra_args, row["code"]))


def read_content(d):
    """(items, title, bio, avatar, socials) from an editor request, or raises ValueError with a plain reason."""
    raw_items = d.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= MAX_ITEMS:
        raise ValueError("Add between 1 and %d addresses." % MAX_ITEMS)
    items = [clean_item(x) for x in raw_items]
    return items, clean_text(d.get("title"), 60), clean_text(d.get("bio"), 280), clean_avatar(d.get("avatar")), clean_socials(d.get("socials"))


def apply_upgrade(con, code, upgrade, name="", days=365):
    """Turn on (or lengthen) an upgrade on a link. Returns None, or a plain reason it couldn't be applied."""
    row = con.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
    if not row:
        return "gone"
    t, f, add = now(), feats(row), days * DAY
    if upgrade == "name":
        nrow = con.execute("SELECT * FROM names WHERE name = ?", (name,)).fetchone()
        if nrow and nrow["owner"] != "link:" + code:
            return "taken"
        if nrow:
            con.execute("UPDATE names SET until = MAX(until, ?) + ? WHERE name = ?", (t, add, name))
        else:
            con.execute("INSERT INTO names (name, owner, created, until) VALUES (?, ?, ?, ?)", (name, "link:" + code, t, t + add))
        return None
    f[upgrade] = max(f.get(upgrade, 0), t) + add
    sets = {"features": json.dumps(f)}
    if upgrade == "keep":
        sets["supporters"] = row["supporters"] + 1
        if row["expires"] is not None:
            sets["expires"] = max(row["expires"], f["keep"])
    if upgrade == "page":
        sets["dedupe"] = None   # an editable page is its own thing now: "same address, same link" no longer points here
    con.execute("UPDATE links SET %s WHERE code = ?" % ", ".join("%s = ?" % k for k in sets), (*sets.values(), code))
    return None


# ---------------------------------------------------------------- background work
def cleanup_once():
    t = now()
    with DB_LOCK, db() as con:
        # Plus ran out: permanent links become "keep while in use", counted from the later of the last visit and the end of Plus
        con.execute("""UPDATE links SET mode = 'inuse', expires = MAX(last_visit, COALESCE((SELECT plus_until FROM accounts a WHERE a.ref = links.owner), 0)) + ?
                       WHERE mode = 'forever' AND (owner IS NULL OR owner NOT IN (SELECT ref FROM accounts WHERE plus_until > ?))""", (INUSE_DAYS * DAY, t))
        # custom names end NAME_GRACE_DAYS after their paid year (their pages go with them; the dashboard warns first)
        for (name,) in con.execute("SELECT name FROM names WHERE until + ? < ?", (NAME_GRACE_DAYS * DAY, t)).fetchall():
            remove_link(con, "@" + name)
            con.execute("DELETE FROM names WHERE name = ?", (name,))
        for (code,) in con.execute("SELECT code FROM links WHERE expires IS NOT NULL AND expires <= ?", (t,)).fetchall():
            remove_link(con, code)
        con.execute("DELETE FROM sessions WHERE expires <= ?", (t,))
        con.execute("DELETE FROM daily WHERE day < ?", (t // DAY - 400,))
    for store in (CHALLENGES,):
        for k in [k for k, v in store.items() if v["expires"] < t]:
            store.pop(k, None)
    with HITS_LOCK:
        for k in list(HITS):
            HITS[k] = [x for x in HITS[k] if x > t - 3600]
            if not HITS[k]:
                del HITS[k]


def remove_link(con, code):
    con.execute("DELETE FROM names WHERE owner = ?", ("link:" + code,))   # a Privacy Plus name goes with its link
    con.execute("DELETE FROM links WHERE code = ?", (code,))
    con.execute("DELETE FROM reports WHERE code = ?", (code,))
    con.execute("DELETE FROM daily WHERE code = ?", (code,))


def forget_account(con, ref):
    """The GmCat account is gone: everything TinyADA kept for it goes too (its pages can't be managed by anyone any more)."""
    for (code,) in con.execute("SELECT code FROM links WHERE owner = ?", (ref,)).fetchall():
        remove_link(con, code)
    con.execute("DELETE FROM names WHERE owner = ?", (ref,))
    con.execute("DELETE FROM sessions WHERE ref = ?", (ref,))
    con.execute("UPDATE quotes SET ref = '' WHERE ref = ?", (ref,))
    con.execute("DELETE FROM accounts WHERE ref = ?", (ref,))


def apply_paid(con, q):
    """A paid request: Plus +365 days, or a custom name for a year (from when the current period ends, or now)."""
    t = now()
    if q["product"] == "plus":
        con.execute("UPDATE accounts SET plus_until = MAX(plus_until, ?) + ? WHERE ref = ?", (t, 365 * DAY, q["ref"]))
    elif q["product"] == "name":
        row = con.execute("SELECT * FROM names WHERE name = ?", (q["name"],)).fetchone()
        if row and row["owner"] == q["ref"]:
            con.execute("UPDATE names SET until = MAX(until, ?) + ? WHERE name = ?", (t, 365 * DAY, q["name"]))
        elif not row:
            con.execute("INSERT INTO names (name, owner, created, until) VALUES (?, ?, ?, ?)", (q["name"], q["ref"], t, t + 365 * DAY))
        else:
            return "taken"   # someone else got it first (can only happen if HQ released and re-gave it): HQ sorts it out
    return None


def check_quote(qid):
    """Ask the payment provider about one Plus request; apply it once if paid. -> status"""
    status, tx = PAY.status(qid)
    if status is None:
        return None
    with DB_LOCK, db() as con:
        q = con.execute("SELECT * FROM quotes WHERE id = ?", (qid,)).fetchone()
        if not q:
            return None
        if status == "paid" and q["status"] != "paid":
            problem = apply_paid(con, q) if q["ref"] else None
            con.execute("UPDATE quotes SET status = ?, paid_at = ?, tx = ? WHERE id = ?", ("paid" if not problem else "paid-check", now(), tx, qid))
            bump(con, "paid")
        elif status in ("expired", "withdrawn") and q["status"] == "open":
            con.execute("UPDATE quotes SET status = ? WHERE id = ?", (status, qid))
    return status


def check_order(oid):
    """Same for a Privacy Plus order (one link's upgrade)."""
    status, tx = PAY.status(oid)
    if status is None:
        return None
    with DB_LOCK, db() as con:
        o = con.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        if not o:
            return None
        if status == "paid" and o["status"] != "paid":
            problem = apply_upgrade(con, o["code"], o["upgrade"], o["name"])
            con.execute("UPDATE orders SET status = ?, paid_at = ?, tx = ? WHERE id = ?", ("paid" if not problem else "paid-check", now(), tx, oid))
            bump(con, "pp_paid")
        elif status in ("expired", "withdrawn") and o["status"] == "open":
            con.execute("UPDATE orders SET status = ? WHERE id = ?", (status, oid))
    return status


def payments_once():
    if not PAY.ready():
        return
    with db() as con:
        since = now() - 26 * 3600
        ids = [r[0] for r in con.execute("SELECT id FROM quotes WHERE status = 'open' AND created > ?", (since,))]
        oids = [r[0] for r in con.execute("SELECT id FROM orders WHERE status = 'open' AND created > ?", (since,))]
    for qid in ids:
        check_quote(qid)
    for oid in oids:
        check_order(oid)


def sweep_accounts_once(limit=25):
    """Safety net: ask the account service about accounts not checked for a day; "410 gone" = deleted -> forget."""
    if not CONNECT:
        return
    with db() as con:
        refs = [r[0] for r in con.execute("SELECT ref FROM accounts WHERE checked < ? ORDER BY checked LIMIT ?", (now() - DAY, limit))]
    for ref in refs:
        code, _ = call(CONNECT["api"], CONNECT["secret"], "GET", "/api/connect/accounts/%s?client=tiny" % urllib.parse.quote(ref, safe=""))
        with DB_LOCK, db() as con:
            if code == 410:
                forget_account(con, ref)
            elif code == 404:
                con.execute("DELETE FROM sessions WHERE ref = ?", (ref,))
            if code in (200, 404):
                con.execute("UPDATE accounts SET checked = ? WHERE ref = ?", (now(), ref))


def loop():
    n = 0
    while True:
        for job in (cleanup_once, payments_once) + ((sweep_accounts_once,) if n % 360 == 0 else ()):
            try:
                job()
            except Exception as ex:   # keep the loop alive; the next round tries again
                print("background job failed:", job.__name__, ex, flush=True)
        n += 1
        time.sleep(30 if GMGM_SECRET else 60)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "GmCatTinyADA/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # ---- helpers
    def visitor(self):
        ip = self.headers.get("X-Real-IP") or self.client_address[0]
        return hmac.new(SALT, ip.encode(), "sha256").hexdigest()[:16]

    def limited(self, kind, record=True):
        n, window = LIMITS[kind]
        key, t = "%s:%s" % (kind, self.visitor()), now()
        with HITS_LOCK:
            recent = [x for x in HITS.get(key, []) if x > t - window]
            if len(recent) >= n:
                HITS[key] = recent
                return True
            if record:
                recent.append(t)
            HITS[key] = recent
        return False

    def send_json(self, code, data, cookies=()):
        body = json.dumps(data, ensure_ascii=False).encode()
        unread = int(self.headers.get("Content-Length") or 0) > 0 and not getattr(self, "body_read", False)
        if unread:   # refused before reading what was sent: close, so the leftover bytes can't spoil the next request
            self.close_connection = True
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("X-Content-Type-Options", "nosniff")
        for c in cookies:
            self.send_header("Set-Cookie", c)
        if unread:
            self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, code, msg, **extra):
        self.send_json(code, dict(error=msg, **extra))

    def redirect(self, location, cookies=()):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_json(self, limit=8192):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            self.close_connection = True
            raise ValueError("too large")
        self.body_read = True
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise ValueError("bad json")
        if not isinstance(d, dict):
            raise ValueError("bad json")
        return d

    def parts(self):
        u = urllib.parse.urlsplit(self.path)
        return [urllib.parse.unquote(p) for p in u.path.split("/") if p], urllib.parse.parse_qs(u.query)

    def same_origin(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return origin in ("https://" + host, "http://" + host)

    def admin_ok(self):
        key = self.headers.get("X-Admin-Key", "")
        return bool(ADMIN_SHA) and bool(key) and hmac.compare_digest(sha(key), ADMIN_SHA)

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def make_cookie(self, name, value, max_age, path="/"):
        return "%s=%s; Path=%s; Max-Age=%d; HttpOnly; SameSite=Lax%s" % (name, value, path, max_age, "; Secure" if COOKIE_SECURE else "")

    def session(self, con):
        tok = self.cookie("tiny_s")
        if not tok:
            return None
        row = con.execute("SELECT a.* FROM sessions s JOIN accounts a ON a.ref = s.ref WHERE s.token_hash = ? AND s.expires > ?",
                          (sha(tok), now())).fetchone()
        return row

    def start_session(self, con, ref, label, via):
        t = now()
        con.execute("INSERT INTO accounts (ref, label, created, seen, checked) VALUES (?, ?, ?, ?, ?) ON CONFLICT(ref) DO UPDATE SET"
                    " seen = excluded.seen, label = CASE WHEN excluded.label != '' THEN excluded.label ELSE accounts.label END",
                    (ref, clean_text(label, 40), t, t, t))
        tok = secrets.token_urlsafe(32)
        con.execute("INSERT INTO sessions (token_hash, ref, created, expires, via) VALUES (?, ?, ?, ?, ?)", (sha(tok), ref, t, t + SESSION_DAYS * DAY, via))
        bump(con, "signins")
        return self.make_cookie("tiny_s", tok, SESSION_DAYS * DAY)

    def live(self, con, code):
        if not LINK_RE.match(code or ""):
            return None
        row = con.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
        if not row and code.startswith("@"):   # a Privacy Plus custom name opens the link it belongs to
            n = con.execute("SELECT owner FROM names WHERE name = ? AND owner LIKE 'link:%' AND until + ? > ?", (code[1:], NAME_GRACE_DAYS * DAY, now())).fetchone()
            if n:
                row = con.execute("SELECT * FROM links WHERE code = ?", (n["owner"][5:],)).fetchone()
        if not row or (row["expires"] is not None and row["expires"] <= now()):
            return None
        return row

    def owner_key_ok(self, row):
        """The link's owner key (X-Owner-Key) for links made without an account. Stored only as its SHA-256."""
        tok = self.headers.get("X-Owner-Key", "") or self.headers.get("X-Delete-Token", "")
        return bool(row and not row["owner"] and row["delete_hash"] and tok and hmac.compare_digest(row["delete_hash"], sha(tok)))

    def link_json(self, row, owner_view=False, fresh=True):
        items = json.loads(row["items"])
        if fresh:
            for it in items:
                if it.get("handle"):
                    a = resolve_handle(it["handle"])
                    if a and a != it["address"]:
                        it["address"], it["moved"] = a, True
        verified = set(json.loads(row["verified"]))
        for it in items:
            it["verified"] = it["address"] in verified
            info = coins.COINS.get(it["coin"], {})
            it["name"], it["uri"] = info.get("name", it["coin"]), info.get("uri", "")
        out = {"code": row["code"], "link": LINK_BASE + row["code"], "items": items, "title": row["title"], "bio": row["bio"],
               "avatar": json.loads(row["avatar"]) if row["avatar"] else None, "socials": json.loads(row["socials"]),
               "mode": row["mode"], "expires": row["expires"], "created": row["created"], "plus": bool(row["owner"]),
               "changed_at": row["changed_at"] if row["changed_at"] and row["changed_at"] > now() - CHANGE_NOTICE_DAYS * DAY else None,
               "inuse_days": INUSE_DAYS}
        if out["changed_at"]:
            out["prev_tails"] = json.loads(row["prev_tails"])
        f = feats(row)
        t = now()
        out.update(kept_until=f.get("keep") if f.get("keep", 0) > t else None, supporters=row["supporters"], page=f.get("page", 0) > t,
                   claimed=bool(row["claimed"]))
        if owner_view:
            out.update(owner=True, visits=row["visits"], last_visit=row["last_visit"], held=bool(row["held"]),
                       features={k: v for k, v in f.items()}, names=[])
        return out

    # ---- routing
    def do_GET(self):
        parts, q = self.parts()
        try:
            if parts[:2] == ["api", "tiny"]:
                return self.get_api(parts[2:], q)
        except ValueError:
            return self.error(400, "That request didn't look right.")
        if DEV_STATIC:
            return self.dev_static(parts)
        self.error(404, "Not found.")

    def get_api(self, p, q):
        one = lambda k: (q.get(k) or [""])[0]
        if p == ["health"]:
            return self.send_json(200, {"ok": True})
        if p == ["config"]:
            return self.config()
        if len(p) == 2 and p[0] == "l":
            return self.view(p[1], count=one("nc") != "1")
        if len(p) == 2 and p[0] == "handle":
            return self.handle_lookup(p[1])
        if p == ["me"]:
            return self.me()
        if p == ["gmcat", "start"]:
            return self.gmcat_start(one("mode"))
        if p == ["gmcat", "return"]:
            return self.gmcat_return(one("state"), one("code"))
        if p == ["wallet", "challenge"]:
            return self.wallet_challenge()
        if p == ["plus", "names", "check"]:
            return self.name_check(one("name"))
        if len(p) == 4 and p[:2] == ["plus", "links"] and p[3] == "stats":
            return self.stats(p[2])
        if len(p) == 3 and p[:2] == ["plus", "buy"]:
            return self.buy_status(p[2])
        if p == ["admin", "overview"]:
            return self.admin_overview()
        if len(p) == 3 and p[0] == "l" and p[2] == "upgrades":
            return self.upgrades(p[1])
        if len(p) == 3 and p[0] == "l" and p[2] == "stats":
            return self.link_stats(p[1])
        if len(p) == 3 and p[0] == "l" and p[2] == "name-check":
            return self.link_name_check(p[1], one("name"))
        if len(p) == 2 and p[0] == "orders":
            return self.order_status(p[1])
        self.error(404, "Not found.")

    def do_POST(self):
        parts, q = self.parts()
        if parts == ["api", "gmcat", "event"]:
            return self.gmcat_event()
        if parts[:2] != ["api", "tiny"]:
            return self.error(404, "Not found.")
        if not self.same_origin():
            return self.error(403, "Not allowed.")
        p = parts[2:]
        try:
            if p == ["links"]:
                return self.create()
            if len(p) == 3 and p[0] == "l" and p[2] == "report":
                return self.report(p[1])
            if len(p) == 3 and p[0] == "l" and p[2] == "upgrade":
                return self.order(p[1])
            if len(p) == 4 and p[0] == "l" and p[2:] == ["claim", "challenge"]:
                return self.claim_challenge(p[1])
            if len(p) == 3 and p[0] == "l" and p[2] == "claim":
                return self.claim(p[1])
            if len(p) == 3 and p[0] == "l" and p[2] == "rekey":
                return self.rekey(p[1])
            if p == ["wallet", "verify"]:
                return self.wallet_verify()
            if p == ["plus", "links"]:
                return self.plus_save(None)
            if p == ["plus", "verify", "challenge"]:
                return self.verify_challenge()
            if p == ["plus", "verify"]:
                return self.verify_done()
            if p == ["plus", "buy"]:
                return self.buy()
            if len(p) == 2 and p[0] == "admin":
                return self.admin_action(p[1])
        except ValueError:
            return self.error(400, "That request didn't look right.")
        self.error(404, "Not found.")

    def do_PUT(self):
        parts, _ = self.parts()
        if len(parts) == 5 and parts[:4] == ["api", "tiny", "plus", "links"] and self.same_origin():
            try:
                return self.plus_save(parts[4])
            except ValueError:
                return self.error(400, "That request didn't look right.")
        if len(parts) == 4 and parts[:3] == ["api", "tiny", "l"] and self.same_origin():
            try:
                return self.owner_save(parts[3])
            except ValueError:
                return self.error(400, "That request didn't look right.")
        self.error(404, "Not found.")

    def do_DELETE(self):
        parts, _ = self.parts()
        if not self.same_origin():
            return self.error(403, "Not allowed.")
        if parts == ["api", "tiny", "session"]:
            return self.sign_out()
        if len(parts) == 4 and parts[:3] == ["api", "tiny", "l"]:
            return self.delete_free(parts[3])
        if len(parts) == 5 and parts[:4] == ["api", "tiny", "plus", "links"]:
            return self.plus_delete(parts[4])
        self.error(404, "Not found.")

    # ---- free links
    def config(self):
        with db() as con:
            s = settings(con)
            acct = self.session(con)
        prem = s["premium"]
        out = {"premium": prem, "teaser": s["teaser"] == "1", "coins": [dict(id=c, **coins.COINS[c]) for c in coins.ORDER],
               "keep": list(KEEP), "inuse_days": INUSE_DAYS, "signed_in": bool(acct), "free": s["free"], "privacy": s["privacy"], "avatars": AVATARS, "max_items": MAX_ITEMS,
               "gmgm_discount": int(float(s["gmgm_discount"] or 0))}
        if prem != "off":
            can_pay = prem == "on" and PAY.ready()
            out.update(sign_in={"gmcat": bool(CONNECT), "email": bool(CONNECT), "wallet": bool(CONNECT)},
                       prices={"plus": price(s, "plus_usd"), "name3": price(s, "name_usd_3"), "name4": price(s, "name_usd_4"),
                               "name5": price(s, "name_usd_5")},
                       can_buy=can_pay and price(s, "plus_usd") > 0, avatars=AVATARS, max_items=MAX_ITEMS,
                       manage=(CONNECT or {}).get("manage", "https://account.gmcat.io/profile/"))
        self.send_json(200, out)

    def create(self):
        with db() as con:
            if settings(con)["free"] != "on":   # the Free tier switch in the admin dashboard: existing links keep working
                return self.error(503, "Making new free links is paused for a little while. Links that already exist still work.")
        if self.limited("create"):
            return self.error(429, "You've made a lot of links this hour. Please wait a little and try again.")
        d = self.read_json()
        keep = d.get("keep")
        if keep not in KEEP:
            return self.error(400, "Choose how long to keep the link.")
        try:
            item = clean_item(d)
        except ValueError as ex:
            return self.error(400, str(ex))
        key = sha("|".join([item["coin"], item.get("handle") or item["address"], item.get("amount", ""), item.get("memo", "")]))
        t = now()
        with DB_LOCK, db() as con:
            row = con.execute("SELECT * FROM links WHERE dedupe = ? AND owner IS NULL AND (expires IS NULL OR expires > ?)", (key, t)).fetchone()
            if row:
                if row["held"]:
                    return self.error(451, "A link for this address was hidden after reports and is waiting for review.")
                # the existing link is kept at least as long as this request asked (never shorter)
                mode, expires = row["mode"], row["expires"]
                if mode == "inuse" or keep == "inuse":
                    mode, expires = "inuse", max(expires, t + KEEP["inuse"])
                else:
                    mode, expires = max(mode, keep, key=KEEP_RANK.get), max(expires, t + KEEP[keep])
                con.execute("UPDATE links SET mode = ?, expires = ?, updated = ? WHERE code = ?", (mode, expires, t, row["code"]))
                bump(con, "deduped")
                return self.send_json(200, {"code": row["code"], "link": LINK_BASE + row["code"], "mode": mode, "expires": expires,
                                            "existing": True, "inuse_days": INUSE_DAYS})
            while True:
                code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
                if not con.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone():
                    break
            token = secrets.token_urlsafe(18)
            expires = t + KEEP[keep]
            con.execute("INSERT INTO links (code, mode, created, updated, expires, last_visit, dedupe, delete_hash, items) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (code, keep, t, t, expires, t, key, sha(token), json.dumps([item], ensure_ascii=False)))
            bump(con, "created")
        self.send_json(201, {"code": code, "link": LINK_BASE + code, "mode": keep, "expires": expires, "delete_token": token, "owner_key": token,
                             "existing": False, "inuse_days": INUSE_DAYS})

    def view(self, code, count=True):
        if self.limited("miss", record=False):
            return self.error(429, "Too many wrong links. Please wait a while and try again.")
        t = now()
        with DB_LOCK, db() as con:
            row = self.live(con, code)
            if not row:
                self.limited("miss")
                return self.error(404, "This link doesn't exist. It may have expired or been deleted.")
            if row["held"]:
                return self.error(451, "This link was hidden after reports and is waiting for review.")
            acct = self.session(con)
            code = row["code"]   # (an @name may point at a Privacy Plus link)
            mine = bool(acct and row["owner"] == acct["ref"]) or self.owner_key_ok(row)
            if not mine and count:   # overlays (nc=1) and the owner's own looks don't count
                expires = row["expires"]
                if row["mode"] == "inuse" and t - row["last_visit"] > 3600:
                    expires = max(expires or 0, t + INUSE_DAYS * DAY)
                con.execute("UPDATE links SET visits = visits + 1, last_visit = ?, expires = ? WHERE code = ?", (t, expires, code))
                if row["owner"] or has(row, "stats"):
                    con.execute("INSERT INTO daily (code, day, n) VALUES (?, ?, 1) ON CONFLICT(code, day) DO UPDATE SET n = n + 1", (code, t // DAY))
                bump(con, "visits")
            row = con.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
            out = self.link_json(row, owner_view=mine)
            if mine and not row["owner"]:
                out["names"] = [dict(r) for r in con.execute("SELECT name, until FROM names WHERE owner = ?", ("link:" + code,))]
        self.send_json(200, out)

    def delete_free(self, code):
        with DB_LOCK, db() as con:
            row = self.live(con, code)
            if not self.owner_key_ok(row):
                return self.error(403, "This can't delete that link.")
            code = row["code"]
            remove_link(con, code)
            bump(con, "deleted")
        self.send_json(200, {"ok": True})

    def report(self, code):
        if self.limited("report"):
            return self.error(429, "Thanks, we have your reports. Please wait a while before sending more.")
        d = self.read_json()
        reason = d.get("reason")
        if reason not in REASONS:
            return self.error(400, "Choose a reason.")
        with DB_LOCK, db() as con:
            row = self.live(con, code)
            if not row:
                return self.error(404, "This link doesn't exist any more.")
            vis = self.visitor()
            if not con.execute("SELECT 1 FROM reports WHERE code = ? AND visitor = ? AND open = 1", (code, vis)).fetchone():
                con.execute("INSERT INTO reports (code, created, reason, details, visitor) VALUES (?, ?, ?, ?, ?)",
                            (code, now(), reason, clean_text(d.get("details"), 1500), vis))
            people = con.execute("SELECT COUNT(DISTINCT visitor) FROM reports WHERE code = ? AND open = 1", (code,)).fetchone()[0]
            if people >= REPORTS_TO_HIDE and not row["held"]:
                con.execute("UPDATE links SET held = 1 WHERE code = ?", (code,))
            bump(con, "reports")
        self.send_json(200, {"ok": True})

    def handle_lookup(self, name):
        if self.limited("handle"):
            return self.error(429, "That's a lot of lookups. Please wait a little.")
        h = "$" + name.lower().lstrip("$")
        if not coins.HANDLE_RE.match(h):
            return self.error(400, "That doesn't look like a $handle.")
        addr = resolve_handle(h)
        if not addr:
            return self.error(404, "We couldn't find %s." % h)
        self.send_json(200, {"handle": h, "address": addr})

    # ---- accounts
    def premium(self, con):
        return settings(con)["premium"]

    def me(self):
        with db() as con:
            acct = self.session(con)
            if not acct:
                return self.send_json(200, {"signed_in": False})
            links = [self.link_json(r, owner_view=True, fresh=False) for r in
                     con.execute("SELECT * FROM links WHERE owner = ? ORDER BY created DESC", (acct["ref"],))]
            names = [{"name": r["name"], "until": r["until"], "grace_until": r["until"] + NAME_GRACE_DAYS * DAY, "used": bool(
                con.execute("SELECT 1 FROM links WHERE code = ?", ("@" + r["name"],)).fetchone())}
                for r in con.execute("SELECT * FROM names WHERE owner = ? ORDER BY name", (acct["ref"],))]
            quotes = [dict(r) for r in con.execute("SELECT id, product, name, usd, amount, address, expires, status FROM quotes WHERE ref = ? AND status = 'open' AND expires > ? ORDER BY created DESC",
                                                    (acct["ref"], now()))]
            via = con.execute("SELECT via FROM sessions WHERE token_hash = ?", (sha(self.cookie("tiny_s")),)).fetchone()
        self.send_json(200, {"signed_in": True, "label": acct["label"], "via": via["via"] if via else "", "plus": plus_active(acct),
                             "plus_until": acct["plus_until"] or None, "links": links, "names": names, "open_quotes": quotes,
                             "name_grace_days": NAME_GRACE_DAYS, "inuse_days": INUSE_DAYS})

    def sign_out(self):
        tok = self.cookie("tiny_s")
        with DB_LOCK, db() as con:
            if tok:
                con.execute("DELETE FROM sessions WHERE token_hash = ?", (sha(tok),))
        self.send_json(200, {"ok": True}, cookies=[self.make_cookie("tiny_s", "", 0)])

    def gmcat_start(self, mode):
        with db() as con:
            prem = self.premium(con)
        if prem == "off" or not CONNECT:
            return self.redirect("/plus/#signin-error=off")
        state = secrets.token_urlsafe(24)
        CHALLENGES["c:" + state] = {"expires": now() + 600}
        q = {"client": "tiny", "state": state, "return": CONNECT["return"]}
        if mode == "email":
            q["lite"] = "1"
        self.redirect(CONNECT["authorize"] + "?" + urllib.parse.urlencode(q), [self.make_cookie("tiny_connect", state, 600, "/api/tiny/gmcat")])

    def gmcat_return(self, state, code):
        clear = self.make_cookie("tiny_connect", "", 0, "/api/tiny/gmcat")
        sorry = lambda why: self.redirect("/plus/#signin-error=" + why, [clear])
        if not CONNECT:
            return sorry("off")
        c = CHALLENGES.pop("c:" + state, None) if state else None
        if not c or c["expires"] < now() or self.cookie("tiny_connect") != state:
            return sorry("expired")
        if len(code) < 20:
            return sorry("cancelled")
        status, d = call(CONNECT["api"], CONNECT["secret"], "POST", "/api/connect/exchange", {"client": "tiny", "code": code})
        ref = str(d.get("account_ref") or "")
        if status != 200 or not REF_RE.match(ref):
            return sorry("failed" if status else "unreachable")
        with DB_LOCK, db() as con:
            cookie = self.start_session(con, ref, d.get("name") or "", "gmcat")
        self.redirect("/plus/", [clear, cookie])

    def wallet_challenge(self):
        with db() as con:
            if self.premium(con) == "off" or not CONNECT:
                return self.error(403, "Signing in isn't open yet.")
        if len(CHALLENGES) > 5000:
            return self.error(429, "Busy right now. Please try again in a minute.")
        nonce = secrets.token_urlsafe(16)
        msg = "Sign in to TinyADA (tiny.gmcat.io).\nThis is not a transaction: it sends nothing and costs nothing.\nCode: " + nonce
        CHALLENGES["w:" + nonce] = {"expires": now() + 600, "message": msg}
        self.send_json(200, {"nonce": nonce, "message": msg})

    def wallet_verify(self):
        if self.limited("signin"):
            return self.error(429, "Too many sign-in attempts. Please wait a little.")
        d = self.read_json(20000)
        c = CHALLENGES.pop("w:" + str(d.get("nonce") or ""), None)
        if not c or c["expires"] < now() or not CONNECT:
            return self.error(400, "That sign-in request ran out. Please try again.")
        status, a = call(CONNECT["api"], CONNECT["secret"], "POST", "/api/connect/wallet/sign-in",
                         {"client": "tiny", "provider": str(d.get("provider") or "")[:32], "address": d.get("address"),
                          "message": c["message"], "signature": d.get("signature"), "key": d.get("key")}, timeout=6)
        if status in (400, 403):
            return self.error(400, "Your wallet's signature didn't check out. Please try again.")
        ref = str(a.get("account_ref") or "")
        if status != 200 or not REF_RE.match(ref):
            return self.error(503, "GmCat accounts can't be reached right now. Please try again soon.")
        w = str(a.get("wallet") or "")
        with DB_LOCK, db() as con:
            cookie = self.start_session(con, ref, (w[:10] + "…" + w[-5:]) if w else "", "wallet")
        self.send_json(201, {"ok": True}, cookies=[cookie])

    def gmcat_event(self):
        if not CONNECT or self.headers.get("X-Real-IP") or self.headers.get("X-Forwarded-For"):
            return self.error(404, "Not found.")
        auth = self.headers.get("Authorization", "")
        given = auth[7:] if auth.startswith("Bearer ") else ""
        if not given or not hmac.compare_digest(sha(given), sha(CONNECT["secret"])):
            return self.error(401, "unauthorized")
        try:
            d = self.read_json(2000)
        except ValueError:
            return self.error(400, "bad request")
        ref, event = str(d.get("account_ref") or ""), str(d.get("event") or "")
        if not REF_RE.match(ref) or event not in ("summary", "disconnected", "account-deleted"):
            return self.error(400, "bad request")
        with DB_LOCK, db() as con:
            acct = con.execute("SELECT * FROM accounts WHERE ref = ?", (ref,)).fetchone()
            if event == "summary":
                n = con.execute("SELECT COUNT(*) FROM links WHERE owner = ?", (ref,)).fetchone()[0]
                return self.send_json(200, {"ok": True, "entries": n, "plus": plus_active(acct)})
            if event == "account-deleted":
                forget_account(con, ref)
            else:
                con.execute("DELETE FROM sessions WHERE ref = ?", (ref,))
        self.send_json(200, {"ok": True, "erased": event == "account-deleted" and bool(acct)})

    # ---- Plus
    def need_plus(self, con, buying=False):
        """-> (account, None) or (None, (status, message))."""
        prem = self.premium(con)
        if prem == "off":
            return None, (403, "TinyADA Plus isn't open yet.")
        acct = self.session(con)
        if not acct:
            return None, (401, "Please sign in first.")
        if not buying and not plus_active(acct):
            return None, (402, "This needs TinyADA Plus.")
        return acct, None

    def plus_save(self, code):
        if self.limited("edit"):
            return self.error(429, "That's a lot of saves. Please wait a little.")
        d = self.read_json(20000)
        t = now()
        try:
            items, title, bio, avatar, socials = read_content(d)
        except ValueError as ex:
            return self.error(400, str(ex))
        with DB_LOCK, db() as con:
            acct, bad = self.need_plus(con)
            if bad:
                return self.error(*bad)
            if code is None:
                name = str(d.get("name") or "").lower().lstrip("@")
                if name:
                    nrow = con.execute("SELECT * FROM names WHERE name = ?", (name,)).fetchone()
                    if not nrow or nrow["owner"] != acct["ref"]:
                        return self.error(403, "You don't own the name @%s." % name)
                    code = "@" + name
                    if con.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone():
                        return self.error(409, "@%s already has a page. Edit that one instead." % name)
                else:
                    if con.execute("SELECT COUNT(*) FROM links WHERE owner = ?", (acct["ref"],)).fetchone()[0] >= 200:
                        return self.error(429, "That's the most links one account can hold. Delete some first.")
                    while True:
                        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
                        if not con.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone():
                            break
                con.execute("INSERT INTO links (code, owner, mode, created, updated, expires, last_visit, items, title, bio, avatar, socials)"
                            " VALUES (?, ?, 'forever', ?, ?, NULL, ?, ?, ?, ?, ?, ?)",
                            (code, acct["ref"], t, t, t, json.dumps(items, ensure_ascii=False), title, bio, avatar, json.dumps(socials, ensure_ascii=False)))
                bump(con, "plus_created")
                status = 201
            else:
                row = con.execute("SELECT * FROM links WHERE code = ? AND owner = ?", (code, acct["ref"])).fetchone()
                if not row:
                    return self.error(404, "That isn't one of your links.")
                if row["held"]:
                    return self.error(451, "This link is hidden while it's reviewed.")
                apply_edit(con, row, items, title, bio, avatar, socials, ", mode = 'forever', expires = NULL")
                bump(con, "plus_edits")
                status = 200
            row = con.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
        self.send_json(status, self.link_json(row, owner_view=True, fresh=False))

    def plus_delete(self, code):
        with DB_LOCK, db() as con:
            acct = self.session(con)
            if not acct:
                return self.error(401, "Please sign in first.")
            if not con.execute("SELECT 1 FROM links WHERE code = ? AND owner = ?", (code, acct["ref"])).fetchone():
                return self.error(404, "That isn't one of your links.")
            remove_link(con, code)
            bump(con, "plus_deleted")
        self.send_json(200, {"ok": True})

    def stats(self, code):
        with db() as con:
            acct, bad = self.need_plus(con)
            if bad:
                return self.error(*bad)
            row = con.execute("SELECT * FROM links WHERE code = ? AND owner = ?", (code, acct["ref"])).fetchone()
            if not row:
                return self.error(404, "That isn't one of your links.")
            today = now() // DAY
            counts = {r["day"]: r["n"] for r in con.execute("SELECT day, n FROM daily WHERE code = ? AND day > ?", (code, today - 60))}
        self.send_json(200, {"code": code, "total": row["visits"], "days": [{"day": (today - i) * DAY, "n": counts.get(today - i, 0)} for i in range(59, -1, -1)]})

    def verify_challenge(self):
        if self.limited("verify"):
            return self.error(429, "That's a lot of tries. Please wait a little.")
        d = self.read_json()
        code, addr = str(d.get("code") or ""), str(d.get("address") or "")
        with db() as con:
            acct, bad = self.need_plus(con)
            if bad:
                return self.error(*bad)
            row = con.execute("SELECT * FROM links WHERE code = ? AND owner = ?", (code, acct["ref"])).fetchone()
        if not row or addr not in {it["address"] for it in json.loads(row["items"])}:
            return self.error(404, "That address isn't on this link.")
        raw = coins.payment_bytes(addr)
        if not raw or raw[0] >> 4 not in (0, 2, 4, 6):
            return self.error(400, "Only Cardano addr1… addresses with a normal (key) wallet can be verified for now.")
        nonce = secrets.token_urlsafe(16)
        msg = ("TinyADA: I own this address and I'm adding it to %s%s.\nThis is not a transaction: it sends nothing and costs nothing.\nCode: %s"
               % (LINK_BASE.replace("https://", ""), code, nonce))
        CHALLENGES["v:" + nonce] = {"expires": now() + 600, "message": msg, "code": code, "address": addr, "ref": acct["ref"]}
        self.send_json(200, {"nonce": nonce, "message": msg, "address_hex": raw.hex()})

    def verify_done(self):
        if self.limited("verify"):
            return self.error(429, "That's a lot of tries. Please wait a little.")
        d = self.read_json(20000)
        c = CHALLENGES.pop("v:" + str(d.get("nonce") or ""), None)
        if not c or c["expires"] < now():
            return self.error(400, "That request ran out. Please try again.")
        try:
            cose.verify_owner(str(d.get("signature") or ""), str(d.get("key") or ""), c["message"], coins.payment_bytes(c["address"]))
        except ValueError as ex:
            return self.error(400, "The signature didn't check out (%s). Make sure the wallet holding this address signs." % ex)
        with DB_LOCK, db() as con:
            acct = self.session(con)
            row = con.execute("SELECT * FROM links WHERE code = ? AND owner = ?", (c["code"], c["ref"])).fetchone()
            if not acct or acct["ref"] != c["ref"] or not row:
                return self.error(403, "Please sign in again.")
            v = set(json.loads(row["verified"]))
            v.add(c["address"])
            con.execute("UPDATE links SET verified = ? WHERE code = ?", (json.dumps(sorted(v)), c["code"]))
            bump(con, "verified")
            row = con.execute("SELECT * FROM links WHERE code = ?", (c["code"],)).fetchone()
        self.send_json(200, self.link_json(row, owner_view=True, fresh=False))

    def name_status(self, con, name, ref):
        """-> (ok, reason, price)"""
        if not NAME_RE.match(name):
            return False, "Names are 3 to 20 letters, numbers, - or _, starting and ending with a letter or number.", 0
        if name in RESERVED or name.startswith("gmcat"):
            return False, "That name is kept for GmCat.", 0
        row = con.execute("SELECT owner FROM names WHERE name = ?", (name,)).fetchone()
        if row:
            return (False, "You already own @%s." % name, 0) if row["owner"] == ref else (False, "@%s is taken." % name, 0)
        if con.execute("SELECT 1 FROM quotes WHERE name = ? AND status = 'open' AND expires > ? AND ref != ?", (name, now(), ref)).fetchone():
            return False, "Someone is buying @%s right now." % name, 0
        if con.execute("SELECT 1 FROM orders WHERE name = ? AND status = 'open' AND expires > ? AND 'link:' || code != ?", (name, now(), ref)).fetchone():
            return False, "Someone is buying @%s right now." % name, 0
        p = name_price(settings(con), name)
        return True, "", p

    def name_check(self, name):
        if self.limited("name"):
            return self.error(429, "That's a lot of checks. Please wait a little.")
        name = name.lower().lstrip("@").strip()
        with db() as con:
            acct, bad = self.need_plus(con, buying=True)
            if bad:
                return self.error(*bad)
            ok, why, p = self.name_status(con, name, acct["ref"])
        self.send_json(200, {"name": name, "available": ok, "reason": why, "usd": p})

    def buy(self):
        if self.limited("buy"):
            return self.error(429, "You've asked for several payment requests already. Please try again later.")
        d = self.read_json()
        product = d.get("product")
        with DB_LOCK, db() as con:
            acct, bad = self.need_plus(con, buying=True)
            if bad:
                return self.error(*bad)
            s = settings(con)
            if s["premium"] != "on" or not PAY.ready():
                return self.error(503, "Buying isn't switched on yet.")
            name = ""
            if product == "plus":
                usd = price(s, "plus_usd")
            elif product == "name":
                if not plus_active(acct):
                    return self.error(402, "Custom names need TinyADA Plus first.")
                name = str(d.get("name") or "").lower().lstrip("@")
                own = con.execute("SELECT owner FROM names WHERE name = ?", (name,)).fetchone()
                if own and own["owner"] == acct["ref"]:
                    usd = name_price(s, name)          # renewing a name you own
                else:
                    ok, why, usd = self.name_status(con, name, acct["ref"])
                    if not ok:
                        return self.error(409, why)
            else:
                return self.error(400, "Choose what to buy.")
            if usd <= 0:
                return self.error(503, "This doesn't have a price yet.")
        order, why = PAY.create("tiny-" + acct["ref"], usd)
        if not order:
            return self.error(503, why)
        opt = order["options"][0]
        with DB_LOCK, db() as con:
            con.execute("INSERT INTO quotes (id, ref, product, name, usd, amount, address, created, expires) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (order["id"], acct["ref"], product, name, usd, int(opt["amount"]), opt["address"], now(), order["expires"]))
            bump(con, "quotes")
        self.send_json(201, {"id": order["id"], "product": product, "name": name, "usd": usd, "amount": int(opt["amount"]), "address": opt["address"],
                             "expires": order["expires"], "options": order["options"]})

    def buy_status(self, qid):
        with db() as con:
            acct = self.session(con)
            q = con.execute("SELECT * FROM quotes WHERE id = ?", (qid,)).fetchone()
            if not acct or not q or q["ref"] != acct["ref"]:
                return self.error(404, "Not found.")
        st = q["status"]
        if st == "open" and PAY.ready():
            st = check_quote(qid) or st
        with db() as con:
            q = con.execute("SELECT * FROM quotes WHERE id = ?", (qid,)).fetchone()
        self.send_json(200, {"id": qid, "status": q["status"] if q["status"] != "open" else (st if st in ("late",) else "open"),
                             "product": q["product"], "name": q["name"], "expires": q["expires"]})

    # ---- Privacy Plus: one link's upgrades, no account
    def privacy_mode(self, con):
        return settings(con)["privacy"]

    def upgrades(self, code):
        """What can be bought for this link, at what price, and until when each runs now."""
        with db() as con:
            s = settings(con)
            row = self.live(con, code)
            if not row:
                return self.error(404, "This link doesn't exist any more.")
            if s["privacy"] == "off" or row["owner"]:
                return self.send_json(200, {"open": False})
            f, mine = feats(row), self.owner_key_ok(row)
            out = []
            for k, u in UPGRADES.items():
                out.append({"id": k, "label": u["label"], "about": u["about"], "owner_only": u["owner"],
                            "usd": price(s, u["price"]) if u["price"] else None, "until": f.get(k) if f.get(k, 0) > now() else None})
            names = [dict(r) for r in con.execute("SELECT name, until FROM names WHERE owner = ?", ("link:" + row["code"],))] if mine else []
        self.send_json(200, {"open": True, "mode": s["privacy"], "can_buy": s["privacy"] == "on" and PAY.ready(), "owner": mine,
                             "discount": int(float(s["gmgm_discount"] or 0)), "upgrades": out, "names": names,
                             "name_prices": {"3": price(s, "name_usd_3"), "4": price(s, "name_usd_4"), "5": price(s, "name_usd_5")},
                             "claimable": [it["address"] for it in json.loads(row["items"]) if self.claim_kind(it["address"])]})

    def link_name_check(self, code, name):
        if self.limited("name"):
            return self.error(429, "That's a lot of checks. Please wait a little.")
        name = name.lower().lstrip("@").strip()
        with db() as con:
            row = self.live(con, code)
            if not self.owner_key_ok(row):
                return self.error(403, "Only the link's owner can choose its name.")
            ok, why, p = self.name_status(con, name, "link:" + row["code"])
        self.send_json(200, {"name": name, "available": ok, "reason": why, "usd": p})

    def order(self, code):
        """Start paying for an upgrade on one link."""
        if self.limited("order"):
            return self.error(429, "You've asked for several payment requests already. Please try again later.")
        d = self.read_json()
        up, name = str(d.get("upgrade") or ""), str(d.get("name") or "").lower().lstrip("@")
        with DB_LOCK, db() as con:
            s = settings(con)
            row = self.live(con, code)
            if not row or row["owner"]:
                return self.error(404, "This link can't be upgraded here.")
            if row["held"]:
                return self.error(451, "This link is hidden while it's reviewed.")
            if s["privacy"] != "on" or not PAY.ready():
                return self.error(503, "Upgrades aren't on sale yet.")
            if up not in UPGRADES:
                return self.error(400, "Choose an upgrade.")
            if UPGRADES[up]["owner"] and not self.owner_key_ok(row):
                return self.error(403, "Only the link's owner can buy this. Open the link on the device you made it on, or prove it with your wallet.")
            if up == "name":
                nrow = con.execute("SELECT owner FROM names WHERE name = ?", (name,)).fetchone()
                if nrow and nrow["owner"] == "link:" + row["code"]:
                    usd = name_price(s, name)   # renewing
                else:
                    ok, why, usd = self.name_status(con, name, "link:" + row["code"])
                    if not ok:
                        return self.error(409, why)
            else:
                usd = price(s, UPGRADES[up]["price"])
            if usd <= 0:
                return self.error(503, "This upgrade doesn't have a price yet.")
            code = row["code"]
        order, why = PAY.create("tinylink-" + code.replace("@", ""), usd)
        if not order:
            return self.error(503, why)
        with DB_LOCK, db() as con:
            con.execute("INSERT INTO orders (id, code, upgrade, name, usd, options, created, expires, provider) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (order["id"], code, up, name, usd, json.dumps(order["options"]), now(), order["expires"], PAY.name))
            bump(con, "pp_orders")
        self.send_json(201, {"id": order["id"], "upgrade": up, "name": name, "usd": usd, "expires": order["expires"], "options": order["options"],
                             "receipt": LINK_BASE + "receipt/" + order["id"]})

    def order_status(self, oid):
        """Anyone holding the order id (the private receipt) may ask; ids are long and random."""
        if not re.match(r"^[A-Za-z0-9_-]{8,80}$", oid):
            return self.error(404, "Not found.")
        with db() as con:
            o = con.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        if not o:
            return self.error(404, "Not found.")
        st = o["status"]
        if st == "open" and PAY.ready():
            st = check_order(oid) or st
            with db() as con:
                o = con.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
        self.send_json(200, {"id": oid, "status": o["status"] if o["status"] != "open" else ("late" if st == "late" else "open"),
                             "code": o["code"], "upgrade": o["upgrade"], "label": UPGRADES[o["upgrade"]]["label"], "name": o["name"], "usd": o["usd"],
                             "options": json.loads(o["options"]), "created": o["created"], "expires": o["expires"], "paid_at": o["paid_at"], "tx": o["tx"]})

    @staticmethod
    def claim_kind(addr):
        """Which wallets can sign for this address: 'cardano' (CIP-30 signData with a key address) or 'solana' (signMessage)."""
        raw = coins.payment_bytes(addr)
        if raw and raw[0] >> 4 in (0, 2, 4, 6):
            return "cardano"
        if coins.check("SOL", addr)[0] == addr and not addr.startswith("addr"):
            return "solana"
        return None

    def claim_challenge(self, code):
        if self.limited("claim"):
            return self.error(429, "That's a lot of tries. Please wait a little.")
        d = self.read_json()
        addr = str(d.get("address") or "")
        with db() as con:
            row = self.live(con, code)
            if not row or row["owner"]:
                return self.error(404, "This link can't be claimed here.")
            if addr not in {it["address"] for it in json.loads(row["items"])}:
                return self.error(404, "That address isn't on this link.")
            if settings(con)["privacy"] == "off":
                return self.error(403, "This isn't open yet.")
        kind = self.claim_kind(addr)
        if not kind:
            return self.error(400, "Wallet proof works for Cardano addr1… and Solana addresses for now. Use the owner key for this one.")
        nonce = secrets.token_urlsafe(16)
        msg = ("TinyADA: I hold this address and I'm taking charge of %s%s.\nThis is not a transaction: it sends nothing and costs nothing.\nCode: %s"
               % (LINK_BASE.replace("https://", ""), row["code"], nonce))
        CHALLENGES["k:" + nonce] = {"expires": now() + 600, "message": msg, "code": row["code"], "address": addr, "kind": kind}
        raw = coins.payment_bytes(addr)
        self.send_json(200, {"nonce": nonce, "message": msg, "kind": kind, "address_hex": raw.hex() if raw else ""})

    def claim(self, code):
        """The wallet always wins: whoever signs with an address on the link gets a fresh owner key (the old one stops
        working) and that address gets the Verified tick."""
        if self.limited("claim"):
            return self.error(429, "That's a lot of tries. Please wait a little.")
        d = self.read_json(20000)
        c = CHALLENGES.pop("k:" + str(d.get("nonce") or ""), None)
        if not c or c["expires"] < now():
            return self.error(400, "That request ran out. Please try again.")
        try:
            if c["kind"] == "cardano":
                cose.verify_owner(str(d.get("signature") or ""), str(d.get("key") or ""), c["message"], coins.payment_bytes(c["address"]))
            else:
                sig = bytes.fromhex(str(d.get("signature") or ""))
                pub = coins.b58decode(c["address"])
                if not pub or len(pub) != 32 or not cose.ed25519_verify(pub, c["message"].encode(), sig):
                    raise ValueError("invalid signature")
        except ValueError as ex:
            return self.error(400, "The signature didn't check out (%s). The wallet holding this address has to sign." % ex)
        token = secrets.token_urlsafe(18)
        with DB_LOCK, db() as con:
            row = con.execute("SELECT * FROM links WHERE code = ?", (c["code"],)).fetchone()
            if not row or c["address"] not in {it["address"] for it in json.loads(row["items"])}:
                return self.error(409, "The link changed meanwhile. Please try again.")
            v = set(json.loads(row["verified"]))
            v.add(c["address"])
            con.execute("UPDATE links SET delete_hash = ?, claimed = 1, verified = ? WHERE code = ?", (sha(token), json.dumps(sorted(v)), c["code"]))
            bump(con, "claims")
        self.send_json(200, {"ok": True, "code": c["code"], "owner_key": token})

    def rekey(self, code):
        """A new owner key for the owner (if the old one may have leaked); the old one stops working."""
        with DB_LOCK, db() as con:
            row = self.live(con, code)
            if not self.owner_key_ok(row):
                return self.error(403, "That owner key doesn't match.")
            token = secrets.token_urlsafe(18)
            con.execute("UPDATE links SET delete_hash = ? WHERE code = ?", (sha(token), row["code"]))
        self.send_json(200, {"ok": True, "owner_key": token})

    def owner_save(self, code):
        """Edit a no-account link with its owner key. Needs the Tip page upgrade."""
        if self.limited("edit"):
            return self.error(429, "That's a lot of saves. Please wait a little.")
        d = self.read_json(20000)
        try:
            items, title, bio, avatar, socials = read_content(d)
        except ValueError as ex:
            return self.error(400, str(ex))
        with DB_LOCK, db() as con:
            row = self.live(con, code)
            if not self.owner_key_ok(row):
                return self.error(403, "That owner key doesn't match.")
            if row["held"]:
                return self.error(451, "This link is hidden while it's reviewed.")
            if not has(row, "page"):
                return self.error(402, "Editing needs the Tip page upgrade.")
            apply_edit(con, row, items, title, bio, avatar, socials)
            bump(con, "pp_edits")
            row = con.execute("SELECT * FROM links WHERE code = ?", (row["code"],)).fetchone()
        self.send_json(200, self.link_json(row, owner_view=True, fresh=False))

    def link_stats(self, code):
        with db() as con:
            row = self.live(con, code)
            if not self.owner_key_ok(row):
                return self.error(403, "That owner key doesn't match.")
            if not has(row, "stats"):
                return self.error(402, "Visit counts need the Visit counts upgrade.")
            today = now() // DAY
            counts = {r["day"]: r["n"] for r in con.execute("SELECT day, n FROM daily WHERE code = ? AND day > ?", (row["code"], today - 60))}
        self.send_json(200, {"code": row["code"], "total": row["visits"], "days": [{"day": (today - i) * DAY, "n": counts.get(today - i, 0)} for i in range(59, -1, -1)]})

    # ---- admin
    def admin_overview(self):
        if not self.admin_ok():
            return self.error(403, "Not allowed.")
        t = now()
        with db() as con:
            one = lambda sql, *a: con.execute(sql, a).fetchone()[0]
            reports = [dict(r) for r in con.execute(
                "SELECT r.id, r.code, r.created, r.reason, r.details, l.held, l.items, l.owner IS NOT NULL AS plus FROM reports r "
                "JOIN links l ON l.code = r.code WHERE r.open = 1 ORDER BY r.created DESC LIMIT 200")]
            for r in reports:
                r["reporters"] = one("SELECT COUNT(DISTINCT visitor) FROM reports WHERE code = ? AND open = 1", r["code"])
                r["items"] = [{"coin": i["coin"], "address": i["address"], "handle": i.get("handle")} for i in json.loads(r["items"])]
            accounts = [dict(r, links=one("SELECT COUNT(*) FROM links WHERE owner = ?", r["ref"])) for r in
                        con.execute("SELECT ref, label, created, seen, plus_until FROM accounts ORDER BY seen DESC LIMIT 100")]
            for a in accounts:
                a["names"] = [r[0] for r in con.execute("SELECT name FROM names WHERE owner = ?", (a["ref"],))]
            self.send_json(200, {
                "free_links": one("SELECT COUNT(*) FROM links WHERE owner IS NULL"),
                "plus_links": one("SELECT COUNT(*) FROM links WHERE owner IS NOT NULL"),
                "inuse_links": one("SELECT COUNT(*) FROM links WHERE mode = 'inuse'"),
                "held": one("SELECT COUNT(*) FROM links WHERE held = 1"),
                "accounts": one("SELECT COUNT(*) FROM accounts"), "plus_accounts": one("SELECT COUNT(*) FROM accounts WHERE plus_until > ?", t),
                "names": one("SELECT COUNT(*) FROM names"),
                "db_bytes": (DATA / "tiny.db").stat().st_size if (DATA / "tiny.db").exists() else 0,
                "stats": {r["k"]: r["v"] for r in con.execute("SELECT k, v FROM stats")},
                "settings": settings(con), "connect": bool(CONNECT), "gmgm": bool(GMGM_SECRET),
                "wallets": [{"chain": c[0], "name": c[1], "symbol": c[2], "receives": c[3],
                             "address": (con.execute("SELECT address FROM wallets WHERE chain = ?", (c[0],)).fetchone() or [""])[0]} for c in coins.RECEIVE_CHAINS],
                "wallet_log": [dict(r) for r in con.execute("SELECT chain, old, new, at FROM wallet_log ORDER BY id DESC LIMIT 30")],
                "reports": reports, "accounts_list": accounts,
                "quotes": [dict(r) for r in con.execute("SELECT id, product, name, usd, amount, created, status, paid_at FROM quotes ORDER BY created DESC LIMIT 50")],
                "orders": [dict(r) for r in con.execute("SELECT id, code, upgrade, name, usd, created, status, paid_at FROM orders ORDER BY created DESC LIMIT 50")],
                "pp_links": one("SELECT COUNT(*) FROM links WHERE owner IS NULL AND features != '{}'"),
                "upgrades": {k: v["label"] for k, v in UPGRADES.items()}})

    def admin_action(self, action):
        if not self.admin_ok():
            return self.error(403, "Not allowed.")
        d = self.read_json()
        with DB_LOCK, db() as con:
            if action == "settings":
                for k in DEFAULTS:
                    if k not in d:
                        continue
                    v = str(d[k])
                    if k in ("premium", "privacy") and v not in ("off", "testing", "on"):
                        return self.error(400, "%s must be off, testing or on" % k)
                    if k == "free" and v not in ("off", "on"):
                        return self.error(400, "free must be on or off")
                    if k == "gmgm_discount":
                        try:
                            pct = int(float(v))
                        except ValueError:
                            return self.error(400, "The discount is a whole number of percent.")
                        if not 0 <= pct <= 90:
                            return self.error(400, "The discount must be between 0 and 90 percent.")
                        v = str(pct)
                    if k == "teaser":
                        v = "1" if v in ("1", "true", "True") else "0"
                    if k.endswith("_usd") or k.startswith("name_usd"):
                        try:
                            f = float(v)
                        except ValueError:
                            return self.error(400, "Prices are numbers in US dollars.")
                        if not 0 <= f <= 1000:
                            return self.error(400, "Prices must be between 0 and 1000 dollars.")
                        v = str(round(f, 2))
                    con.execute("INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, v))
                return self.send_json(200, {"ok": True, "settings": settings(con)})
            if action == "wallet":   # a receiving wallet for Privacy Plus payments: public address only, every change logged
                chain = str(d.get("chain") or "")
                if chain not in WALLET_CHAINS:
                    return self.error(400, "Unknown chain.")
                raw = coins.clean(d.get("address"))
                old = (con.execute("SELECT address FROM wallets WHERE chain = ?", (chain,)).fetchone() or [""])[0]
                if raw:
                    addr, why = WALLET_CHAINS[chain][4](raw)
                    if not addr:
                        return self.error(400, why)
                    con.execute("INSERT INTO wallets (chain, address, updated) VALUES (?, ?, ?) ON CONFLICT(chain) DO UPDATE SET address = excluded.address, updated = excluded.updated", (chain, addr, now()))
                else:
                    addr = ""
                    con.execute("DELETE FROM wallets WHERE chain = ?", (chain,))
                if addr != old:
                    con.execute("INSERT INTO wallet_log (chain, old, new, at) VALUES (?, ?, ?, ?)", (chain, old, addr, now()))
                return self.send_json(200, {"ok": True, "chain": chain, "address": addr})
            if action == "dismiss":
                con.execute("UPDATE reports SET open = 0 WHERE id = ?", (int(d.get("report") or 0),))
                return self.send_json(200, {"ok": True})
            if action == "gift":
                ref = str(d.get("ref") or "")
                try:
                    days = int(d.get("days"))
                except (TypeError, ValueError):
                    return self.error(400, "days must be a number")
                if not con.execute("SELECT 1 FROM accounts WHERE ref = ?", (ref,)).fetchone():
                    return self.error(404, "No such account.")
                if days > 0:
                    con.execute("UPDATE accounts SET plus_until = MAX(plus_until, ?) + ? WHERE ref = ?", (now(), days * DAY, ref))
                else:
                    con.execute("UPDATE accounts SET plus_until = 0 WHERE ref = ?", (ref,))
                return self.send_json(200, {"ok": True})
            if action == "grant":   # Privacy Plus upgrade on a link without payment (testing, gifts)
                code, up = str(d.get("code") or "").strip().lstrip("/"), str(d.get("upgrade") or "")
                code = code.split("tiny.gmcat.io/")[-1]
                row = con.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
                if not row or row["owner"]:
                    return self.error(404, "No such link (or it belongs to a Plus account).")
                if up not in UPGRADES:
                    return self.error(400, "Unknown upgrade.")
                name = str(d.get("name") or "").lower().lstrip("@")
                if up == "name":
                    ok, why, _ = self.name_status(con, name, "link:" + code)
                    if not ok and "already own" not in why:
                        return self.error(409, why)
                try:
                    days = max(1, min(3650, int(d.get("days") or 365)))
                except (TypeError, ValueError):
                    return self.error(400, "days must be a number")
                problem = apply_upgrade(con, code, up, name, days)
                if problem:
                    return self.error(409, problem)
                return self.send_json(200, {"ok": True})
            if action == "release-name":
                name = str(d.get("name") or "").lower().lstrip("@")
                remove_link(con, "@" + name)
                con.execute("DELETE FROM names WHERE name = ?", (name,))
                return self.send_json(200, {"ok": True})
            code = str(d.get("code") or "")
            if not con.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone():
                return self.error(404, "No such link.")
            if action == "hold":
                con.execute("UPDATE links SET held = 1 WHERE code = ?", (code,))
            elif action == "restore":
                con.execute("UPDATE links SET held = 0 WHERE code = ?", (code,))
                con.execute("UPDATE reports SET open = 0 WHERE code = ?", (code,))
            elif action == "delete":
                remove_link(con, code)
            else:
                return self.error(404, "Not found.")
        self.send_json(200, {"ok": True})

    # ---- dev only
    def dev_static(self, parts):
        root = Path(DEV_STATIC).resolve()
        rel = "/".join(parts)
        if len(parts) == 1 and LINK_RE.match(parts[0]):
            rel = "view/index.html"
        elif len(parts) == 2 and LINK_RE.match(parts[0]) and parts[1] == "overlay":
            rel = "overlay/index.html"
        elif len(parts) == 2 and parts[0] == "receipt":
            rel = "receipt/index.html"
        f = (root / rel).resolve()
        if f.is_dir():
            f = f / "index.html"
        if (root not in f.parents and f != root) or not f.is_file():
            f = root / "404.html"
        body = f.read_bytes()
        types = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".png": "image/png",
                 ".svg": "image/svg+xml", ".json": "application/json", ".webp": "image/webp", ".xml": "application/xml", ".txt": "text/plain"}
        self.send_response(200 if f.name != "404.html" else 404)
        self.send_header("Content-Type", types.get(f.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        csp = os.environ.get("TINY_DEV_CSP")
        if f.suffix == ".html" and csp:
            self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        self.wfile.write(body)


def main():
    global CONNECT
    CONNECT = load_connect()
    init()
    threading.Thread(target=loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    print("GmCat TinyADA on 127.0.0.1:%d, data in %s, sign-in %s, $GMGM %s" % (PORT, DATA, "on" if CONNECT else "off", "on" if GMGM_SECRET else "off"), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
