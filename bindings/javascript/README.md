# JavaScript / TypeScript SDK

Node.js FFI wrapper for the P4 Rust core.

## Install

```bash
npm i @pythonicit/p4-core-sdk
```

## Runtime requirements

- Node.js 18+
- Bundled native runtime targets:
  - Windows x64
  - Linux x64
  - macOS Intel (x64)
  - macOS Apple Silicon (arm64)

Overrides:
- `P4_CORE_LIB` for core native library path

## Example

```javascript
const { P4Core } = require("@pythonicit/p4-core-sdk");

const core = new P4Core();
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
