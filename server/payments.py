"""TinyADA's payment socket.

Everything in TinyADA that costs money (Plus, custom names, Privacy Plus upgrades) asks THIS module for a payment request
and later asks whether it was paid. Nothing else in TinyADA knows how payments work, so GmCat Pay (the planned multi-coin
service, a separate multi-coin payment service) can be plugged in here later without touching the rest.

Today there is one provider: GmCat Drop's $GMGM checker ("partner quotes": one address + one exact amount, ~30 minutes).

A provider has:
    ready() -> bool
    create(ref, usd) -> (order, None) | (None, plain-language error)
        order = {"id", "expires", "options": [ {"coin", "label", "amount" (str), "address", "uri", "note", "discount"} ...]}
        Options are listed in the order to show them ($GMGM first). GmCat Pay will return many options (one per coin).
    status(order_id) -> "open" | "late" | "paid" | "expired" | "withdrawn" | None (couldn't ask), plus the tx id when paid
"""
import json
import re
import urllib.error
import urllib.request


def _call(base, secret, method, path, body=None, timeout=8):
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


class DropGmgm:
    """$GMGM through GmCat Drop's existing payment checker (exact amount on a shared address)."""
    name = "drop-gmgm"

    def __init__(self, api, secret, discount_pct=lambda: 0):
        self.api, self.secret, self.discount_pct = api, secret, discount_pct

    def ready(self):
        return bool(self.secret)

    def create(self, ref, usd):
        pct = max(0, min(90, int(self.discount_pct() or 0)))
        pay_usd = round(usd * (100 - pct) / 100, 2)
        status, q = _call(self.api, self.secret, "POST", "/api/partner/quotes", {"ref": re.sub(r"[^A-Za-z0-9_-]", "", ref)[:64], "usd": pay_usd})
        if status not in (200, 201):
            why = str(q.get("error") or "")
            return None, {"price_unavailable": "The $GMGM price isn't available right now. Please try again soon.",
                          "payments_off": "$GMGM payments are switched off right now.",
                          "too_many_open": "There are several open payment requests already. Use one of those, or wait for them to end.",
                          "bad_amount": "This price is too small or too big for a $GMGM payment."}.get(why) or "The payment checker can't be reached right now. Please try again soon."
        opt = {"coin": "GMGM", "label": "$GMGM", "amount": str(int(q["amount"])), "address": q["address"], "uri": "", "discount": pct,
               "usd": pay_usd, "note": "Send exactly this amount of $GMGM (a Cardano token). The exact amount is how we know it's you."}
        return {"id": q["id"], "expires": int(q["expires_at"]), "options": [opt]}, None

    def status(self, order_id):
        code, d = _call(self.api, self.secret, "GET", "/api/partner/quotes/" + urllib.request.quote(order_id, safe=""))
        if code != 200:
            return None, ""
        return d.get("status"), str(d.get("tx") or "")[:100]
