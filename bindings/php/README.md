# PHP SDK (FFI)

Composer package metadata and wrapper class:
- [P4Core.php](src/P4Core.php)

## Install

```bash
composer require masterjx9/p4-core-sdk
```

## Runtime requirements

- PHP 8.1+ with `ffi` enabled
- Bundled native runtime payload is auto-resolved for:
  - Windows x64
  - Linux x64
  - macOS Intel (x64)
  - macOS Apple Silicon (arm64)

Enable `ffi` in `php.ini`, then:

```bash
composer install
php bindings/php/example.php
```

Optional override:
- set `P4_CORE_LIB` to an absolute path to your own native library.
