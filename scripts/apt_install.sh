#!/usr/bin/env bash
# Bounded apt install (fallback only). A stalled Ubuntu mirror ate 27 min of a 30-min job on 2026-11-06,
# so every phase has a timeout, and a stalled Azure mirror is swapped for archive.ubuntu.com once.
set -euo pipefail
APT="apt-get -qq -o Acquire::Retries=3 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20"
fetch() { sudo timeout 240 $APT update && sudo timeout 240 $APT install -y --no-install-recommends --download-only "$@"; }
fetch "$@" || { echo "apt mirror slow, switching to archive.ubuntu.com"; sudo sed -i 's#azure.archive.ubuntu.com#archive.ubuntu.com#g' /etc/apt/sources.list.d/*.sources; fetch "$@"; }
sudo $APT install -y --no-install-recommends "$@" >/dev/null
