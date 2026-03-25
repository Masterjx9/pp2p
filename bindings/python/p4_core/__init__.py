"""
Python ctypes bridge for the Rust P4 core C ABI.
"""

from __future__ import annotations

import ctypes
import json
import os
import pathlib
import shutil
import time
from typing import Any


def _platform_lib_name() -> str:
    if os.name == "nt":
        return "p4_core.dll"
    if os.uname().sysname == "Darwin":
        return "libp4_core.dylib"
    return "libp4_core.so"


def _platform_onionrelay_name() -> str:
    if os.name == "nt":
        return "onionrelay.exe"
    return "onionrelay"


def _platform_native_dir() -> str | None:
    arch = os.uname().machine.lower() if os.name != "nt" else os.environ.get("PROCESSOR_ARCHITECTURE", "").lower()
    if os.name == "nt":
        if "64" in arch:
            return "win32-x64"
        return None
    if os.uname().sysname == "Darwin":
        if arch in {"arm64", "aarch64"}:
            return "darwin-arm64"
        if arch in {"x86_64", "amd64"}:
            return "darwin-x64"
        return None
    if arch in {"x86_64", "amd64"}:
        return "linux-x64"
    return None


def _default_library_path() -> str:
    env = os.environ.get("P4_CORE_LIB")
    if env:
        return env

    lib_name = _platform_lib_name()
    here = pathlib.Path(__file__).resolve().parent

    # Preferred: bundled library inside wheel.
    native_dir = _platform_native_dir()
    bundled = here / "native" / native_dir / lib_name if native_dir else here / "native" / lib_name
    if bundled.exists():
        return str(bundled)

    legacy_bundled = here / "native" / lib_name
    if legacy_bundled.exists():
        return str(legacy_bundled)

    # Fallback for local source-tree runs.
    if os.name == "nt":
        rel = pathlib.Path("dist") / "p4_core" / "windows-x64" / "p4_core.dll"
    elif os.uname().sysname == "Darwin":
        rel = pathlib.Path("dist") / "p4_core" / "macos" / "libp4_core.dylib"
    else:
        rel = pathlib.Path("dist") / "p4_core" / "linux-x64" / "libp4_core.so"

    candidates = [
        pathlib.Path(__file__).resolve().parents[3] / rel,
        pathlib.Path.cwd() / rel,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    # Return best-guess bundled path so ctypes emits a useful file-not-found.
    return str(bundled)


def _default_onionrelay_path() -> str:
    env = os.environ.get("P4_ONIONRELAY_BIN")
    if env:
        return env

    exe_name = _platform_onionrelay_name()
    here = pathlib.Path(__file__).resolve().parent
    native_dir = _platform_native_dir()
    bundled = here / "onionrelay" / native_dir / exe_name if native_dir else here / "onionrelay" / exe_name
    if bundled.exists():
        return str(bundled)

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    candidates = [
        repo_root / "onionrelay" / (native_dir or "") / exe_name,
        repo_root / "dist" / exe_name,
        repo_root / "onionrelay_src" / "src" / "app" / exe_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return str(bundled)


def resolve_onionrelay_binary_path(onionrelay_bin: str | None = None) -> str:
    candidate = onionrelay_bin or _default_onionrelay_path()
    resolved = shutil.which(candidate) or candidate
    path = pathlib.Path(resolved)
    if path.exists():
        if os.name == "nt" and path.suffix.lower() != ".exe":
            raise OSError(f"OnionRelay binary must be .exe on Windows: {path}")
        return str(path)
    if shutil.which(resolved):
        return resolved
    raise OSError(
        "OnionRelay binary not found. Set P4_ONIONRELAY_BIN or install a package build "
        "that bundles onionrelay."
    )


class P4CoreError(RuntimeError):
    pass


class P4Core:
    def __init__(self, lib_path: str | None = None) -> None:
        path = lib_path or _default_library_path()
        self._lib = ctypes.CDLL(path)

        self._lib.p4_generate_identity_json.restype = ctypes.c_void_p
        self._lib.p4_peer_id_from_public_key_b64.argtypes = [ctypes.c_char_p]
        self._lib.p4_peer_id_from_public_key_b64.restype = ctypes.c_void_p
        self._lib.p4_sign_envelope_json.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.c_char_p,
        ]
        self._lib.p4_sign_envelope_json.restype = ctypes.c_void_p
        self._lib.p4_verify_envelope_json.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.c_uint64,
        ]
        self._lib.p4_verify_envelope_json.restype = ctypes.c_ubyte
        self._lib.p4_last_error_message.restype = ctypes.c_void_p
        self._lib.p4_free_string.argtypes = [ctypes.c_void_p]

    def _take_string(self, ptr: int | None) -> str:
        if not ptr:
            raise P4CoreError(self.last_error())
        try:
            raw = ctypes.cast(ptr, ctypes.c_char_p).value or b""
            return raw.decode("utf-8")
        finally:
            self._lib.p4_free_string(ptr)

    def last_error(self) -> str:
        ptr = self._lib.p4_last_error_message()
        if not ptr:
            return "unknown error"
        return self._take_string(ptr)

    def generate_identity(self) -> dict[str, Any]:
        ptr = self._lib.p4_generate_identity_json()
        return json.loads(self._take_string(ptr))

    def peer_id_from_public_key_b64(self, public_key_b64: str) -> str:
        ptr = self._lib.p4_peer_id_from_public_key_b64(public_key_b64.encode("utf-8"))
        return self._take_string(ptr)

    def sign_envelope(
        self,
        private_key_b64: str,
        sender_peer_id: str,
        recipient_peer_id: str,
        payload: dict[str, Any],
        nonce: str,
        timestamp_ms: int | None = None,
    ) -> dict[str, Any]:
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        ptr = self._lib.p4_sign_envelope_json(
            private_key_b64.encode("utf-8"),
            sender_peer_id.encode("utf-8"),
            recipient_peer_id.encode("utf-8"),
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            ctypes.c_uint64(timestamp_ms),
            nonce.encode("utf-8"),
        )
        return json.loads(self._take_string(ptr))

    def verify_envelope(
        self,
        envelope: dict[str, Any],
        signer_public_key_b64: str,
        max_skew_ms: int = 60_000,
        now_ms: int | None = None,
    ) -> bool:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        ok = self._lib.p4_verify_envelope_json(
            json.dumps(envelope, separators=(",", ":")).encode("utf-8"),
            signer_public_key_b64.encode("utf-8"),
            ctypes.c_uint64(now_ms),
            ctypes.c_uint64(max_skew_ms),
        )
        if ok == 1:
            return True
        raise P4CoreError(self.last_error())


__all__ = ["P4Core", "P4CoreError", "resolve_onionrelay_binary_path"]


