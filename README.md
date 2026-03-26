# P4 (Persistent Point-to-Point Protocol)

P4 keeps normal point-to-point data paths (WebRTC/DataChannel) and adds persistent rendezvous for rediscovery and automatic reconnect after disconnects.

This repository is a monorepo containing:
- Runtime reference CLI: `p4.py`
- Rust core + C ABI: `rust/p4-core`, `rust/p4-ffi`, `include/p4_core.h`
- SDK bindings: `bindings/`
- Minimal runtime transport source/build tree: `onionrelay_src/` (source builds only)

## Why P4

Use P4 when you want direct encrypted peer communication without making a central app server the permanent source of truth.

Example use cases:
- Personal file sync (Dropbox alternative)
- Password manager cross-device sync
- Notes/tasks syncing (offline-first apps)
- Home automation control (phone to local hub)
- Game state sync (local-host multiplayer)
- Camera/IoT monitoring without cloud
- Clipboard sharing between devices
- Local-first databases (CRDT peer sync)
- Encrypted chat without central servers
- Dev tools: logs/metrics between local machines

## Onion Relay Scope and Safety

- P4 uses OnionRelay only for peer rediscovery/rendezvous signaling when reconnecting.
- P4 does not route normal application payload traffic through relays; data stays on direct peer-to-peer channels whenever possible.
- The relay ecosystem is community-operated and decentralized.
- This project is for legitimate privacy-preserving communication and local-first sync use cases.
- This project is not for botnets, command-and-control, malware operations, abuse automation, unauthorized access, or any other nefarious activity.

If you want to support the onion relay ecosystem, you can run your own relay: https://community.torproject.org/relay/

`onionrelay_src` is built for this project with a minimal runtime configuration. The build disables non-required components with:
- `--disable-module-relay`
- `--disable-module-dirauth`
- `--disable-module-pow`
- `--disable-unittests`

This is important because:
- It only includes the onion relay functionality needed for P4's use case.
- It minimizes the attack surface of the relay component used by P4.
- It reduces binary/runtime footprint and keeps packaging lighter across SDKs.
- It lowers operational complexity by removing features not required for rendezvous signaling.

This is important because:
- It only includes the onion relay functionality needed for P4's use case.
- It minimizes the attack surface of the relay component used by P4.


## What Is Supported

Protocol/runtime support:
- Signed envelope identity/authentication via Rust core crypto
- Peer reconnect loop after channel drop
- Persistent rendezvous identity for rediscovery
- WebRTC DataChannel messaging
- STUN by default (`stun:stun.l.google.com:19302`)
- TURN optional (recommended for stricter NAT environments)

Packaged SDK targets with bundled native core + runtime transport (Python, npm, Maven):
- Windows x64
- Linux x64
- macOS Intel (x64)
- macOS Apple Silicon (arm64)

## SDK Packages (Install First)

Python:
- Package: `p4_core`
- PyPI: `https://pypi.org/project/p4_core/`
- Install: `pip install p4_core`
- Legacy compatibility package: `p4-core-sdk` (`https://pypi.org/project/p4-core-sdk/`)
- Note: the official package name is `p4_core`.

JavaScript/TypeScript:
- Package: `@pythonicit/p4-core-sdk`
- npm: `https://www.npmjs.com/package/@pythonicit/p4-core-sdk`
- Install: `npm i @pythonicit/p4-core-sdk`

Java:
- Coordinates: `io.github.masterjx9:p4-core-sdk:0.2.1`
- Maven Central: `https://central.sonatype.com/artifact/io.github.masterjx9/p4-core-sdk`

PHP:
- Package: `masterjx9/p4-core-sdk`
- Packagist: `https://packagist.org/packages/masterjx9/p4-core-sdk`
- Install: `composer require masterjx9/p4-core-sdk`
- Runtime payload auto-resolution is included in package behavior.

C++:
- Wrapper lives in this repo: `bindings/cpp`
- Uses bundled runtime payload auto-resolution.

## Source Install (Secondary)

Use source installs only when developing/contributing to this monorepo:
- Python: `pip install -e .\bindings\python`
- JS/TS: `npm install .\bindings\javascript`
- Java: `mvn -f bindings\java\pom.xml package`
- PHP: `composer install` in repo root
- C++: `cmake -S bindings/cpp -B bindings/cpp/build && cmake --build bindings/cpp/build --config Release`

Source-only runtime build:
- Windows: `powershell -ExecutionPolicy Bypass -File .\build_onionrelay_windows.ps1`
- Linux/macOS: `./scripts/build_onionrelay_unix.sh`

## Abstract Device Requirements

For any device/platform/language implementation of P4:
- A stable local identity keypair persisted on disk
- Ability to run the P4 native crypto core for that OS/arch
- Network access to the rendezvous network for rediscovery signaling
- Network access for WebRTC ICE (STUN, optionally TURN)
- Local storage for state (identity, known peers, service metadata)
- Reasonably correct system clock for envelope freshness checks
- Ability to open local loopback/listener ports for runtime signaling paths

## Python Test (Package-First)

This test uses `pip install p4_core` with bundled runtime payloads (no source build required).

1. Create env and install dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install p4_core aiortc cryptography
```
2. Initialize two peers:

```powershell
python p4.py init --state-dir .\human_test\peerA
python p4.py init --state-dir .\human_test\peerB
```

3. Start peer A (terminal 1):

```powershell
python p4.py run --state-dir .\human_test\peerA
```

4. Start peer B (terminal 2):

```powershell
python p4.py run --state-dir .\human_test\peerB
```

5. In each `p4>` prompt:
- Run `/invite` and exchange JSON
- Add the other peer invite: `/add-json <invite-json>` or `/add-file <path>`
- Verify with `/peers`
- Send message: `/send <peer_id> hello`
- Reconnect test: `/drop <peer_id>` then wait for auto reconnect and send again

## Architecture Summary

Rust core:
- `rust/p4-core`: identity, peer id derivation, envelope sign/verify
- `rust/p4-ffi`: C ABI
- `include/p4_core.h`: ABI contract

Python runtime:
- `p4.py` is a reference node/CLI and consumes `p4_core` package.

Runtime transport (source-only build tooling):
- Windows subset build via `build_onionrelay_windows.ps1`
- Linux/macOS build pipeline via `.github/workflows/build-onionrelay-unix.yml`

## Contributing

1. Fork and create a feature branch from `main`.
2. Keep changes scoped (runtime, core, or one binding per PR when possible).
3. Run the relevant local checks before pushing:
- Python: import + runtime smoke where touched
- JS: package install smoke where touched
- Java: `mvn -f bindings/java/pom.xml package`
- PHP: `php -l` and runtime smoke where touched
- C++: CMake build + example run
4. Update docs/README for any behavior or install flow change.
5. Open PR with:
- what changed
- how you tested
- platform(s) tested

## Security Notes

- App data runs over direct point-to-point channels when ICE succeeds.
- Persistent rediscovery signaling is handled by the bundled runtime transport.
- TURN is optional but recommended for higher reliability through strict NAT/firewall conditions.
- You can override native lib path in all SDKs with `P4_CORE_LIB`.
