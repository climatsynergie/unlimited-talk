#!/bin/sh
# Only on the dedicated staging host. Do not flush Docker/UFW rules.
set -eu
: "${STAGING_DB_CIDR:?Set the private staging database CIDR}"
iptables -N UT-STAGING-EGRESS 2>/dev/null || true
ensure_rule() {
    iptables -C UT-STAGING-EGRESS "$@" 2>/dev/null || iptables -A UT-STAGING-EGRESS "$@"
}
ensure_rule -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
ensure_rule -d 172.30.8.0/24 -j RETURN
ensure_rule -d "$STAGING_DB_CIDR" -p tcp --dport 25060 -j RETURN
# Insert before an existing terminal DROP; never grant general WAN access.
if [ -n "${STAGING_SPACES_CIDR:-}" ]; then
    iptables -C UT-STAGING-EGRESS -d "$STAGING_SPACES_CIDR" -p tcp --dport 443 -j RETURN 2>/dev/null || \
        iptables -I UT-STAGING-EGRESS 1 -d "$STAGING_SPACES_CIDR" -p tcp --dport 443 -j RETURN
fi
ensure_rule -j DROP
iptables -C DOCKER-USER -s 172.30.8.0/24 -j UT-STAGING-EGRESS 2>/dev/null || \
    iptables -I DOCKER-USER 1 -s 172.30.8.0/24 -j UT-STAGING-EGRESS
