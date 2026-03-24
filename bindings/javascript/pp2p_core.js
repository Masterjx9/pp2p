/*
 * Node.js bridge for the Rust PP2P C ABI.
 */

const ffi = require("ffi-napi");
const ref = require("ref-napi");
const fs = require("fs");
const path = require("path");

function defaultLibPath() {
  if (process.env.PP2P_CORE_LIB) {
    return process.env.PP2P_CORE_LIB;
  }

  let bundled = null;
  if (process.platform === "win32" && process.arch === "x64") {
    bundled = path.resolve(__dirname, "native", "win32-x64", "pp2p_core.dll");
  } else if (process.platform === "darwin" && process.arch === "x64") {
    bundled = path.resolve(__dirname, "native", "darwin-x64", "libpp2p_core.dylib");
  } else if (process.platform === "darwin" && process.arch === "arm64") {
    bundled = path.resolve(__dirname, "native", "darwin-arm64", "libpp2p_core.dylib");
  } else if (process.platform === "linux" && process.arch === "x64") {
    bundled = path.resolve(__dirname, "native", "linux-x64", "libpp2p_core.so");
  }

  if (bundled && fs.existsSync(bundled)) {
    return bundled;
  }

  let rel = null;
  if (process.platform === "win32") rel = "dist/pp2p_core/windows-x64/pp2p_core.dll";
  else if (process.platform === "darwin") rel = "dist/pp2p_core/macos/libpp2p_core.dylib";
  else rel = "dist/pp2p_core/linux-x64/libpp2p_core.so";

  const candidates = [
    path.resolve(process.cwd(), rel),
    path.resolve(__dirname, "..", "..", rel),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  throw new Error(
    `PP2P native library not found for ${process.platform}/${process.arch}. ` +
      `Set PP2P_CORE_LIB or install a package build that includes native binaries.`
  );
}

class Pp2pCore {
  constructor(libPath = defaultLibPath()) {
    this.lib = ffi.Library(libPath, {
      pp2p_generate_identity_json: ["pointer", []],
      pp2p_peer_id_from_public_key_b64: ["pointer", ["string"]],
      pp2p_sign_envelope_json: ["pointer", ["string", "string", "string", "string", "uint64", "string"]],
      pp2p_verify_envelope_json: ["uchar", ["string", "string", "uint64", "uint64"]],
      pp2p_last_error_message: ["pointer", []],
      pp2p_free_string: ["void", ["pointer"]],
    });
  }

  _takeString(ptr) {
    if (ref.isNull(ptr)) {
      throw new Error(this.lastError());
    }
    try {
      return ref.readCString(ptr, 0);
    } finally {
      this.lib.pp2p_free_string(ptr);
    }
  }

  lastError() {
    return this._takeString(this.lib.pp2p_last_error_message());
  }

  generateIdentity() {
    return JSON.parse(this._takeString(this.lib.pp2p_generate_identity_json()));
  }

  peerIdFromPublicKeyB64(publicKeyB64) {
    return this._takeString(this.lib.pp2p_peer_id_from_public_key_b64(publicKeyB64));
  }

  signEnvelope({ privateKeyB64, senderPeerId, recipientPeerId, payload, timestampMs, nonce }) {
    const ts = typeof timestampMs === "number" ? timestampMs : Date.now();
    const ptr = this.lib.pp2p_sign_envelope_json(
      privateKeyB64,
      senderPeerId,
      recipientPeerId,
      JSON.stringify(payload),
      ts,
      nonce
    );
    return JSON.parse(this._takeString(ptr));
  }

  verifyEnvelope({ envelope, signerPublicKeyB64, maxSkewMs = 60000, nowMs }) {
    const now = typeof nowMs === "number" ? nowMs : Date.now();
    const ok = this.lib.pp2p_verify_envelope_json(
      JSON.stringify(envelope),
      signerPublicKeyB64,
      now,
      maxSkewMs
    );
    if (ok === 1) {
      return true;
    }
    throw new Error(this.lastError());
  }
}

module.exports = { Pp2pCore };
