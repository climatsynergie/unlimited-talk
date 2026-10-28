#!/bin/bash
set -euo pipefail
[ "$(id -u)" = 0 ]
[ -f /run/ut-image-build-authorized ]
. /etc/os-release
[ "$ID" = opensuse-leap ] && [ "$VERSION_ID" = 16.0 ]
[ ! -e /var/lib/cloud/instance ] && [ ! -L /var/lib/cloud/instance ] || {
  echo 'Refusing to modify an already initialized cloud instance'; exit 1;
}
for service in asterisk apache2 mariadb; do
  if systemctl is-active --quiet "$service"; then
    echo 'Refusing to modify a running telephony service'; exit 1;
  fi
done
[ -f /etc/cloud/cloud.cfg.d/99-unlimited-talk.cfg ]
/usr/sbin/sshd -t
/usr/sbin/sshd -T | grep -qx 'passwordauthentication no'
/usr/sbin/sshd -T | grep -qx 'permitrootlogin no'
usermod --password '*' root
for type in rsa ecdsa ed25519 dsa; do
  rm -f "/etc/ssh/ssh_host_${type}_key" "/etc/ssh/ssh_host_${type}_key.pub"
done
rm -f /root/.ssh/authorized_keys /root/.bash_history
zypper --non-interactive clean --all >/dev/null
rm -rf /var/tmp/ut-build-repos
cloud-init clean --logs --machine-id --seed --configs network
restorecon -RF /etc/cloud /etc/ssh /etc/machine-id
fstrim / || true
sync
printf 'CLOUD_TEMPLATE_SEALED\n'
systemctl poweroff
