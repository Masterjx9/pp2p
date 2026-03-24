# Multi-Language SDK Bindings

All SDKs call the same native ABI in [pp2p_core.h](/c:/Users/RKerrigan/Projects/pp2p/include/pp2p_core.h).

## Native library build

- Windows: `.\scripts\build_pp2p_core.ps1`
- Linux/macOS: `./scripts/build_pp2p_core_unix.sh`

Output:
- Windows: `dist/pp2p_core/windows-x64/pp2p_core.dll`
- Linux: `dist/pp2p_core/linux-x64/libpp2p_core.so`
- macOS: `dist/pp2p_core/macos/libpp2p_core.dylib`

## SDK packages

- Python: `bindings/python` (`pyproject.toml`, package `pp2p_core/`)
- JavaScript/TypeScript: `bindings/javascript` (`package.json`)
- Java: `bindings/java` (`pom.xml`, JNA wrapper)
- C++: `bindings/cpp` (`CMakeLists.txt`, wrapper static lib)
- PHP: repo root `composer.json` (autoload -> `bindings/php/src`)

Maven namespace in this repo:
- `io.github.masterjx9`

Install commands:
- Python: `pip install pp2p_core`
- JS/TS: `npm i @pythonicit/pp2p-core-sdk`
- Java (Maven): `io.github.masterjx9:pp2p-core-sdk:0.1.0`
- PHP (Composer): `composer require masterjx9/pp2p-core-sdk`

Runtime requirements (all SDKs):
- Python/JS packages bundle native binaries for:
  - Windows x64
  - Linux x64
  - macOS Intel (x64)
  - macOS Apple Silicon (arm64)
- Java/PHP/C++ currently require a native library path (`PP2P_CORE_LIB` or explicit path argument).

Each binding README has language-specific usage examples.
