#!/bin/bash
# Runs inside a bare ubuntu:24.04 container (.github/workflows/build.yml), from the repo:
#   docker run --rm -v "$PWD:/ndpt" -w /ndpt ubuntu:24.04 bash packaging/bare_linux.sh
# Starts the built TUI and GUI on a system with nothing added but Python (for smoke.py) and
# an X server, to see what they need from the system that the build didn't pack.
set -u
export DEBIAN_FRONTEND=noninteractive  # or a package that pulls in tzdata asks for a time zone

apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 xvfb >/dev/null \
    || exit 1

timeout 200 python3 packaging/smoke.py dist/ndpt-tui --demo || exit 1

# Xvfb itself, not xvfb-run, so that it can't wait on anything; and what it says, shown.
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
sleep 3
echo "Xvfb said: $(cat /tmp/xvfb.log)"
DISPLAY=:99 QT_QPA_PLATFORM=xcb SMOKE_SHOW=1 timeout 200 python3 packaging/smoke.py dist/ndpt-gui --demo
code=$?
[ "$code" = 124 ] && echo "smoke.py itself was still running after 200 s"
exit "$code"
