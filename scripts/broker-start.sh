#!/bin/sh
set -eu
secret=$(cat /run/secrets/broker_password)
case "$secret" in *[!0-9a-f]*|'') exit 1;; esac
[ "${#secret}" -ge 32 ]
umask 077
{ printf 'bind 0.0.0.0\nprotected-mode yes\nport 6379\nrequirepass %s\n' "$secret"; printf 'appendonly yes\nappendfsync everysec\ndir /data\nmaxmemory 96mb\nmaxmemory-policy noeviction\nsave ""\n'; } > /tmp/redis.conf
exec redis-server /tmp/redis.conf
