# LineageOS 18.1 (`a64_bvS`) GSI Bringup for Q-Tel Q1 (`k37m_m01c`)

This directory contains the tested **LineageOS 18.1 (Android 11, vanilla)** Generic System Image and all Q-Tel Q1 vendor/product adaptation files required to boot it cleanly on the MT6737M hardware.

## Why LineageOS 18.1 `a64_bvS`?
1. **Native VNDK 30 Compatibility**: The Q-Tel Q1 ships with an Android 11 vendor (`ro.product.vndk.version=30`, `first_api_level=30`). LineageOS 18.1 (Android 11) matches VNDK 30 natively and runs faster with significantly lower RAM usage than the bloated stock Chinese firmware.
2. **Binder Protocol 8 (`arm32_binder64` / `a64_bvS`)**: Early bringup testing with `arm_bvS` failed with:
   ```text
   Binder driver protocol(8) does not match user space protocol(7)!
   ```
   The Q1's Linux `4.19.127` kernel uses **64-bit Binder IPC (Protocol 8)** alongside 32-bit ARMv7 userspace (`armeabi-v7a`). In Project Treble terminology, this requires **`a64_bvS`** (`arm32_binder64`, A/B System-as-Root, vanilla, built-in Phh Superuser).
3. **`binderfs` Mounting (`init.binderfs.rc`)**: The Q1 kernel relies on `binderfs` (`/dev/binderfs/binder` symlinked to `/dev/binder`), which stock `system_a` mounted in `init.rc` but the GSI omits. Injecting `/vendor/etc/init/init.binderfs.rc` (mode `0644`, SELinux `u:object_r:vendor_configs_file:s0`) into `vendor_a` fixes this permanently for any GSI.
4. **Unencrypted `/data` (`fstab.mt6735.noenc`)**: Removing `fileencryption=...` and `keydirectory=/metadata/vold/metadata_encryption` from `fstab.mt6735` allows LineageOS 18.1 to boot cleanly on unencrypted `f2fs` `/data` while keeping Internal Storage (`/sdcard`, 12 GB) natively accessible in TWRP and MTP.
5. **Clean `product_a` (`empty_product.img`)**: Replaces the 601 MB stock `product_a` (containing Chinese EasyOS overlays and preinstalled apps) with a clean 4 MB `ext4` image, satisfying `first_stage_mount` while freeing ~597 MB inside `super` (2.50 GB) for the 1.20 GiB LineageOS system image.

---

## Files in This Directory
- `lineage-18.1-20240121-UNOFFICIAL-a64_bvS.img.xz` — Andy Yan's LineageOS 18.1 `arm32_binder64` vanilla GSI (432 MB compressed -> 1.20 GiB raw image).
- `vendor_a_lineage.img` — Pre-patched `vendor_a` image (`141 MB`, contains `fstab.mt6735.noenc` + `init.binderfs.rc`, `0644`, verified with `e2fsck`).
- `empty_product.img` — Clean 4 MB `ext4` image for `product_a`.
- `init.binderfs.rc` — Vendor init snippet that mounts `/dev/binderfs` and creates `/dev/{binder,hwbinder,vndbinder}` symlinks on `on init`.
- `fstab.mt6735.noenc` — Unencrypted `fstab.mt6735` derived from `../stock/fstab.mt6735.stock`.
- `patch_vendor_for_gsi.sh` — Reproducible shell script to rebuild `vendor_a_lineage.img` from `../stock/stock_vendor_a.img`.
- `NOTES.txt` — Detailed technical bringup notes and debugging log summary.

---

## Flashing Instructions

### Prerequisites
- Bootloader unlocked ([../bootloader/README.md](../bootloader/README.md))
- Custom TWRP flashed to `boot_a` + `vbmeta_disabled.bin` flashed to `vbmeta_a` ([../recovery/README.md](../recovery/README.md))
- Full stock backup saved ([../stock/README.md](../stock/README.md))

### 1. Download (if cloned from GitHub) and Decompress the LineageOS 18.1 GSI
If you cloned this repository from GitHub, download `vendor_a_lineage.img` and `lineage-18.1-20240121-UNOFFICIAL-a64_bvS.img.xz` from [Release `v1.0`](https://github.com/clysnelzum/qtel-q1-dev/releases/tag/v1.0) into `rom/`:
```bash
gh release download v1.0 -R clysnelzum/qtel-q1-dev -p "vendor_a_lineage.img" -p "lineage-18.1-*.img.xz" -D .
xz -dk lineage-18.1-20240121-UNOFFICIAL-a64_bvS.img.xz
```

### 2. Format `/data` and Clear Stale Metadata Encryption Keys in TWRP
Boot into TWRP (`adb reboot recovery`) and run:
```bash
adb shell "
  umount /data 2>/dev/null || true
  mkdir -p /tmp/m
  mount -t ext4 /dev/block/platform/bootdevice/by-name/md_udc /tmp/m
  rm -rf /tmp/m/vold/metadata_encryption /tmp/m/vold/expand_*
  sync && umount /tmp/m
  make_f2fs -g android -f /dev/block/platform/bootdevice/by-name/userdata
"
```

### 3. Flash `product_a`, `vendor_a`, and `system_a` via `fastbootd`
```bash
adb reboot fastboot
fastboot getvar is-userspace   # must print: is-userspace: yes

fastboot flash product_a empty_product.img
fastboot flash vendor_a  vendor_a_lineage.img
fastboot flash system_a  lineage-18.1-20240121-UNOFFICIAL-a64_bvS.img
fastboot reboot
```

> **Important**: Always flash dynamic partitions (`system_a`, `vendor_a`, `product_a`) via `fastbootd` (`fastboot flash ...`), not `adb push /dev/block/mapper/...`, so `super` metadata and partition sizes update reliably.

### 4. First Boot & Verification
First boot takes ~45–90 seconds. Verify via ADB:
```bash
adb devices -l
adb shell "getprop sys.boot_completed; getprop ro.lineage.version; df -h /data; wm size; wm density"
```
Expected verified output:
```text
1
18.1-20240121-UNOFFICIAL-a64_bvS
/dev/block/mmcblk0p31  12G  636M   11G   6% /data/user/0
Physical size: 240x320
Physical density: 120
```

### Optional Display Scaling Tip (`240x320` QVGA)
Note that the LineageOS boot animation has a fixed resolution and appears cropped on `240x320`, whereas the Android UI itself dynamically adapts to `240x320`. You can fine-tune UI scaling at any time without rebooting:
```bash
adb shell wm density 100     # slightly more screen real estate
adb shell wm density reset   # restore default 120 dpi
```
