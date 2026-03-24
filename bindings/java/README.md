# Java SDK (JNA)

Maven module with JNA wrapper class:
- [Pp2pCore.java](/c:/Users/RKerrigan/Projects/pp2p/bindings/java/src/main/java/io/github/masterjx9/pp2p/Pp2pCore.java)

Namespace/groupId configured:
- `io.github.masterjx9`

## Install (Maven)

```xml
<dependency>
  <groupId>io.github.masterjx9</groupId>
  <artifactId>pp2p-core-sdk</artifactId>
  <version>0.1.0</version>
</dependency>
```

## Runtime requirements

- Java 11+
- Native PP2P core library (`pp2p_core.dll` / `libpp2p_core.so` / `libpp2p_core.dylib`)

## Build (local module)

Build native core from repo root first:
```bash
./scripts/build_pp2p_core_unix.sh
```
or on Windows:
```powershell
.\scripts\build_pp2p_core.ps1
```

Then build Java module:
```bash
cd bindings/java
mvn package
```

## Usage

```java
import io.github.masterjx9.pp2p.Pp2pCore;

Pp2pCore core = new Pp2pCore("C:/path/to/pp2p_core.dll");
String identityJson = core.generateIdentityJson();
```
