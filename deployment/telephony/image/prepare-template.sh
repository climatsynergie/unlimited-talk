#!/bin/bash
set -euo pipefail
[ "$(id -u)" = 0 ]
[ -f /run/ut-image-build-authorized ] || { echo 'Image-build authorization marker missing'; exit 1; }
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
rpm -q cloud-init growpart openssh-server >/dev/null
install -d -m 755 /etc/cloud/cloud.cfg.d /etc/ssh/sshd_config.d
cat > /etc/cloud/cloud.cfg.d/99-unlimited-talk.cfg <<'CFG'
datasource_list: [ ConfigDrive, DigitalOcean, NoCloud ]
preserve_hostname: false
disable_root: true
ssh_pwauth: false
ssh_deletekeys: true
ssh_genkeytypes: [ ed25519, ecdsa, rsa ]
users: [ default ]
system_info:
  default_user:
    name: utops
    gecos: Unlimited Talks Operations
    lock_passwd: true
    groups: [ wheel ]
    sudo: [ "ALL=(ALL) NOPASSWD:ALL" ]
    shell: /bin/bash
  network:
    renderers: [ network-manager ]
growpart:
  mode: auto
  devices: [ '/' ]
resize_rootfs: true
CFG
cat > /etc/ssh/sshd_config.d/00-unlimited-talk.conf <<'CFG'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
CFG
/usr/sbin/sshd -t
systemctl enable cloud-init-local.service cloud-config.service cloud-final.service
restorecon -RF /etc/cloud /etc/ssh/sshd_config.d
/usr/sbin/sshd -T | grep -E '^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication) '
printf 'CLOUD_TEMPLATE_CONFIGURATION_WRITTEN\n'
