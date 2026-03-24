# PP2P - Persistent P2P Protocol

PP2P keeps normal WebRTC P2P data channels and adds persistent onion rendezvous for rediscovery/reconnect after disconnect.

This repo is now structured as:
- Runtime prototype: `pp2p.py`
- Protocol crypto core: `rust/pp2p-core` + `rust/pp2p-ffi`
- Language SDK bindings: `bindings/`
- Onionrelay slim source/build tree: `tor_win_min_src/`

## What Is Complete

1. Two peers connect and exchange messages (WebRTC DataChannel).
2. Peer reconnect logic auto-runs after session drop.
3. Onion rendezvous identity persists (service ID + key blob in state dir).
4. `pp2p.py` identity/envelope crypto now calls Rust core via C ABI.
5. Multi-language SDK package scaffolds exist for Python, JS/TS, Java, C++, PHP.

## Protocol Flow

```text
   +------+        +----------------------------------+        +----------------------------------+
   | Dead |------->| Establish                        |------->| Authenticate                     |
   +------+   UP   | - direct/onion rendezvous select | OPENED | - verify pinned peer            |
      ^            | - signed SDP offer/answer        |        | - verify Ed25519 sig + nonce    |
      |            | - onion only for signaling       |        | - fail if trust check fails     |
      |            +----------------------------------+        +-------------------+--------------+
      |                         FAIL                                              SUCCESS/NONE |
      |                                                                                       |
      |            +----------------------------------+        CLOSING                        v
      +------------| Terminate                        |<--------------------------------+---------------+
           DOWN    | - close session / stop node      |                                 | Network       |
                   +----------------------------------+                                 | - WebRTC/ICE  |
                                                                                        | - DataChannel |
                                                                                        | - app traffic |
                                                                                        | - reconnect   |
                                                                                        |   -> Establish|
                                                                                        +---------------+
```

## Core Architecture

### Rust core
- `rust/pp2p-core`: identity + peer_id derivation + envelope sign/verify + replay primitive
- `rust/pp2p-ffi`: C ABI export surface
- `include/pp2p_core.h`: shared ABI contract

### Python runtime integration
`pp2p.py` uses `bindings/python/pp2p_core/` for:
- identity generation/loading
- envelope signing
- envelope verification

Legacy migration:
- old `identity_ed25519.pem` is auto-migrated to `identity_ed25519.json` on first run.

## Build Rust Core

Windows:
```powershell
.\scripts\build_pp2p_core.ps1
```

Linux/macOS:
```bash
./scripts/build_pp2p_core_unix.sh
```

Output:
- `dist/pp2p_core/windows-x64/pp2p_core.dll`
- `dist/pp2p_core/linux-x64/libpp2p_core.so`
- `dist/pp2p_core/macos/libpp2p_core.dylib`

## Runtime Quick Start (Windows)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Build Rust core + onionrelay subset
.\scripts\build_pp2p_core.ps1
.\build_tor_subset_windows.ps1
```

Initialize peers:
```powershell
.\.venv\Scripts\python.exe pp2p.py init --state-dir .\human_test\peerA
.\.venv\Scripts\python.exe pp2p.py init --state-dir .\human_test\peerB
```

Run peers:
```powershell
.\.venv\Scripts\python.exe pp2p.py run --state-dir .\human_test\peerA --mode onion --tor-bin .\tor_win_min_src\src\app\tor.exe
.\.venv\Scripts\python.exe pp2p.py run --state-dir .\human_test\peerB --mode onion --tor-bin .\tor_win_min_src\src\app\tor.exe
```

At `pp2p>` prompt:
- `/invite`
- `/add-file <invite.json>` or `/add-json <invite-json>`
- `/peers`
- `/send <peer_id> <text>`
- `/drop <peer_id>`

## SDK Packaging Layout

- Python package: `bindings/python/pyproject.toml`
- JavaScript package: `bindings/javascript/package.json`
- Java Maven module: `bindings/java/pom.xml`
- C++ CMake wrapper: `bindings/cpp/CMakeLists.txt`
- PHP Composer package (monorepo root for Packagist): `composer.json`

See `bindings/README.md`.

## SDK Install Commands

- Python: `pip install pp2p_core`
- Python (legacy compatibility name): `pip install pp2p-core-sdk` (installs `pp2p_core`)
- JavaScript/TypeScript: `npm i @pythonicit/pp2p-core-sdk`
- Java (Maven): `io.github.masterjx9:pp2p-core-sdk:0.1.0`
- PHP (Composer): `composer require masterjx9/pp2p-core-sdk`

## SDK Runtime Requirements

Python / JS SDKs:
- `pip install pp2p_core` and `npm i @pythonicit/pp2p-core-sdk` include bundled native binaries for:
  - Windows x64
  - Linux x64
  - macOS Intel (x64)
  - macOS Apple Silicon (arm64)

Java / PHP / C++ SDKs:
- Require explicit native library path for now (`PP2P_CORE_LIB` or constructor path).

Extra requirements for the Python `pp2p.py` runtime CLI:
- `pip install -r requirements.txt`
- Onion mode requires an `onionrelay`/Tor binary (`--tor-bin`), built from this repo subset.

## Registry Publishing

Maven Central namespace string used in this repo:
- `io.github.masterjx9`

GitHub Actions workflows:
- `.github/workflows/publish-python.yml`
- `.github/workflows/publish-npm.yml`
- `.github/workflows/publish-maven-central.yml`
- `.github/workflows/update-packagist.yml`

Required GitHub secrets:
- `PYPI_API_TOKEN`
- `MAVEN_CENTRAL_USERNAME`
- `MAVEN_CENTRAL_PASSWORD`
- `MAVEN_GPG_PRIVATE_KEY`
- `MAVEN_GPG_PASSPHRASE`
- `PACKAGIST_USERNAME`
- `PACKAGIST_ACCESS_TOKEN`

NPM workflow uses trusted publishing (OIDC), so no npm token secret is required.

## Onionrelay Build Pipeline (Unix)

Workflow:
- `.github/workflows/build-onionrelay-unix.yml`

Build script:
- `scripts/build_onionrelay_unix.sh`

Targets:
- Linux x86_64
- macOS Intel
- macOS Apple Silicon

## Rust Core Build Pipeline

Workflow:
- `.github/workflows/build-pp2p-core.yml`

Targets:
- Windows x64
- Linux x64
- macOS Intel
- macOS Apple Silicon

## Notes

- Onion is used for signaling/rendezvous persistence; media/data remains WebRTC.
- TURN is optional; STUN default is `stun:stun.l.google.com:19302`.
- If native core library is in a custom location, set `PP2P_CORE_LIB` env var.
