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
  if (platform === "win32") return "pp2p_core.dll";
  if (platform === "darwin") return "libpp2p_core.dylib";
  return "libpp2p_core.so";
}

if (process.env.PP2P_CORE_LIB) {
  process.exit(0);
}

const dir = platformDir(process.platform, process.arch);
if (!dir) {
  console.error(
    `[pp2p-core-sdk] Unsupported platform ${process.platform}/${process.arch}. ` +
      "Set PP2P_CORE_LIB to a valid native library path."
  );
  process.exit(1);
}

const expected = path.resolve(__dirname, "..", "native", dir, libName(process.platform));
if (!fs.existsSync(expected)) {
  console.error(
    `[pp2p-core-sdk] Missing bundled native library: ${expected}. ` +
      "Reinstall package or set PP2P_CORE_LIB."
  );
  process.exit(1);
}
