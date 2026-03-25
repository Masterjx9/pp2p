#!/usr/bin/env python3
"""
Persistent Point-to-Point (P4) node runtime.

Protocol summary:
- Every node has a persistent Ed25519 identity key.
- Peers pin each other's public keys in contacts.json.
- Signaling messages are signed JSON envelopes.
- Rendezvous transport is either:
  - onion: connect to peer hidden service through local OnionRelay SOCKS
  - direct: plain TCP (for local testing without onion relay)
- Data traffic uses WebRTC DataChannels (aiortc).
- If a session dies, the initiator automatically re-runs signaling.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import shutil
import signal
import socket
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from aiortc import RTCConfiguration, RTCDataChannel, RTCIceServer, RTCPeerConnection
from aiortc import RTCSessionDescription

from p4_core import P4Core, P4CoreError, resolve_onionrelay_binary_path as resolve_packaged_onionrelay_binary_path


PROTOCOL_VERSION = 1
IDENTITY_FILE = "identity_ed25519.json"
LEGACY_IDENTITY_FILE = "identity_ed25519.pem"
CONTACTS_FILE = "contacts.json"
ONIONRELAY_DIR = "onionrelay"
ONIONRELAY_DATA_DIR = "data"
ONIONRELAYRC_FILE = "onionrelayrc"
ONION_KEY_BLOB_FILE = "onion_v3_key_blob.txt"
ONION_SERVICE_ID_FILE = "onion_service_id.txt"
REPO_ROOT = Path(__file__).resolve().parent
MAX_ENVELOPE_SKEW_MS = 24 * 3600 * 1000
_P4_CORE: Optional[P4Core] = None


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_text_any_common_encoding(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # Final fallback keeps behavior deterministic: JSON parse will fail with a clear error.
    return raw.decode("utf-8")


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def get_p4_core() -> P4Core:
    global _P4_CORE
    if _P4_CORE is not None:
        return _P4_CORE

    lib_override = os.environ.get("P4_CORE_LIB")
    try:
        _P4_CORE = P4Core(lib_override if lib_override else None)
    except OSError as exc:
        raise RuntimeError(
            "Failed to load P4 Rust core library. "
            "Build it first with scripts/build_p4_core.ps1 (Windows) or "
            "scripts/build_p4_core_unix.sh (Linux/macOS), or set P4_CORE_LIB."
        ) from exc
    return _P4_CORE


def derive_turn_rest_credentials(
    shared_secret: str,
    ttl_seconds: int,
    user_hint: str = "p4",
) -> tuple[str, str]:
    """
    Generate ephemeral TURN credentials compatible with TURN REST auth style.
    """
    if ttl_seconds <= 0:
        raise RuntimeError("--turn-ttl-seconds must be > 0")
    expiry = int(time.time()) + int(ttl_seconds)
    username = f"{expiry}:{user_hint}" if user_hint else str(expiry)
    digest = hmac.new(
        shared_secret.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    credential = b64e(digest)
    return username, credential


def parse_host_port(text: str) -> tuple[str, int]:
    if ":" not in text:
        raise ValueError("Expected <host>:<port>")
    host, port_text = text.rsplit(":", 1)
    return host, int(port_text)


def is_local_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def pick_onion_port_trio(state_dir: Path) -> tuple[int, int, int]:
    """
    Pick a stable, free local (signal, socks, control) port trio.
    """
    seed = int(hashlib.sha256(str(state_dir).encode("utf-8")).hexdigest()[:8], 16)
    for n in range(30000):
        base = 20000 + ((seed + n) % 30000)  # 20000..49999
        signal_port = base
        socks_port = base + 1
        control_port = base + 2
        if (
            is_local_port_free("127.0.0.1", signal_port)
            and is_local_port_free("127.0.0.1", socks_port)
            and is_local_port_free("127.0.0.1", control_port)
        ):
            return signal_port, socks_port, control_port
    raise RuntimeError("Could not find a free local onion port trio")


def local_onionrelay_binary_candidates() -> list[Path]:
    candidates = [
        REPO_ROOT / "onionrelay" / "win32-x64" / "onionrelay.exe",
        REPO_ROOT / "onionrelay" / "linux-x64" / "onionrelay",
        REPO_ROOT / "onionrelay" / "darwin-x64" / "onionrelay",
        REPO_ROOT / "onionrelay" / "darwin-arm64" / "onionrelay",
        REPO_ROOT / "onionrelay_src" / "src" / "app" / "onionrelay.exe",
        REPO_ROOT / "onionrelay_src" / "src" / "app" / "onionrelay",
        REPO_ROOT / "dist" / "onionrelay.exe",
        REPO_ROOT / "dist" / "onionrelay",
    ]
    try:
        bundled = Path(resolve_packaged_onionrelay_binary_path(None))
        candidates.insert(0, bundled)
    except Exception:
        pass
    return candidates


def resolve_onionrelay_binary_path(onionrelay_bin: Optional[str]) -> str:
    """
    Resolve an OnionRelay runtime binary.

    Priority:
    1) explicit --onionrelay-bin from caller
    2) bundled SDK onionrelay runtime
    3) local repo candidates
    """
    if onionrelay_bin:
        found = shutil.which(onionrelay_bin) or onionrelay_bin
        p = Path(found)
        if os.name == "nt" and p.exists() and p.suffix.lower() != ".exe":
            raise RuntimeError(
                f"OnionRelay binary must be a native Windows executable (.exe): {p}. "
                "Provide a .exe path."
            )
        return str(p)

    try:
        return resolve_packaged_onionrelay_binary_path(None)
    except Exception:
        pass

    for candidate in local_onionrelay_binary_candidates():
        if not candidate.exists():
            continue
        if os.name == "nt" and candidate.suffix.lower() != ".exe":
            continue
        if os.name != "nt" and candidate.suffix.lower() == ".exe":
            continue
        if candidate.exists():
            return str(candidate)

    raise RuntimeError(
        "No compatible OnionRelay binary found. Install a package build that bundles onionrelay "
        "or pass --onionrelay-bin explicitly."
    )


@dataclass
class Rendezvous:
    transport: str
    address: str
    port: int


@dataclass
class Contact:
    peer_id: str
    public_key_b64: str
    rendezvous: Rendezvous
    name: str = ""

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Contact":
        return Contact(
            peer_id=raw["peer_id"],
            public_key_b64=raw["public_key_b64"],
            rendezvous=Rendezvous(**raw["rendezvous"]),
            name=raw.get("name", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["rendezvous"] = asdict(self.rendezvous)
        return out


@dataclass
class Identity:
    private_key_b64: str
    public_key_b64: str
    peer_id: str

    @staticmethod
    def load_or_create(path: Path, core: P4Core) -> "Identity":
        ensure_parent(path)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            identity = Identity(
                private_key_b64=raw["private_key_b64"],
                public_key_b64=raw["public_key_b64"],
                peer_id=raw["peer_id"],
            )
            expected_peer_id = core.peer_id_from_public_key_b64(identity.public_key_b64)
            if identity.peer_id != expected_peer_id:
                raise RuntimeError(
                    "Identity peer_id does not match public_key_b64 in identity file"
                )
            return identity

        legacy = path.parent / LEGACY_IDENTITY_FILE
        if legacy.exists():
            return Identity._migrate_legacy_pem(path, legacy, core)

        raw_ident = core.generate_identity()
        identity = Identity(
            private_key_b64=raw_ident["private_key_b64"],
            public_key_b64=raw_ident["public_key_b64"],
            peer_id=raw_ident["peer_id"],
        )
        atomic_write_json(path, asdict(identity))
        return identity

    @staticmethod
    def _migrate_legacy_pem(path: Path, legacy_path: Path, core: P4Core) -> "Identity":
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ed25519
        except Exception as exc:
            raise RuntimeError(
                f"Legacy identity exists at {legacy_path} but cryptography is unavailable. "
                "Install cryptography once to migrate, then rerun."
            ) from exc

        raw_pem = legacy_path.read_bytes()
        private = serialization.load_pem_private_key(raw_pem, password=None)
        if not isinstance(private, ed25519.Ed25519PrivateKey):
            raise RuntimeError(f"Legacy identity file is not Ed25519: {legacy_path}")

        private_raw = private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_raw = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        identity = Identity(
            private_key_b64=b64e(private_raw),
            public_key_b64=b64e(public_raw),
            peer_id=core.peer_id_from_public_key_b64(b64e(public_raw)),
        )
        atomic_write_json(path, asdict(identity))
        log(f"Migrated legacy identity to {path.name}")
        return identity


class ReplayWindow:
    def __init__(self, max_seen: int = 4096) -> None:
        self.max_seen = max_seen
        self._seen: dict[str, list[str]] = {}
        self._seen_set: dict[str, set[str]] = {}

    def seen(self, peer_id: str, nonce: str) -> bool:
        s = self._seen_set.setdefault(peer_id, set())
        if nonce in s:
            return True
        seq = self._seen.setdefault(peer_id, [])
        seq.append(nonce)
        s.add(nonce)
        if len(seq) > self.max_seen:
            old = seq.pop(0)
            s.discard(old)
        return False


@dataclass
class Session:
    contact: Contact
    role: str
    pc: Optional[RTCPeerConnection] = None
    dc: Optional[RTCDataChannel] = None
    connected: bool = False
    state: str = "idle"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    current_session_id: str = ""


@dataclass
class RuntimeConfig:
    state_dir: Path
    mode: str
    signal_host: str
    signal_port: int
    advertise_host: str
    retry_seconds: float
    stun_server: str
    turn_server: Optional[str]
    turn_username: Optional[str]
    turn_password: Optional[str]
    turn_secret: Optional[str]
    turn_ttl_seconds: int
    turn_user: str
    onionrelay_bin: Optional[str]
    onionrelay_socks_port: int
    onionrelay_control_port: int
    no_stdin: bool


class P4Node:
    def __init__(self, cfg: RuntimeConfig) -> None:
        self.cfg = cfg
        self.core = get_p4_core()
        self.identity = Identity.load_or_create(self.cfg.state_dir / IDENTITY_FILE, self.core)
        self.contacts: dict[str, Contact] = {}
        self.sessions: dict[str, Session] = {}
        self.replay = ReplayWindow()

        self.server: Optional[asyncio.AbstractServer] = None
        self._maintainers: list[asyncio.Task[Any]] = []
        self._stdin_task: Optional[asyncio.Task[Any]] = None
        self._stop = asyncio.Event()
        self._onionrelay_proc: Optional[asyncio.subprocess.Process] = None
        self._onionrelay_log_task: Optional[asyncio.Task[Any]] = None
        self._onionrelay_control_reader: Optional[asyncio.StreamReader] = None
        self._onionrelay_control_writer: Optional[asyncio.StreamWriter] = None
        self._onion_service_id: Optional[str] = None
        self._own_rendezvous: Optional[Rendezvous] = None
        self._turn_mode = "none"

        ice_servers: list[RTCIceServer] = []
        if self.cfg.stun_server:
            ice_servers.append(RTCIceServer(urls=[self.cfg.stun_server]))
        if self.cfg.turn_server:
            turn_username = self.cfg.turn_username
            turn_password = self.cfg.turn_password
            if bool(turn_username) ^ bool(turn_password):
                raise RuntimeError(
                    "Provide both --turn-username and --turn-password, or neither."
                )
            if not turn_username and not turn_password and self.cfg.turn_secret:
                turn_username, turn_password = derive_turn_rest_credentials(
                    shared_secret=self.cfg.turn_secret,
                    ttl_seconds=self.cfg.turn_ttl_seconds,
                    user_hint=self.cfg.turn_user,
                )
                self._turn_mode = "rest-secret"
                log(
                    f"TURN credentials auto-generated (mode=rest-secret ttl={self.cfg.turn_ttl_seconds}s)"
                )
            elif turn_username and turn_password:
                self._turn_mode = "static-creds"
            else:
                self._turn_mode = "no-auth"

            if turn_username and turn_password:
                ice_servers.append(
                    RTCIceServer(
                        urls=[self.cfg.turn_server],
                        username=turn_username,
                        credential=turn_password,
                    )
                )
            else:
                ice_servers.append(RTCIceServer(urls=[self.cfg.turn_server]))
        self._ice_config = RTCConfiguration(iceServers=ice_servers)

    @property
    def own_rendezvous(self) -> Rendezvous:
        if self._own_rendezvous is None:
            raise RuntimeError("Node rendezvous is not initialized yet")
        return self._own_rendezvous

    def _contacts_path(self) -> Path:
        return self.cfg.state_dir / CONTACTS_FILE

    def _onionrelay_root(self) -> Path:
        return self.cfg.state_dir / ONIONRELAY_DIR

    def _onionrelay_data(self) -> Path:
        return self._onionrelay_root() / ONIONRELAY_DATA_DIR

    def _onionrelayrc_path(self) -> Path:
        return self._onionrelay_root() / ONIONRELAYRC_FILE

    def _onion_key_blob_path(self) -> Path:
        return self._onionrelay_root() / ONION_KEY_BLOB_FILE

    def _onion_service_id_path(self) -> Path:
        return self._onionrelay_root() / ONION_SERVICE_ID_FILE

    async def run(self) -> None:
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self._load_contacts()
        await self._setup_rendezvous()
        await self._start_signal_server()
        self._start_maintainers()

        log(f"Node peer_id={self.identity.peer_id}")
        log(f"Rendezvous: {self.own_rendezvous.transport}://{self.own_rendezvous.address}:{self.own_rendezvous.port}")
        log(
            "Local ports: "
            f"signal={self.cfg.signal_port} "
            f"socks={self.cfg.onionrelay_socks_port} "
            f"control={self.cfg.onionrelay_control_port}"
        )
        log(
            f"ICE: stun={self.cfg.stun_server} "
            f"turn={self._turn_mode if self.cfg.turn_server else 'none'}"
        )
        log("Share this invite with peers:")
        print(json.dumps(self.build_invite(), indent=2, sort_keys=True), flush=True)

        if not self.cfg.no_stdin:
            self._stdin_task = asyncio.create_task(self._stdin_loop(), name="stdin-loop")

        await self._stop.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        for task in self._maintainers:
            task.cancel()
        self._maintainers.clear()

        if self._stdin_task:
            self._stdin_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stdin_task
            self._stdin_task = None

        for session in self.sessions.values():
            await self._close_session_pc(session)

        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

        if self._onionrelay_log_task:
            self._onionrelay_log_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._onionrelay_log_task
            self._onionrelay_log_task = None

        if self._onionrelay_control_writer:
            if self._onion_service_id:
                with contextlib.suppress(Exception):
                    await self._onionrelay_control_command(f"DEL_ONION {self._onion_service_id}")
                self._onion_service_id = None
            self._onionrelay_control_writer.close()
            with contextlib.suppress(Exception):
                await self._onionrelay_control_writer.wait_closed()
            self._onionrelay_control_writer = None
            self._onionrelay_control_reader = None

        if self._onionrelay_proc:
            if self._onionrelay_proc.returncode is None:
                self._onionrelay_proc.terminate()
                try:
                    await asyncio.wait_for(self._onionrelay_proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self._onionrelay_proc.kill()
                    await self._onionrelay_proc.wait()
            self._onionrelay_proc = None

    def stop(self) -> None:
        self._stop.set()

    def _load_contacts(self) -> None:
        raw = load_json_file(self._contacts_path(), default=[])
        contacts = [Contact.from_dict(item) for item in raw]
        self.contacts = {c.peer_id: c for c in contacts}
        self.sessions = {}
        for c in contacts:
            role = "initiator" if self.identity.peer_id < c.peer_id else "responder"
            self.sessions[c.peer_id] = Session(contact=c, role=role)

    def _save_contacts(self) -> None:
        payload = [c.to_dict() for c in sorted(self.contacts.values(), key=lambda x: x.peer_id)]
        atomic_write_json(self._contacts_path(), payload)

    def build_invite(self) -> dict[str, Any]:
        return {
            "peer_id": self.identity.peer_id,
            "public_key_b64": self.identity.public_key_b64,
            "rendezvous": asdict(self.own_rendezvous),
        }

    async def _setup_rendezvous(self) -> None:
        if self.cfg.mode == "onion":
            await self._start_onionrelay()
        elif self.cfg.mode == "direct":
            self._own_rendezvous = Rendezvous(
                transport="direct",
                address=self.cfg.advertise_host,
                port=self.cfg.signal_port,
            )
        else:
            raise RuntimeError(f"Unsupported mode: {self.cfg.mode}")

    async def _start_onionrelay(self, wait_bootstrap: bool = True, quiet: bool = False) -> None:
        onionrelay_bin = resolve_onionrelay_binary_path(self.cfg.onionrelay_bin)
        onionrelay_path = Path(onionrelay_bin)
        if not onionrelay_path.exists() and not shutil.which(onionrelay_bin):
            raise RuntimeError(f"OnionRelay binary not found: {onionrelay_bin}")
        if os.name == "nt" and onionrelay_path.exists() and onionrelay_path.suffix.lower() != ".exe":
            raise RuntimeError(
                f"Refusing non-Windows OnionRelay binary on Windows: {onionrelay_path}. "
                "Use onionrelay.exe."
            )

        self._onionrelay_root().mkdir(parents=True, exist_ok=True)
        self._onionrelay_data().mkdir(parents=True, exist_ok=True)

        relayrc = [
            f"SocksPort {self.cfg.onionrelay_socks_port}",
            f"ControlPort {self.cfg.onionrelay_control_port}",
            f"DataDirectory {self._onionrelay_data().resolve()}",
            "CookieAuthentication 0",
            "ClientOnly 1",
            "AvoidDiskWrites 1",
            "Log notice stdout",
        ]
        self._onionrelayrc_path().write_text("\n".join(relayrc) + "\n", encoding="utf-8")

        if not quiet:
            log("Starting OnionRelay process...")
        proc_env = os.environ.copy()
        if os.name == "nt":
            mingw_bin = Path(r"C:\msys64\mingw64\bin")
            if mingw_bin.exists():
                current_path = proc_env.get("PATH", "")
                path_parts = current_path.split(";") if current_path else []
                if str(mingw_bin) not in path_parts:
                    proc_env["PATH"] = str(mingw_bin) + (";" + current_path if current_path else "")
        if quiet:
            self._onionrelay_proc = await asyncio.create_subprocess_exec(
                onionrelay_bin,
                "-f",
                str(self._onionrelayrc_path()),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=proc_env,
            )
        else:
            self._onionrelay_proc = await asyncio.create_subprocess_exec(
                onionrelay_bin,
                "-f",
                str(self._onionrelayrc_path()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=proc_env,
            )
            self._onionrelay_log_task = asyncio.create_task(self._pump_onionrelay_logs(), name="onionrelay-log")

        await self._wait_for_local_port("127.0.0.1", self.cfg.onionrelay_socks_port, timeout=120)
        await self._wait_for_local_port("127.0.0.1", self.cfg.onionrelay_control_port, timeout=120)
        await self._open_onionrelay_control()
        await self._onionrelay_authenticate()
        service_id = await self._onionrelay_add_onion_service(self.cfg.signal_port)
        if wait_bootstrap:
            await self._wait_for_onionrelay_bootstrap(timeout=360)
        self._onion_service_id = service_id
        onion = f"{service_id}.onion"
        self._own_rendezvous = Rendezvous(transport="onion", address=onion, port=80)
        if not quiet:
            log(f"Onion relay ready: {onion}")

    async def _open_onionrelay_control(self) -> None:
        self._onionrelay_control_reader, self._onionrelay_control_writer = await asyncio.open_connection(
            "127.0.0.1",
            self.cfg.onionrelay_control_port,
        )

    async def _onionrelay_authenticate(self) -> None:
        try:
            await self._onionrelay_control_command("AUTHENTICATE")
            return
        except Exception:
            pass
        await self._onionrelay_control_command('AUTHENTICATE ""')

    async def _onionrelay_add_onion_service(self, local_port: int) -> str:
        existing_blob = self._load_onion_key_blob()
        key_spec = f"ED25519-V3:{existing_blob}" if existing_blob else "NEW:ED25519-V3"
        cmd = f"ADD_ONION {key_spec} Flags=Detach Port=80,127.0.0.1:{local_port}"
        lines = await self._onionrelay_control_command(cmd)

        service_id: Optional[str] = None
        new_key_blob: Optional[str] = None
        for line in lines:
            if line.startswith("ServiceID="):
                service_id = line.split("=", 1)[1].strip()
            elif line.startswith("PrivateKey="):
                value = line.split("=", 1)[1].strip()
                if value.startswith("ED25519-V3:"):
                    new_key_blob = value.split(":", 1)[1].strip()

        if not service_id:
            raise RuntimeError("ADD_ONION did not return ServiceID")

        self._onion_service_id_path().write_text(service_id + "\n", encoding="utf-8")
        if new_key_blob:
            self._onion_key_blob_path().write_text(new_key_blob + "\n", encoding="utf-8")
        elif not existing_blob:
            raise RuntimeError("ADD_ONION did not return key material for NEW:ED25519-V3")

        return service_id

    def _load_onion_key_blob(self) -> Optional[str]:
        path = self._onion_key_blob_path()
        if not path.exists():
            return None
        blob = path.read_text(encoding="utf-8").strip()
        return blob or None

    async def _onionrelay_control_command(self, command: str) -> list[str]:
        if not self._onionrelay_control_reader or not self._onionrelay_control_writer:
            raise RuntimeError("OnionRelay control connection is not open")

        self._onionrelay_control_writer.write((command + "\r\n").encode("utf-8"))
        await self._onionrelay_control_writer.drain()

        lines: list[str] = []
        while True:
            raw = await self._onionrelay_control_reader.readline()
            if not raw:
                raise RuntimeError("EOF from OnionRelay control port")

            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if len(line) < 3 or not line[:3].isdigit():
                raise RuntimeError(f"Malformed OnionRelay control reply: {line}")

            code = int(line[:3])
            sep = line[3] if len(line) >= 4 else " "
            rest = line[4:] if len(line) > 4 else ""

            if code >= 400:
                raise RuntimeError(f"OnionRelay control error {code}: {rest}")

            if sep == "+":
                # Data block mode; read until a single "." line.
                lines.append(rest)
                while True:
                    chunk = await self._onionrelay_control_reader.readline()
                    if not chunk:
                        raise RuntimeError("EOF during OnionRelay control data block")
                    text = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
                    if text == ".":
                        break
                    if text.startswith(".."):
                        text = text[1:]
                    lines.append(text)
                continue

            lines.append(rest)
            if sep == " ":
                return lines
            if sep == "-":
                continue
            raise RuntimeError(f"Unexpected OnionRelay control line separator: {line}")

    async def _wait_for_onionrelay_bootstrap(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if self._onionrelay_proc and self._onionrelay_proc.returncode is not None:
                raise RuntimeError(f"OnionRelay exited with code {self._onionrelay_proc.returncode}")

            try:
                lines = await self._onionrelay_control_command("GETINFO status/bootstrap-phase")
                progress = self._extract_bootstrap_progress(lines)
                if progress >= 100:
                    return
            except Exception:
                # Keep waiting while OnionRelay settles.
                pass

            if time.monotonic() > deadline:
                raise TimeoutError("OnionRelay bootstrap did not reach 100% in time")
            await asyncio.sleep(1.0)

    @staticmethod
    def _extract_bootstrap_progress(lines: list[str]) -> int:
        for line in lines:
            if line.startswith("status/bootstrap-phase="):
                body = line.split("=", 1)[1]
                for token in body.split():
                    if token.startswith("PROGRESS="):
                        value = token.split("=", 1)[1]
                        try:
                            return int(value)
                        except ValueError:
                            return -1
        return -1

    async def _pump_onionrelay_logs(self) -> None:
        if not self._onionrelay_proc or not self._onionrelay_proc.stdout:
            return
        while True:
            line = await self._onionrelay_proc.stdout.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                log(f"[onionrelay] {text}")

    async def _wait_for_local_port(self, host: str, port: int, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if self._onionrelay_proc and self._onionrelay_proc.returncode is not None:
                raise RuntimeError(
                    "OnionRelay process exited before opening local ports. "
                    "On Windows, ensure these DLLs exist next to onionrelay.exe: "
                    "libcrypto-3-x64.dll, libssl-3-x64.dll, libevent-7.dll, "
                    "liblzma-5.dll, zlib1.dll, libzstd.dll, libwinpthread-1.dll."
                )
            try:
                reader, writer = await asyncio.open_connection(host, port)
                writer.close()
                await writer.wait_closed()
                return
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Port {host}:{port} did not open in time")
                await asyncio.sleep(0.5)

    async def _start_signal_server(self) -> None:
        self.server = await asyncio.start_server(
            self._handle_signal_conn,
            host=self.cfg.signal_host,
            port=self.cfg.signal_port,
        )
        sock_names = ", ".join(str(sock.getsockname()) for sock in self.server.sockets or [])
        log(f"Signaling server listening on {sock_names}")

    def _start_maintainers(self) -> None:
        for session in self.sessions.values():
            if session.role == "initiator":
                task = asyncio.create_task(self._maintain_contact(session), name=f"maintain-{session.contact.peer_id}")
                self._maintainers.append(task)

    async def _maintain_contact(self, session: Session) -> None:
        while not self._stop.is_set():
            try:
                if not session.connected:
                    await self._initiate_with_contact(session)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log(f"Dial to {session.contact.peer_id} failed: {exc}")
            await asyncio.sleep(self.cfg.retry_seconds)

    async def _initiate_with_contact(self, session: Session) -> None:
        async with session.lock:
            if session.connected:
                return

            await self._close_session_pc(session)
            pc = await self._create_pc(session, initiator=True)
            session.pc = pc
            session.state = "negotiating"
            session.current_session_id = str(uuid.uuid4())

            dc = pc.createDataChannel("chat")
            self._wire_datachannel(session, dc)

            await pc.setLocalDescription(await pc.createOffer())
            await self._wait_ice_complete(pc)

            payload = {
                "type": "offer",
                "session_id": session.current_session_id,
                "sdp": pc.localDescription.sdp,
                "sdp_type": pc.localDescription.type,
            }
            envelope = self._build_message(session.contact.peer_id, payload)
            reply = await self._send_signal_request(session.contact, envelope)
            await self._validate_message(reply, expected_from=session.contact.peer_id)
            if reply.get("payload", {}).get("type") != "answer":
                raise RuntimeError("Expected answer payload")

            if reply["payload"]["session_id"] != session.current_session_id:
                raise RuntimeError("Session ID mismatch in answer")

            answer = RTCSessionDescription(
                sdp=reply["payload"]["sdp"],
                type=reply["payload"]["sdp_type"],
            )
            await pc.setRemoteDescription(answer)
            session.state = "answer-applied"
            log(f"Negotiation done with {session.contact.peer_id}, waiting for data channel")

    async def _handle_signal_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            msg = await self._read_json_line(reader, timeout=25)
            await self._validate_message(msg, expected_to=self.identity.peer_id)

            payload = msg.get("payload", {})
            msg_type = payload.get("type")
            remote_peer_id = msg["sender_peer_id"]

            if msg_type == "offer":
                response_payload = await self._handle_offer(remote_peer_id, payload)
                response = self._build_message(remote_peer_id, response_payload)
            elif msg_type == "ping":
                response = self._build_message(
                    remote_peer_id,
                    {"type": "pong", "session_id": payload.get("session_id", "")},
                )
            else:
                raise RuntimeError(f"Unsupported inbound message type: {msg_type}")

            await self._write_json_line(writer, response)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            err = {"ok": False, "error": str(exc)}
            with contextlib.suppress(Exception):
                await self._write_json_line(writer, err)
            log(f"Signal handling error from {peer}: {exc}")
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _handle_offer(self, peer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = self.sessions.get(peer_id)
        if session is None:
            raise RuntimeError(f"Unknown peer: {peer_id}")

        async with session.lock:
            await self._close_session_pc(session)
            pc = await self._create_pc(session, initiator=False)
            session.pc = pc
            session.state = "negotiating"
            session.current_session_id = payload["session_id"]

            offer = RTCSessionDescription(sdp=payload["sdp"], type=payload["sdp_type"])
            await pc.setRemoteDescription(offer)
            await pc.setLocalDescription(await pc.createAnswer())
            await self._wait_ice_complete(pc)

            return {
                "type": "answer",
                "session_id": session.current_session_id,
                "sdp": pc.localDescription.sdp,
                "sdp_type": pc.localDescription.type,
            }

    async def _create_pc(self, session: Session, initiator: bool) -> RTCPeerConnection:
        pc = RTCPeerConnection(self._ice_config)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            state = pc.connectionState
            session.state = state
            log(f"{session.contact.peer_id} connection state -> {state}")
            if state in {"failed", "closed", "disconnected"}:
                session.connected = False
                session.dc = None
                if session.pc is pc:
                    session.pc = None
                with contextlib.suppress(Exception):
                    await pc.close()

        if not initiator:
            @pc.on("datachannel")
            def on_datachannel(dc: RTCDataChannel) -> None:
                self._wire_datachannel(session, dc)

        return pc

    def _wire_datachannel(self, session: Session, dc: RTCDataChannel) -> None:
        session.dc = dc

        def mark_open() -> None:
            if session.connected:
                return
            session.connected = True
            session.state = "connected"
            log(f"Data channel OPEN with {session.contact.peer_id}")
            hello = {
                "type": "hello",
                "from_peer_id": self.identity.peer_id,
                "timestamp": int(time.time()),
            }
            dc.send(json.dumps(hello, sort_keys=True))

        @dc.on("open")
        def on_open() -> None:
            mark_open()

        @dc.on("message")
        def on_message(raw: Any) -> None:
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="replace")
            else:
                text = str(raw)
            try:
                obj = json.loads(text)
                if obj.get("type") == "chat":
                    print(f"{session.contact.peer_id}> {obj.get('text', '')}", flush=True)
                elif obj.get("type") == "hello":
                    log(f"Handshake hello from {session.contact.peer_id}")
                else:
                    log(f"{session.contact.peer_id} sent: {obj}")
            except json.JSONDecodeError:
                print(f"{session.contact.peer_id}> {text}", flush=True)

        @dc.on("close")
        def on_close() -> None:
            session.connected = False
            session.state = "channel-closed"
            session.dc = None
            log(f"Data channel CLOSED with {session.contact.peer_id}")

        if dc.readyState == "open":
            mark_open()

    async def _close_session_pc(self, session: Session) -> None:
        pc = session.pc
        session.pc = None
        session.dc = None
        session.connected = False
        if pc is not None:
            with contextlib.suppress(Exception):
                await pc.close()

    async def _wait_ice_complete(self, pc: RTCPeerConnection, timeout: float = 20) -> None:
        start = time.monotonic()
        while pc.iceGatheringState != "complete":
            if time.monotonic() - start > timeout:
                raise TimeoutError("ICE gathering timeout")
            await asyncio.sleep(0.05)

    def _build_message(self, to_peer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.core.sign_envelope(
                private_key_b64=self.identity.private_key_b64,
                sender_peer_id=self.identity.peer_id,
                recipient_peer_id=to_peer_id,
                payload=payload,
                nonce=secrets.token_hex(16),
                timestamp_ms=int(time.time() * 1000),
            )
        except P4CoreError as exc:
            raise RuntimeError(f"Envelope signing failed: {exc}") from exc

    async def _validate_message(
        self,
        msg: dict[str, Any],
        expected_from: Optional[str] = None,
        expected_to: Optional[str] = None,
    ) -> None:
        if msg.get("protocol_version") != PROTOCOL_VERSION:
            raise RuntimeError("Unsupported protocol version")
        from_peer_id = msg.get("sender_peer_id")
        to_peer_id = msg.get("recipient_peer_id")
        if not isinstance(from_peer_id, str) or not isinstance(to_peer_id, str):
            raise RuntimeError("Invalid envelope peer IDs")

        if expected_from and from_peer_id != expected_from:
            raise RuntimeError("Unexpected message sender")
        if expected_to and to_peer_id != expected_to:
            raise RuntimeError("Unexpected message recipient")

        contact = self.contacts.get(from_peer_id)
        if contact is None:
            raise RuntimeError(f"Unknown peer identity: {from_peer_id}")

        nonce = str(msg.get("nonce", ""))
        if not nonce:
            raise RuntimeError("Missing nonce")
        try:
            self.core.verify_envelope(
                envelope=msg,
                signer_public_key_b64=contact.public_key_b64,
                now_ms=int(time.time() * 1000),
                max_skew_ms=MAX_ENVELOPE_SKEW_MS,
            )
        except P4CoreError as exc:
            raise RuntimeError(f"Signature verification failed: {exc}") from exc

        if self.replay.seen(from_peer_id, nonce):
            raise RuntimeError("Replay detected")

    async def _send_signal_request(self, contact: Contact, msg: dict[str, Any]) -> dict[str, Any]:
        rendezvous = contact.rendezvous
        if rendezvous.transport == "direct":
            reader, writer = await asyncio.open_connection(rendezvous.address, rendezvous.port)
        elif rendezvous.transport == "onion":
            reader, writer = await self._open_onion_stream(rendezvous.address, rendezvous.port)
        else:
            raise RuntimeError(f"Unsupported contact transport: {rendezvous.transport}")

        try:
            await self._write_json_line(writer, msg)
            reply = await self._read_json_line(reader, timeout=25)
            if isinstance(reply, dict) and reply.get("ok") is False:
                raise RuntimeError(f"Remote error: {reply.get('error', 'unknown')}")
            return reply
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _open_onion_stream(self, onion_host: str, onion_port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.cfg.onionrelay_socks_port)
        try:
            await self._socks5_handshake(reader, writer, onion_host, onion_port)
            return reader, writer
        except Exception:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            raise

    async def _socks5_handshake(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        host: str,
        port: int,
    ) -> None:
        # greeting: SOCKS5, 1 method, no-auth
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        resp = await reader.readexactly(2)
        if resp != b"\x05\x00":
            raise RuntimeError("SOCKS auth negotiation failed")

        host_bytes = host.encode("ascii")
        if len(host_bytes) > 255:
            raise RuntimeError("SOCKS domain name too long")

        req = bytearray()
        req.extend(b"\x05\x01\x00\x03")
        req.append(len(host_bytes))
        req.extend(host_bytes)
        req.extend(port.to_bytes(2, "big"))
        writer.write(bytes(req))
        await writer.drain()

        head = await reader.readexactly(4)
        if head[0] != 0x05 or head[1] != 0x00:
            raise RuntimeError(f"SOCKS connect failed, code={head[1]}")
        atyp = head[3]
        if atyp == 0x01:  # IPv4
            await reader.readexactly(4 + 2)
        elif atyp == 0x03:  # domain
            ln = await reader.readexactly(1)
            await reader.readexactly(ln[0] + 2)
        elif atyp == 0x04:  # IPv6
            await reader.readexactly(16 + 2)
        else:
            raise RuntimeError("SOCKS replied with unknown address type")

    async def _write_json_line(self, writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
        writer.write((json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
        await writer.drain()

    async def _read_json_line(self, reader: asyncio.StreamReader, timeout: float) -> dict[str, Any]:
        raw = await asyncio.wait_for(reader.readline(), timeout=timeout)
        if not raw:
            raise RuntimeError("EOF while reading JSON line")
        try:
            val = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Invalid JSON line received") from exc
        if not isinstance(val, dict):
            raise RuntimeError("Expected JSON object")
        return val

    async def _stdin_loop(self) -> None:
        self._print_help()
        while not self._stop.is_set():
            try:
                line = await asyncio.to_thread(input, "p4> ")
            except (EOFError, KeyboardInterrupt):
                self.stop()
                return
            line = line.strip()
            if not line:
                continue
            await self._handle_command(line)

    def _print_help(self) -> None:
        print(
            "Commands: /help, /peers, /invite, /add-file <invite.json>, /add-json <invite-json>, /add-invite, /send <peer_id> <text>, "
            "/drop <peer_id>, /quit",
            flush=True,
        )

    async def _add_contact_from_invite_payload(self, invite: dict[str, Any]) -> None:
        try:
            contact = Contact.from_dict(invite)
        except Exception as exc:
            print(f"Invalid invite payload: {exc}", flush=True)
            return

        if contact.peer_id == self.identity.peer_id:
            print("Cannot add yourself as contact", flush=True)
            return

        is_new = contact.peer_id not in self.contacts
        self.contacts[contact.peer_id] = contact
        self._save_contacts()

        role = "initiator" if self.identity.peer_id < contact.peer_id else "responder"
        session = self.sessions.get(contact.peer_id)
        if session is None:
            session = Session(contact=contact, role=role)
            self.sessions[contact.peer_id] = session
            if session.role == "initiator":
                task = asyncio.create_task(
                    self._maintain_contact(session),
                    name=f"maintain-{session.contact.peer_id}",
                )
                self._maintainers.append(task)
        else:
            session.contact = contact
            session.role = role

        action = "Added" if is_new else "Updated"
        print(f"{action} contact {contact.peer_id}", flush=True)

    async def _add_contact_from_file(self, path_text: str) -> None:
        p = Path(path_text.strip().strip('"')).expanduser()
        try:
            raw = read_text_any_common_encoding(p)
            payload = json.loads(raw.lstrip("\ufeff"))
        except Exception as exc:
            print(f"Failed to read invite file '{p}': {exc}", flush=True)
            return
        await self._add_contact_from_invite_payload(payload)

    async def _add_contact_from_json_text(self, raw_json: str) -> None:
        try:
            payload = json.loads(raw_json.lstrip("\ufeff"))
        except Exception as exc:
            print(f"Invalid invite JSON: {exc}", flush=True)
            return
        await self._add_contact_from_invite_payload(payload)

    @staticmethod
    def _read_invite_multiline_from_stdin() -> str:
        print("Paste invite JSON, then enter a single '.' on its own line.", flush=True)
        lines: list[str] = []
        while True:
            line = input("invite> ")
            if line.strip() == ".":
                break
            lines.append(line)
        return "\n".join(lines)

    async def _handle_command(self, line: str) -> None:
        if line == "/help":
            self._print_help()
            return
        if line == "/peers":
            for s in self.sessions.values():
                print(
                    f"{s.contact.peer_id} role={s.role} connected={s.connected} state={s.state}",
                    flush=True,
                )
            return
        if line == "/invite":
            print(json.dumps(self.build_invite(), indent=2, sort_keys=True), flush=True)
            return
        if line.startswith("/add-file "):
            path_text = line.split(" ", 1)[1]
            if not path_text.strip():
                print("Usage: /add-file <invite.json>", flush=True)
                return
            await self._add_contact_from_file(path_text)
            return
        if line.startswith("/add-json "):
            raw_json = line.split(" ", 1)[1]
            if not raw_json.strip():
                print("Usage: /add-json <invite-json>", flush=True)
                return
            await self._add_contact_from_json_text(raw_json)
            return
        if line == "/add-invite":
            raw_json = await asyncio.to_thread(self._read_invite_multiline_from_stdin)
            await self._add_contact_from_json_text(raw_json)
            return
        if line == "/quit":
            self.stop()
            return
        if line.startswith("/send "):
            parts = line.split(" ", 2)
            if len(parts) < 3:
                print("Usage: /send <peer_id> <text>", flush=True)
                return
            await self.send_chat(parts[1], parts[2])
            return
        if line.startswith("/drop "):
            parts = line.split(" ", 1)
            await self.drop_peer(parts[1].strip())
            return
        print("Unknown command; use /help", flush=True)

    async def send_chat(self, peer_id: str, text: str) -> None:
        session = self.sessions.get(peer_id)
        if not session:
            print(f"Unknown peer_id: {peer_id}", flush=True)
            return
        if not session.dc or not session.connected:
            print(f"Peer {peer_id} is not connected", flush=True)
            return
        payload = {
            "type": "chat",
            "from_peer_id": self.identity.peer_id,
            "timestamp": int(time.time()),
            "text": text,
        }
        session.dc.send(json.dumps(payload, sort_keys=True))

    async def drop_peer(self, peer_id: str) -> None:
        session = self.sessions.get(peer_id)
        if not session:
            print(f"Unknown peer_id: {peer_id}", flush=True)
            return
        async with session.lock:
            await self._close_session_pc(session)
        print(f"Dropped session with {peer_id}", flush=True)


def state_identity(state_dir: Path) -> Identity:
    state_dir.mkdir(parents=True, exist_ok=True)
    return Identity.load_or_create(state_dir / IDENTITY_FILE, get_p4_core())


def load_contacts(state_dir: Path) -> dict[str, Contact]:
    path = state_dir / CONTACTS_FILE
    raw = load_json_file(path, default=[])
    contacts = [Contact.from_dict(item) for item in raw]
    return {c.peer_id: c for c in contacts}


def save_contacts(state_dir: Path, contacts: dict[str, Contact]) -> None:
    path = state_dir / CONTACTS_FILE
    payload = [c.to_dict() for c in sorted(contacts.values(), key=lambda x: x.peer_id)]
    atomic_write_json(path, payload)


def build_invite_from_state(state_dir: Path, mode: str, advertise: str) -> dict[str, Any]:
    ident = state_identity(state_dir)
    if mode == "onion":
        service_id_path = state_dir / ONIONRELAY_DIR / ONION_SERVICE_ID_FILE
        if not service_id_path.exists():
            raise RuntimeError(
                f"Missing onion service id file: {service_id_path}. "
                "Start the node in onion mode at least once."
            )
        service_id = service_id_path.read_text(encoding="utf-8").strip()
        onion = f"{service_id}.onion"
        rendezvous = Rendezvous(transport="onion", address=onion, port=80)
    else:
        host, port = parse_host_port(advertise)
        rendezvous = Rendezvous(transport="direct", address=host, port=port)
    return {
        "peer_id": ident.peer_id,
        "public_key_b64": ident.public_key_b64,
        "rendezvous": asdict(rendezvous),
    }


def resolve_runtime_ports_for_mode(
    mode: str,
    state_dir: Path,
    signal_port: Optional[int],
    onionrelay_socks_port: Optional[int],
    onionrelay_control_port: Optional[int],
) -> tuple[int, int, int]:
    if mode == "onion":
        if signal_port is None and onionrelay_socks_port is None and onionrelay_control_port is None:
            signal_port, onionrelay_socks_port, onionrelay_control_port = pick_onion_port_trio(state_dir)
        else:
            if signal_port is None:
                signal_port = 18080
            if onionrelay_socks_port is None:
                onionrelay_socks_port = 19050
            if onionrelay_control_port is None:
                onionrelay_control_port = 19051
    else:
        if signal_port is None:
            signal_port = 18080
        if onionrelay_socks_port is None:
            onionrelay_socks_port = 19050
        if onionrelay_control_port is None:
            onionrelay_control_port = 19051
    return int(signal_port), int(onionrelay_socks_port), int(onionrelay_control_port)


async def ensure_onion_identity_async(
    state_dir: Path,
    onionrelay_bin: Optional[str],
    signal_port: Optional[int],
    onionrelay_socks_port: Optional[int],
    onionrelay_control_port: Optional[int],
) -> None:
    service_id_path = state_dir / ONIONRELAY_DIR / ONION_SERVICE_ID_FILE
    key_blob_path = state_dir / ONIONRELAY_DIR / ONION_KEY_BLOB_FILE
    if service_id_path.exists() and key_blob_path.exists():
        return

    state_identity(state_dir)
    signal, socks, control = resolve_runtime_ports_for_mode(
        mode="onion",
        state_dir=state_dir,
        signal_port=signal_port,
        onionrelay_socks_port=onionrelay_socks_port,
        onionrelay_control_port=onionrelay_control_port,
    )
    cfg = RuntimeConfig(
        state_dir=state_dir,
        mode="onion",
        signal_host="127.0.0.1",
        signal_port=signal,
        advertise_host="127.0.0.1",
        retry_seconds=5.0,
        stun_server="stun:stun.l.google.com:19302",
        turn_server=None,
        turn_username=None,
        turn_password=None,
        turn_secret=None,
        turn_ttl_seconds=3600,
        turn_user="p4",
        onionrelay_bin=onionrelay_bin,
        onionrelay_socks_port=socks,
        onionrelay_control_port=control,
        no_stdin=True,
    )
    node = P4Node(cfg)
    try:
        await node._start_onionrelay(wait_bootstrap=False, quiet=True)
    finally:
        with contextlib.suppress(Exception):
            await node.shutdown()


def cmd_init(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    ident = state_identity(state_dir)
    contacts_path = state_dir / CONTACTS_FILE
    if not contacts_path.exists():
        atomic_write_json(contacts_path, [])
    print(f"Initialized {state_dir}")
    print(f"peer_id={ident.peer_id}")
    return 0


def cmd_invite(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    if args.mode == "onion":
        service_id_path = state_dir / ONIONRELAY_DIR / ONION_SERVICE_ID_FILE
        key_blob_path = state_dir / ONIONRELAY_DIR / ONION_KEY_BLOB_FILE
        if not (service_id_path.exists() and key_blob_path.exists()):
            asyncio.run(
                ensure_onion_identity_async(
                    state_dir=state_dir,
                    onionrelay_bin=args.onionrelay_bin,
                    signal_port=args.signal_port,
                    onionrelay_socks_port=args.onionrelay_socks_port,
                    onionrelay_control_port=args.onionrelay_control_port,
                )
            )
    invite = build_invite_from_state(state_dir, args.mode, args.advertise)
    print(json.dumps(invite, indent=2, sort_keys=True))
    return 0


def parse_invite_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.invite_file:
        raw = read_text_any_common_encoding(Path(args.invite_file))
        return json.loads(raw.lstrip("\ufeff"))
    if args.invite_json:
        return json.loads(args.invite_json.lstrip("\ufeff"))
    raise RuntimeError("Provide --invite-file or --invite-json")


def cmd_add_contact(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    me = state_identity(state_dir)
    invite = parse_invite_payload(args)

    contact = Contact.from_dict(invite)
    if contact.peer_id == me.peer_id:
        raise RuntimeError("Cannot add yourself as contact")

    contacts = load_contacts(state_dir)
    contacts[contact.peer_id] = contact
    save_contacts(state_dir, contacts)

    print(f"Added/updated contact {contact.peer_id}")
    return 0


async def cmd_run_async(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    signal_port, onionrelay_socks_port, onionrelay_control_port = resolve_runtime_ports_for_mode(
        mode=args.mode,
        state_dir=state_dir,
        signal_port=args.signal_port,
        onionrelay_socks_port=args.onionrelay_socks_port,
        onionrelay_control_port=args.onionrelay_control_port,
    )

    cfg = RuntimeConfig(
        state_dir=state_dir,
        mode=args.mode,
        signal_host=args.signal_host,
        signal_port=int(signal_port),
        advertise_host=args.advertise_host,
        retry_seconds=float(args.retry_seconds),
        stun_server=args.stun_server,
        turn_server=args.turn_server,
        turn_username=args.turn_username,
        turn_password=args.turn_password,
        turn_secret=args.turn_secret,
        turn_ttl_seconds=int(args.turn_ttl_seconds),
        turn_user=args.turn_user,
        onionrelay_bin=args.onionrelay_bin,
        onionrelay_socks_port=int(onionrelay_socks_port),
        onionrelay_control_port=int(onionrelay_control_port),
        no_stdin=args.no_stdin,
    )

    node = P4Node(cfg)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, node.stop)

    await node.run()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    return asyncio.run(cmd_run_async(args))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Persistent point-to-point node")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Create state directory + identity")
    p_init.add_argument("--state-dir", required=True)
    p_init.set_defaults(func=cmd_init)

    p_inv = sub.add_parser("invite", help="Print invite JSON")
    p_inv.add_argument("--state-dir", required=True)
    p_inv.add_argument("--mode", choices=["onion", "direct"], default="onion")
    p_inv.add_argument(
        "--advertise",
        default="127.0.0.1:18080",
        help="Only used in direct mode: host:port to advertise",
    )
    p_inv.add_argument(
        "--onionrelay-bin",
        help=(
            "Optional OnionRelay runtime path/name used when onion invite needs to auto-create "
            "onion identity files."
        ),
    )
    p_inv.add_argument("--signal-port", type=int, default=None)
    p_inv.add_argument("--onionrelay-socks-port", type=int, default=None)
    p_inv.add_argument("--onionrelay-control-port", type=int, default=None)
    p_inv.set_defaults(func=cmd_invite)

    p_add = sub.add_parser("add-contact", help="Import contact invite JSON")
    p_add.add_argument("--state-dir", required=True)
    p_add.add_argument("--invite-file")
    p_add.add_argument("--invite-json")
    p_add.set_defaults(func=cmd_add_contact)

    p_run = sub.add_parser("run", help="Run node")
    p_run.add_argument("--state-dir", required=True)
    p_run.add_argument("--mode", choices=["onion", "direct"], default="onion")
    p_run.add_argument("--signal-host", default="127.0.0.1")
    p_run.add_argument("--signal-port", type=int, default=None)
    p_run.add_argument(
        "--advertise-host",
        default="127.0.0.1",
        help="Used in direct mode invite",
    )
    p_run.add_argument("--retry-seconds", type=float, default=5.0)
    p_run.add_argument("--stun-server", default="stun:stun.l.google.com:19302")
    p_run.add_argument("--turn-server", help="Optional TURN URI, e.g. turn:host:3478?transport=udp")
    p_run.add_argument("--turn-username", help="TURN username")
    p_run.add_argument("--turn-password", help="TURN password")
    p_run.add_argument(
        "--turn-secret",
        help="Optional shared secret for TURN REST ephemeral credentials (coturn style)",
    )
    p_run.add_argument(
        "--turn-ttl-seconds",
        type=int,
        default=3600,
        help="TTL for auto-generated TURN REST credentials",
    )
    p_run.add_argument(
        "--turn-user",
        default="p4",
        help="User hint embedded in auto-generated TURN REST username",
    )
    p_run.add_argument(
        "--onionrelay-bin",
        help=(
            "Optional OnionRelay runtime path/name. If omitted, p4 auto-resolves bundled onionrelay."
        ),
    )
    p_run.add_argument("--onionrelay-socks-port", type=int, default=None)
    p_run.add_argument("--onionrelay-control-port", type=int, default=None)
    p_run.add_argument("--no-stdin", action="store_true")
    p_run.set_defaults(func=cmd_run)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())



