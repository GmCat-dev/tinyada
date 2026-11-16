// Test helper (TinyADA): a throwaway Cardano wallet signs a message with its RECEIVING (base) address, the way a CIP-30
// wallet's signData(paymentAddress, payload) does. Uses the same EMURGO libraries as the GmCat account service.
// Usage: node test_sign_payment.mjs '<message>' [privateKeyHex]  ->  {"address","signature","key","private"}
import { createRequire } from 'node:module';
const load = createRequire(import.meta.url), Cardano = load('@emurgo/cardano-serialization-lib-nodejs'), MS = load('@emurgo/cardano-message-signing-nodejs');
const [message, priv] = process.argv.slice(2);
const privateKey = priv ? Cardano.PrivateKey.from_normal_bytes(Buffer.from(priv, 'hex')) : Cardano.PrivateKey.generate_ed25519(), publicKey = privateKey.to_public();
const stakeKey = Cardano.PrivateKey.generate_ed25519().to_public();
const address = Cardano.BaseAddress.new(1, Cardano.Credential.from_keyhash(publicKey.hash()), Cardano.Credential.from_keyhash(stakeKey.hash())).to_address();
const pm = MS.HeaderMap.new(); pm.set_algorithm_id(MS.Label.from_algorithm_id(MS.AlgorithmId.EdDSA)); pm.set_header(MS.Label.new_text('address'), MS.CBORValue.new_bytes(Buffer.from(address.to_hex(), 'hex')));
const um = MS.HeaderMap.new(); um.set_header(MS.Label.new_text('hashed'), MS.CBORValue.new_special(MS.CBORSpecial.new_bool(false)));
const builder = MS.COSESign1Builder.new(MS.Headers.new(MS.ProtectedHeaderMap.new(pm), um), new TextEncoder().encode(message), false), signed = builder.build(privateKey.sign(builder.make_data_to_sign().to_bytes()).to_bytes());
const key = MS.COSEKey.new(MS.Label.from_key_type(MS.KeyType.OKP)); key.set_algorithm_id(MS.Label.from_algorithm_id(MS.AlgorithmId.EdDSA));
key.set_header(MS.Label.from_ec_key(MS.ECKey.CRV), MS.CBORValue.from_label(MS.Label.from_curve_type(MS.CurveType.Ed25519))); key.set_header(MS.Label.from_ec_key(MS.ECKey.X), MS.CBORValue.new_bytes(publicKey.as_bytes()));
console.log(JSON.stringify({ address: address.to_bech32('addr'), hex: address.to_hex(), signature: Buffer.from(signed.to_bytes()).toString('hex'), key: Buffer.from(key.to_bytes()).toString('hex'), private: Buffer.from(privateKey.as_bytes()).toString('hex') }));
