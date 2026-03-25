const fs = require("fs");
const path = require("path");

function platformDir(platform, arch) {
  if (platform === "win32" && arch === "x64") return "win32-x64";
  if (platform === "linux" && arch === "x64") return "linux-x64";
  if (platform === "darwin" && arch === "x64") return "darwin-x64";
  if (platform === "darwin" && arch === "arm64") return "darwin-arm64";
  return null;
}

function libName(platform) {
  if (platform === "win32") return "p4_core.dll";
  if (platform === "darwin") return "libp4_core.dylib";
  return "libp4_core.so";
}

function onionrelayName(platform) {
  if (platform === "win32") return "onionrelay.exe";
  return "onionrelay";
}

if (process.env.P4_CORE_LIB) {
  process.exit(0);
}

const dir = platformDir(process.platform, process.arch);
if (!dir) {
  console.error(
    `[p4-core-sdk] Unsupported platform ${process.platform}/${process.arch}. ` +
      "Set P4_CORE_LIB to a valid native library path."
  );
  process.exit(1);
}

const expected = path.resolve(__dirname, "..", "native", dir, libName(process.platform));
if (!fs.existsSync(expected)) {
  console.error(
    `[p4-core-sdk] Missing bundled native library: ${expected}. ` +
      "Reinstall package or set P4_CORE_LIB."
  );
  process.exit(1);
}

if (!process.env.P4_ONIONRELAY_BIN) {
  const expectedOnionrelay = path.resolve(__dirname, "..", "onionrelay", dir, onionrelayName(process.platform));
  if (!fs.existsSync(expectedOnionrelay)) {
    console.error(
      `[p4-core-sdk] Missing bundled onionrelay runtime: ${expectedOnionrelay}. ` +
        "Reinstall package or set P4_ONIONRELAY_BIN."
    );
    process.exit(1);
  }
}
