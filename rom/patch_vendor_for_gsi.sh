#!/usr/bin/env bash
# Reproducibly patches stock_vendor_a.img for LineageOS 18.1 (a64_bvS) GSI:
#   1. Resizes ext4 into the unused space at the end of the vendor_a image.
#   2. Replaces /etc/fstab.mt6735 with fstab.mt6735.noenc (mode 0644, vendor_configs_file).
#   3. Injects /etc/init/init.binderfs.rc (mode 0644, vendor_configs_file) to mount /dev/binderfs.
#   4. Validates the resulting filesystem with e2fsck.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${1:-$SCRIPT_DIR/../stock/stock_vendor_a.img}"
DST="${2:-$SCRIPT_DIR/vendor_a_lineage.img}"

cp "$SRC" "$DST"
sudo e2fsck -f -y "$DST" || true
sudo resize2fs "$DST"

sudo debugfs -w "$DST" -R "rm /etc/fstab.mt6735" || true
sudo debugfs -w "$DST" -R "write $SCRIPT_DIR/fstab.mt6735.noenc /etc/fstab.mt6735"
sudo debugfs -w "$DST" -R "set_inode_field /etc/fstab.mt6735 mode 0100644"
sudo debugfs -w "$DST" -R 'ea_set /etc/fstab.mt6735 security.selinux u:object_r:vendor_configs_file:s0\000'

sudo debugfs -w "$DST" -R "rm /etc/init/init.binderfs.rc" 2>/dev/null || true
sudo debugfs -w "$DST" -R "write $SCRIPT_DIR/init.binderfs.rc /etc/init/init.binderfs.rc"
sudo debugfs -w "$DST" -R "set_inode_field /etc/init/init.binderfs.rc mode 0100644"
sudo debugfs -w "$DST" -R 'ea_set /etc/init/init.binderfs.rc security.selinux u:object_r:vendor_configs_file:s0\000'

sudo e2fsck -f -y "$DST"
echo "[+] Patched vendor image ready: $DST"
