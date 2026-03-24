# Python SDK

This package is a ctypes bridge over the PP2P Rust C ABI.

## Install

```bash
pip install pp2p_core
```

## Runtime requirements

- Python 3.9+
- Native PP2P core library (`pp2p_core.dll` / `libpp2p_core.so` / `libpp2p_core.dylib`)

Build native library first:

Windows:
```powershell
.\scripts\build_pp2p_core.ps1
```

Linux/macOS:
```bash
./scripts/build_pp2p_core_unix.sh
```

If the library is not in `dist/pp2p_core/...`, set `PP2P_CORE_LIB` to its absolute path.

## Local dev install

```bash
pip install -e ./bindings/python
```

## Example

```python
from pp2p_core import Pp2pCore

core = Pp2pCore()
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
