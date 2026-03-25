# Java SDK (JNA)

Maven module with JNA wrapper class:
- [P4Core.java](src/main/java/io/github/masterjx9/p4/P4Core.java)

Namespace/groupId configured:
- `io.github.masterjx9`

## Install (Maven)

```xml
<dependency>
  <groupId>io.github.masterjx9</groupId>
  <artifactId>p4-core-sdk</artifactId>
  <version>0.2.1</version>
</dependency>
```

## Runtime requirements

- Java 11+
- Bundled native runtime payload is auto-loaded for:
  - Windows x64
  - Linux x64
  - macOS Intel (x64)
  - macOS Apple Silicon (arm64)

## Usage

```java
import io.github.masterjx9.p4.P4Core;

P4Core core = new P4Core(); // auto-load bundled native lib
String identityJson = core.generateIdentityJson();
```

Optional override:
- set `P4_CORE_LIB` to an absolute path to your own native library.

