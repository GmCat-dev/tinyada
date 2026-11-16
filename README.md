# TinyADA

Short links for crypto addresses: the code behind **[tiny.gmcat.io](https://tiny.gmcat.io/)**, a free tool from GmCat.

Paste an address (or a Cardano `$handle`) and get a link like `tiny.gmcat.io/k7f2qa` with a QR code. TinyADA first ran as
TinyADA.com in 2019 and came back in 2026 as part of the GmCat Toolbox.

## What it does
- **Typo protection:** every address is checked against its coin's built-in checksum before a link is made (Cardano
  Shelley and Byron, Bitcoin incl. bech32/bech32m, Ethereum EIP-55, Solana, Litecoin, Dogecoin). Same rules in the
  browser (`web/js/tiny-core.js`) and on the server (`server/coins.py`).
- **Ending check:** the link page shows the last characters big, to compare with the wallet (against address-swapping malware).
- **Payment requests:** amount + note as wallet links (CIP-13, BIP-21, EIP-681, Solana Pay).
- **Keep while in use:** free links can last 1, 7 or 30 days, or until 6 months pass without a visit. Same address = same link.
- **Owner keys and wallet proof:** a link's owner key is stored only as a SHA-256. The wallet holding the address can
  always take a link over by signing a message (Cardano CIP-30 `signData`, Solana `signMessage`): the wallet always wins.
- **Privacy:** no IP addresses stored (short-lived salted hashes in memory for rate limits only), no cookies for free links.

## Check us
The browser code that tiny.gmcat.io serves is the code in `web/js/` here, byte for byte. Compare it yourself:

    curl -s https://tiny.gmcat.io/js/tiny-core.js | sha256sum
    sha256sum web/js/tiny-core.js

## Run it
Python 3.8+ standard library only.

    cd server
    TINY_DATA=/tmp/tiny TINY_PORT=4299 TINY_COOKIE_SECURE=0 TINY_LINK_BASE=http://127.0.0.1:4299/ \
      TINY_DEV_STATIC=../web python3 server.py
    python3 test_server.py     # API tests (wallet-signature tests need: npm i @emurgo/cardano-serialization-lib-nodejs @emurgo/cardano-message-signing-nodejs)

`server/server.py` lists the whole API at the top. `server/payments.py` is the payment "socket": everything that costs
money goes through it, so you can plug in your own payment checker. `server/nginx-example.conf` shows the web server setup.

## Licence
- **AGPL-3.0** (see `LICENSE`): free to use, study, change and share. If you run a changed version as a website, you
  must offer your changes to its users under the same licence.
- **Commercial licence:** want to use TinyADA in a product without the AGPL's share-your-changes rule? See `COMMERCIAL.md`.

The TinyADA name, the //TinyADA logo and GmCat's artwork are not covered by the code licence.
Coin logo shapes on the site come from [Simple Icons](https://simpleicons.org) (CC0); the logos are their projects' trademarks, shown only to say which coins TinyADA supports.

## Security
Please report security problems privately: see `SECURITY.md`.
