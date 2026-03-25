# Multi-Language SDK Bindings

All SDKs call the same native ABI in [p4_core.h](../include/p4_core.h).

## Native library build

- Windows: `.\scripts\build_p4_core.ps1`
- Linux/macOS: `./scripts/build_p4_core_unix.sh`

Output:
- Windows: `dist/p4_core/windows-x64/p4_core.dll`
- Linux: `dist/p4_core/linux-x64/libp4_core.so`
- macOS: `dist/p4_core/macos/libp4_core.dylib`

## SDK packages

- Python: `bindings/python` (`pyproject.toml`, package `p4_core/`)
- JavaScript/TypeScript: `bindings/javascript` (`package.json`)
- Java: `bindings/java` (`pom.xml`, JNA wrapper)
- C++: `bindings/cpp` (`CMakeLists.txt`, wrapper static lib)
- PHP: repo root `composer.json` (autoload -> `bindings/php/src`)

Maven namespace in this repo:
- `io.github.masterjx9`

Install commands:
- Python: `pip install p4_core`
- JS/TS: `npm i @pythonicit/p4-core-sdk`
- Java (Maven): `io.github.masterjx9:p4-core-sdk:0.2.1`
- PHP (Composer): `composer require masterjx9/p4-core-sdk`

Runtime requirements (all SDKs):
- Python/JS/Java packages bundle native core + runtime transport for:
  - Windows x64
  - Linux x64
  - macOS Intel (x64)
  - macOS Apple Silicon (arm64)
- PHP/C++ auto-resolve bundled runtime files from:
  - `native/p4_core/<platform>/`
  - transport runtime package payload
- Any SDK can be overridden with `P4_CORE_LIB`.

Each binding README has language-specific usage examples.

