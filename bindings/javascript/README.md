# JavaScript / TypeScript SDK

Node.js FFI wrapper for the PP2P Rust core.

## Install

```bash
npm i @pythonicit/pp2p-core-sdk
```

## Runtime requirements

- Node.js 18+
- Native PP2P core library (`pp2p_core.dll` / `libpp2p_core.so` / `libpp2p_core.dylib`)

Build native library first:

From repo root:

```bash
./scripts/build_pp2p_core_unix.sh
```
or on Windows:
```powershell
.\scripts\build_pp2p_core.ps1
```

If the library is not in `dist/pp2p_core/...`, set `PP2P_CORE_LIB` to its absolute path.

## Example

```javascript
const { Pp2pCore } = require("./bindings/javascript/pp2p_core");

const core = new Pp2pCore();
const a = core.generateIdentity();
const b = core.generateIdentity();

const env = core.signEnvelope({
  privateKeyB64: a.private_key_b64,
  senderPeerId: a.peer_id,
  recipientPeerId: b.peer_id,
  payload: { type: "offer" },
  nonce: "n1",
});

core.verifyEnvelope({ envelope: env, signerPublicKeyB64: a.public_key_b64 });
console.log("ok");
```
