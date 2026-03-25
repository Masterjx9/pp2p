#!/bin/sh

if command -v autoreconf; then
  # Newer autoconf versions (e.g. 2.73) emit warnings for legacy macros in
  # Tor's configure.ac; treating warnings as errors breaks CI bootstrap.
  opt="-i -f -W all"

  for i in "$@"; do
    case "$i" in
      -v)
        opt="${opt} -v"
        ;;
    esac
  done

  # shellcheck disable=SC2086
  exec autoreconf $opt
fi

set -e

# Run this to generate all the initial makefiles, etc.
aclocal -I m4 && \
	autoheader && \
	autoconf && \
	automake --add-missing --copy
