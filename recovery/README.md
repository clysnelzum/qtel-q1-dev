# Custom TWRP (`TWRP 3.7.0_11-Q-Tel-Q1`) for Q-Tel Q1 (`k37m_m01c`)

This directory contains the custom-ported **TWRP 3.7.0_11** recovery-as-boot image for the Q-Tel Q1, its build script, AVB helper images, and live verification logs.

## Technical Overview
The Q-Tel Q1 has **no dedicated `recovery` partition** (Android 11 A/B **recovery-as-boot** architecture): `boot_a` (32 MB) contains both the first-stage init ramdisk for normal Android boot (`first_stage_ramdisk/`) and the full recovery environment.

### Key Porting Details
- **Kernel & DTB**: Reuses the stock Q-Tel Q1 Linux `4.19.127` 32-bit ARMv7 `zImage` and DTB (Android Boot Image Header v2, page size `2048`).
- **Normal Boot Preserved**: Copies stock `first_stage_ramdisk/` verbatim (with unencrypted `fstab.mt6735`) so normal boot (`androidboot.force_normal_boot=1`) mounts `super` cleanly.
- **TWRP Base**: 32-bit `armeabi-v7a` Android 11 (SDK 30) MediaTek TWRP ramdisk (`20.72 MB` total boot image, well under the `32 MB` `boot_a` limit).
- **MediaTek `musb-hdrc` USB Fix**:
  - Sets `write /sys/module/musb_hdrc/parameters/kernel_init_done 1` on `early-init` (without this, the MT6735/MT6737M 4.19 kernel never pulls up USB D+).
  - Sets `write /sys/class/udc/musb-hdrc/device/cmode 1` (`cmode 2` is charge-only!).
  - Configures ConfigFS USB gadget with `mtp.gs0` + `ffs.adb` + `ffs.fastboot` (`18d1:4ee2` MTP+ADB, `18d1:d001` ADB/sideload, `18d1:4ee0` fastbootd).
  - Fixes 32-bit `LD_LIBRARY_PATH` (`/system/lib:/vendor/lib/hw`) in `system/etc/init/hw/init.rc`.
- **240x320 QVGA Display Polish**: Boosted all UI fonts in `twres/ui.xml` by ~1.6x–1.8x (`font_l=84`, `font_m=68`, `font_s=58`, `fixed=52`, `keylabel=96`) so buttons and menus remain legible when scaled down to `240x320`.
- **Clean Q-Tel Q1 Branding**: Zero third-party device strings in `prop.default` or `/tmp/recovery.log`; enumerates as `Q-Tel Q1` (`full_k37m_m01c` / `k37m_m01c`) with version banner `3.7.0_11-Q-Tel-Q1`.
- **Dynamic & Physical Partitions**: Explicit `twrp.flags` mapping for `System`, `Vendor`, `Product` (plus `System Image`, `Vendor Image`, `Product Image` via `/dev/block/mapper/*_a`), `Boot (Slot A/B)`, `DTBO`, `VBMeta`, `LK`, `SecCfg`, `NVRAM`, `NVDATA`, `ProInfo`, `Protect1/2`, `Logo`, `FRP`, `metadata`, `MicroSD` (`/external_sd`), and `USB-OTG`.

---

## Files in This Directory
- `twrp_q1_boot.img` — Ready-to-flash TWRP 3.7.0_11-Q-Tel-Q1 recovery-as-boot image (20.72 MB).
- `vbmeta_disabled.bin` — Stock `vbmeta_a.bin` with AVB flags set to `0x03` (`HASHTREE_DISABLED | VERIFICATION_DISABLED`). **Required** to avoid a 35-second AVB bootloop when flashing modified `boot_a`.
- `para_recovery.bin` — 512 KB `para` image containing `boot-recovery` to force booting straight into TWRP via Preloader if Android cannot reboot.
- `build_twrp.py` — Documented Python script that reproduces `twrp_q1_boot.img`, `vbmeta_disabled.bin`, and `para_recovery.bin`.
- `recovery.log` — Live `/tmp/recovery.log` verification capture from the device.

