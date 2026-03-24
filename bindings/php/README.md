# PHP SDK (FFI)

Composer package metadata and wrapper class:
- [Pp2pCore.php](/c:/Users/RKerrigan/Projects/pp2p/bindings/php/src/Pp2pCore.php)

Build native core from repo root first.

## Install

```bash
composer require masterjx9/pp2p-core-sdk
```

## Runtime requirements

- PHP 8.1+ with `ffi` enabled
- Native PP2P core library (`pp2p_core.dll` / `libpp2p_core.so` / `libpp2p_core.dylib`)

Enable `ffi` in `php.ini`, then:

```bash
composer install
php bindings/php/example.php
```
