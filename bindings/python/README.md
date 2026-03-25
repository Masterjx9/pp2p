# Python SDK

This package is a ctypes bridge over the P4 Rust C ABI.

## Install

```bash
pip install p4_core
```

## Runtime requirements

- Python 3.9+
- Bundled native runtime targets:
  - Windows x64
  - Linux x64
  - macOS Intel (x64)
  - macOS Apple Silicon (arm64)

Overrides:
- `P4_CORE_LIB` for core native library path

## Example

```python
from p4_core import P4Core

core = P4Core()
alice = core.generate_identity()
bob = core.generate_identity()

env = core.sign_envelope(
    private_key_b64=alice["private_key_b64"],
    sender_peer_id=alice["peer_id"],
    recipient_peer_id=bob["peer_id"],
    payload={"type": "hello", "text": "hi"},
    nonce="n1",
)
core.verify_envelope(env, signer_public_key_b64=alice["public_key_b64"])
print("ok")
```


