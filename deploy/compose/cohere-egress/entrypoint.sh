#!/usr/bin/env bash
# Bring up AmneziaWG (best-effort) then run tinyproxy in the foreground.
#
# Why this layout:
# * AmneziaWG carries upstream cohere traffic only. AllowedIPs in awg0.conf
#   is "0.0.0.0/0, ::/0", so every outbound packet from this container would
#   normally hit the tunnel — including the return packets to the docker
#   bridge clients on :8888. We mark inbound docker-bridge traffic and route
#   the replies via the main table so they exit through eth0 instead of awg0.
# * If awg0.conf is missing we still run tinyproxy. This lets local smoke
#   tests and CI build verification work without a real VPN config.

set -euo pipefail

CONF="${AWG_CONF:-/etc/amneziawg/awg0.conf}"
INTERFACE="${AWG_INTERFACE:-awg0}"
MARK="${AWG_RETURN_MARK:-0x100}"
RULE_PREF="${AWG_RULE_PREF:-100}"

log() { printf '[cohere-egress] %s\n' "$*" >&2; }

start_amneziawg() {
    if [ ! -f "$CONF" ]; then
        log "no AmneziaWG config at ${CONF}; running tinyproxy without VPN (test/dev mode)"
        return 0
    fi

    log "starting AmneziaWG interface ${INTERFACE} from ${CONF}"
    if ! awg-quick up "$CONF"; then
        log "awg-quick up failed; continuing without VPN — cohere calls will reach the network unproxied"
        return 0
    fi

    # Return-path routing for docker-bridge clients.
    # Mark packets that arrived via eth0 (i.e. from another docker container
    # using us as a proxy); send their replies via the main routing table
    # instead of the AllowedIPs=0.0.0.0/0 wg table.
    if iptables -t mangle -C PREROUTING -i eth0 -j MARK --set-mark "$MARK" 2>/dev/null; then
        log "mangle PREROUTING mark rule already present"
    else
        iptables -t mangle -A PREROUTING -i eth0 -j MARK --set-mark "$MARK" \
            && log "added iptables mangle PREROUTING mark ${MARK} on eth0" \
            || log "iptables mangle add failed (continuing)"
    fi

    if ip rule list | grep -q "fwmark ${MARK}"; then
        log "ip rule for fwmark ${MARK} already present"
    else
        ip rule add fwmark "$MARK" lookup main pref "$RULE_PREF" \
            && log "added ip rule fwmark ${MARK} lookup main pref ${RULE_PREF}" \
            || log "ip rule add failed (continuing)"
    fi
}

start_amneziawg

log "starting tinyproxy on :8888"
exec tinyproxy -d -c /etc/tinyproxy/tinyproxy.conf
