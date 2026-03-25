#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${ROOT_DIR}/onionrelay_src"
OUT_DIR="${1:-${ROOT_DIR}/dist}"
OUT_NAME="${2:-onionrelay}"

if [[ ! -d "${SRC_DIR}" ]]; then
  echo "Missing source directory: ${SRC_DIR}" >&2
  exit 1
fi

if command -v getconf >/dev/null 2>&1; then
  JOBS="$(getconf _NPROCESSORS_ONLN || echo 4)"
else
  JOBS=4
fi

CONFIG_FLAGS=(
  --disable-asciidoc
  --disable-module-relay
  --disable-module-dirauth
  --disable-module-pow
)

if [[ "$(uname -s)" == "Darwin" ]]; then
  OPENSSL_PREFIX="$(brew --prefix openssl@3 2>/dev/null || true)"
  LIBEVENT_PREFIX="$(brew --prefix libevent 2>/dev/null || true)"
  XZ_PREFIX="$(brew --prefix xz 2>/dev/null || true)"
  ZSTD_PREFIX="$(brew --prefix zstd 2>/dev/null || true)"

  for prefix in "$OPENSSL_PREFIX" "$LIBEVENT_PREFIX" "$XZ_PREFIX" "$ZSTD_PREFIX"; do
    if [[ -n "${prefix}" ]]; then
      export PKG_CONFIG_PATH="${prefix}/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
      export CPPFLAGS="-I${prefix}/include ${CPPFLAGS:-}"
      export LDFLAGS="-L${prefix}/lib ${LDFLAGS:-}"
    fi
  done
fi

pushd "${SRC_DIR}" >/dev/null

# Clean stale dependency metadata that can be copied from Windows/MSYS builds.
# These files can make GNU make fail on Linux with "multiple target patterns".
find . -type d -name .deps -prune -exec rm -rf {} + || true
find . -name "*.Po" -delete || true
find . -name "*.Plo" -delete || true
rm -f config.log config.status || true
chmod +x ./scripts/build/combine_libs || true

# Generate configure script when building from source snapshots that don't
# include pre-generated autotools outputs.
if [[ ! -x "./configure" ]]; then
  chmod +x ./autogen.sh
  if ! ./autogen.sh; then
    # Some environments fail on autogen warnings treated as errors.
    if command -v autoreconf >/dev/null 2>&1; then
      autoreconf -i -f -W all
    else
      echo "autogen failed and autoreconf is unavailable" >&2
      exit 1
    fi
  fi
fi

make distclean >/dev/null 2>&1 || true
./configure "${CONFIG_FLAGS[@]}"
make -j"${JOBS}"

SRC_BIN="$(find "${SRC_DIR}/src/app" -maxdepth 1 -type f -perm -111 | head -n1)"
if [[ -z "${SRC_BIN}" ]]; then
  echo "No executable found under ${SRC_DIR}/src/app after build" >&2
  exit 1
fi
cp -f "${SRC_BIN}" "${SRC_DIR}/src/app/onionrelay"

SRC_LIB="$(find "${SRC_DIR}" -maxdepth 1 -type f -name 'lib*.a' | head -n1)"
if [[ -n "${SRC_LIB}" ]]; then
  cp -f "${SRC_LIB}" "${SRC_DIR}/libonionrelay.a"
fi
popd >/dev/null

mkdir -p "${OUT_DIR}"
cp -f "${SRC_DIR}/src/app/onionrelay" "${OUT_DIR}/${OUT_NAME}"
chmod +x "${OUT_DIR}/${OUT_NAME}"

echo "Built ${OUT_DIR}/${OUT_NAME}"
