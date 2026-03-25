/*
 * Node.js bridge for the Rust P4 C ABI.
 */

const ffi = require("ffi-napi");
const ref = require("ref-napi");
const fs = require("fs");
const path = require("path");

function platformDir(platform, arch) {
  if (platform === "win32" && arch === "x64") return "win32-x64";
  if (platform === "linux" && arch === "x64") return "linux-x64";
  if (platform === "darwin" && arch === "x64") return "darwin-x64";
  if (platform === "darwin" && arch === "arm64") return "darwin-arm64";
  return null;
}

function coreLibName(platform) {
  if (platform === "win32") return "p4_core.dll";
  if (platform === "darwin") return "libp4_core.dylib";
  return "libp4_core.so";
}

function onionrelayName(platform) {
  if (platform === "win32") return "onionrelay.exe";
  return "onionrelay";
}

function defaultLibPath() {
  if (process.env.P4_CORE_LIB) {
    return process.env.P4_CORE_LIB;
  }

  const dir = platformDir(process.platform, process.arch);
  const bundled = dir
    ? path.resolve(__dirname, "native", dir, coreLibName(process.platform))
    : null;

  if (bundled && fs.existsSync(bundled)) {
    return bundled;
  }

  let rel = null;
  if (process.platform === "win32") rel = "dist/p4_core/windows-x64/p4_core.dll";
  else if (process.platform === "darwin") rel = "dist/p4_core/macos/libp4_core.dylib";
  else rel = "dist/p4_core/linux-x64/libp4_core.so";

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
    `P4 native library not found for ${process.platform}/${process.arch}. ` +
      `Set P4_CORE_LIB or install a package build that includes native binaries.`
  );
}

function defaultOnionrelayPath() {
  if (process.env.P4_ONIONRELAY_BIN) {
    return process.env.P4_ONIONRELAY_BIN;
  }

  const dir = platformDir(process.platform, process.arch);
  const bundled = dir
    ? path.resolve(__dirname, "onionrelay", dir, onionrelayName(process.platform))
    : null;
  if (bundled && fs.existsSync(bundled)) {
    return bundled;
  }

  const exe = onionrelayName(process.platform);
  const candidates = [
    path.resolve(process.cwd(), "onionrelay", dir || "", exe),
    path.resolve(process.cwd(), "dist", exe),
    path.resolve(process.cwd(), "onionrelay_src", "src", "app", exe),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  throw new Error(
    `P4 onionrelay runtime not found for ${process.platform}/${process.arch}. ` +
      `Set P4_ONIONRELAY_BIN or install a package build that includes onionrelay.`
  );
}

function resolveOnionrelayPath(pathOverride) {
  const candidate = pathOverride || defaultOnionrelayPath();
  if (path.isAbsolute(candidate) || candidate.includes(path.sep)) {
    if (!fs.existsSync(candidate)) {
      throw new Error(`OnionRelay runtime not found: ${candidate}`);
    }
    return candidate;
  }
  return candidate;
}

class P4Core {
  constructor(libPath = defaultLibPath()) {
    this.lib = ffi.Library(libPath, {
      p4_generate_identity_json: ["pointer", []],
      p4_peer_id_from_public_key_b64: ["pointer", ["string"]],
      p4_sign_envelope_json: ["pointer", ["string", "string", "string", "string", "uint64", "string"]],
      p4_verify_envelope_json: ["uchar", ["string", "string", "uint64", "uint64"]],
      p4_last_error_message: ["pointer", []],
      p4_free_string: ["void", ["pointer"]],
    });
  }

  _takeString(ptr) {
    if (ref.isNull(ptr)) {
      throw new Error(this.lastError());
    }
    try {
      return ref.readCString(ptr, 0);
    } finally {
      this.lib.p4_free_string(ptr);
    }
  }

  lastError() {
    return this._takeString(this.lib.p4_last_error_message());
  }

  generateIdentity() {
    return JSON.parse(this._takeString(this.lib.p4_generate_identity_json()));
  }

  peerIdFromPublicKeyB64(publicKeyB64) {
    return this._takeString(this.lib.p4_peer_id_from_public_key_b64(publicKeyB64));
  }

  signEnvelope({ privateKeyB64, senderPeerId, recipientPeerId, payload, timestampMs, nonce }) {
    const ts = typeof timestampMs === "number" ? timestampMs : Date.now();
    const ptr = this.lib.p4_sign_envelope_json(
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
    const ok = this.lib.p4_verify_envelope_json(
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

module.exports = { P4Core, resolveOnionrelayPath };