---

## 1. How to Extract Recovery / Boot from a Live Device
Because recovery lives inside `boot_a`:
- **From Preloader (`mtkclient`)**:
  ```bash
  sudo mtk r boot_a,vbmeta_a boot_a.bin,vbmeta_a.bin
  ```
- **From TWRP (ADB root)**:
  ```bash
  adb pull /dev/block/platform/bootdevice/by-name/boot_a boot_a_current.img
  ```

## 2. How to Flash TWRP to a Live Device

> **Prerequisite**: Bootloader must be unlocked (see [../bootloader/README.md](../bootloader/README.md)). Note that `fastboot boot` is unsupported on this MT6737M LK bootloader (triggers `lk_crash`); flash directly to `boot_a`.

### Method A: Via Fastboot (Recommended)
```bash
adb reboot bootloader
fastboot devices -l

fastboot flash vbmeta_a vbmeta_disabled.bin
fastboot flash boot_a   twrp_q1_boot.img
# Optional: flash para_recovery.bin to boot straight into TWRP instead of Android
fastboot flash para     para_recovery.bin
fastboot reboot
```
*(If you flashed `para_recovery.bin`, clear it once TWRP boots: `adb shell "dd if=/dev/zero of=/dev/block/platform/bootdevice/by-name/para bs=4096 count=1 && sync"`.)*

### Method B: Via MediaTek Preloader (`mtkclient` — Works Even from a Bootloop)
```bash
sudo /path/to/mtkclient/venv/bin/mtk w vbmeta_a vbmeta_disabled.bin
sudo /path/to/mtkclient/venv/bin/mtk w boot_a   twrp_q1_boot.img
python3 ../bootloader/unlock_q1_bootloader.py wdt-reboot --mtk-venv /path/to/mtkclient/venv
```

### Booting into TWRP or `fastbootd`
- **From Android**:
  ```bash
  adb reboot recovery
  ```
- **From a stuck/unbootable OS (via Preloader)**:
  ```bash
  sudo /path/to/mtkclient/venv/bin/mtk w para para_recovery.bin
  python3 ../bootloader/unlock_q1_bootloader.py wdt-reboot --mtk-venv /path/to/mtkclient/venv
  # Reboots directly into TWRP (18d1:4ee2) without pulling the battery!
  # Once in TWRP (use 'adb wait-for-recovery'), clear the boot-recovery flag:
  adb shell "dd if=/dev/zero of=/dev/block/platform/bootdevice/by-name/para bs=4096 count=1 && sync"
  ```
- **Entering userspace `fastbootd` (for flashing dynamic partitions in `super`)**:
  ```bash
  adb reboot fastboot
  fastboot getvar is-userspace   # returns: yes
  ```

## 3. Rebuilding `twrp_q1_boot.img`
To rebuild from a donor 32-bit Android 11 MediaTek TWRP ramdisk directory + `../stock/boot_a.bin`:
```bash
python3 build_twrp.py \
  --stock-boot ../stock/boot_a.bin \
  --stock-vbmeta ../stock/vbmeta_a.bin \
  --donor-ramdisk /path/to/donor_mtk/ramdisk \
  --noenc-fstab ../rom/fstab.mt6735.noenc \
  --output ./twrp_q1_boot.img
```

## Verified Working Features
- Touchscreen + partial T9 keypad navigation
- Readable boosted fonts on `240x320` QVGA
- Root ADB (`uid=0`), `adb push/pull`, `adb sideload`, MTP (`18d1:4ee2`), and `fastbootd` (`is-userspace: yes`)
- Native read/write Internal Storage (`/data` & `/sdcard`, 12 GB unencrypted `f2fs`) when paired with unencrypted `fstab.mt6735`
- Clean mounting, backup, and flashing of dynamic (`super`) and physical partitions
