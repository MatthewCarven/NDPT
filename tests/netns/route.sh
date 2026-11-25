#!/bin/bash
# Builds a tiny routed network out of Linux network namespaces and probes it with
# NDPT's Linux prober: as root (raw sockets), then as an ordinary user (ping sockets).
# Real "time exceeded" and "unreachable" answers, IPv4 and IPv6, no internet needed.
#
#   client 10.1.0.2   --   10.1.0.1 router 10.2.0.1   --   10.2.0.2 dest
#          fd00:1::2       fd00:1::1       fd00:2::1       fd00:2::2
#
# Needs root:  sudo PYTHON="$(command -v python)" bash tests/netns/route.sh
# From Windows, in WSL:  wsl -d Ubuntu-24.04 -u root -- bash tests/netns/route.sh
# With a command after it, runs that in the client's namespace instead of the checks.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
python="${PYTHON:-python3}"
uid="${SUDO_UID:-65534}" gid="${SUDO_GID:-65534}"  # the ordinary user: whoever ran sudo, or nobody
ns="ndpt$$"

cleanup() { for n in c r d; do ip netns del "$ns-$n" 2>/dev/null || true; done; }
trap cleanup EXIT
inside() { local n="$1"; shift; ip netns exec "$ns-$n" "$@"; }

for n in c r d; do
    ip netns add "$ns-$n"
    inside "$n" sysctl -qw net.ipv6.conf.default.accept_dad=0 net.ipv6.conf.all.accept_dad=0
    ip -n "$ns-$n" link set lo up
done
ip -n "$ns-r" link add eth0 type veth peer name eth0 netns "$ns-c"
ip -n "$ns-r" link add eth1 type veth peer name eth0 netns "$ns-d"
ip -n "$ns-c" addr add 10.1.0.2/24 dev eth0 && ip -n "$ns-c" addr add fd00:1::2/64 dev eth0
ip -n "$ns-r" addr add 10.1.0.1/24 dev eth0 && ip -n "$ns-r" addr add fd00:1::1/64 dev eth0
ip -n "$ns-r" addr add 10.2.0.1/24 dev eth1 && ip -n "$ns-r" addr add fd00:2::1/64 dev eth1
ip -n "$ns-d" addr add 10.2.0.2/24 dev eth0 && ip -n "$ns-d" addr add fd00:2::2/64 dev eth0
ip -n "$ns-c" link set eth0 up && ip -n "$ns-d" link set eth0 up
ip -n "$ns-r" link set eth0 up && ip -n "$ns-r" link set eth1 up
ip -n "$ns-c" route add default via 10.1.0.1 && ip -n "$ns-c" -6 route add default via fd00:1::1
ip -n "$ns-d" route add default via 10.2.0.1 && ip -n "$ns-d" -6 route add default via fd00:2::1
inside r sysctl -qw net.ipv4.ip_forward=1 net.ipv6.conf.all.forwarding=1 \
    net.ipv4.icmp_ratelimit=0 net.ipv6.icmp.ratelimit=0
if [ $# -gt 0 ]; then
    inside c "$@"
    exit
fi

# Neighbour discovery first, so the first IPv6 probes don't wait out a lost solicitation (1 s).
inside c ping -q -c1 -W3 10.2.0.2 >/dev/null && inside c ping -q -c1 -W3 fd00:2::2 >/dev/null

status=0
echo "== as root: a new namespace lets nobody use ping sockets, so raw sockets"
inside c env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$repo" "$python" "$here/check_route.py" raw || status=1
sleep 1.5  # the router's "no route" needs a second's tokens after the first run's errors
echo "== as uid $uid, with ping sockets allowed in the client's namespace"
inside c sysctl -qw net.ipv4.ping_group_range="0 2147483647"
inside c setpriv --reuid="$uid" --regid="$gid" --clear-groups \
    env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$repo" "$python" "$here/check_route.py" ping || status=1
exit $status
