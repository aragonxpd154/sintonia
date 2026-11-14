#!/bin/sh
cd "$(dirname "$0")" && PYTHONDONTWRITEBYTECODE=1 exec python3 -m arkt "$@"
