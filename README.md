# Q-Tel Q1 (`k37m_m01c`) — Bootloader Unlock, Custom TWRP & LineageOS 18.1 Bringup

This repository collects all firmware dumps, custom tools, patches, recovery builds, and ROM bringup artifacts produced to take the **Q-Tel Q1** (a MediaTek MT6737M hybrid T9-keypad Android phone) from a factory-locked, bloated white-label stock firmware to an unlocked device running **custom TWRP 3.7.0_11** and **vanilla LineageOS 18.1**, while preserving **100% bit-for-bit factory reversibility**.

## Project Goals & Achievements
1. **Bootloader Unlock (No Volume Buttons Required)**:
   - Discovered an unprotected MediaTek MT6737M Preloader (`0e8d:2000`, `SBC=False`, `SLA=False`, `DAA=False`).
   - Reverse-engineered `lk_a.bin` to confirm **SecCfg V3** (`AND_SECCFG_v`) with hardware SEJ/HACC encryption.
   - Fixed two upstream bugs in `mtkclient`'s `SecCfgV3` initialization for factory-blank `seccfg` partitions and unlocked the bootloader (`unlocked: yes`, `ro.boot.flash.locked=0`, `ro.boot.verifiedbootstate=orange`) without needing physical Volume Up/Down keys (which are absent on the Q1 T9 keypad).
2. **Custom TWRP (`TWRP 3.7.0_11-Q-Tel-Q1`)**:
   - Ported 32-bit `armeabi-v7a` Android 11 (SDK 30) TWRP as an A/B **recovery-as-boot** image (`twrp_q1_boot.img`, 20.72 MB) preserving stock `first_stage_ramdisk/`.
   - Solved MediaTek `musb_hdrc` USB enumeration (`kernel_init_done=1`, `cmode=1`, `mtp.gs0`) for working **root ADB**, **MTP**, and **`fastbootd`**.
   - Boosted `twres/ui.xml` font sizes (~1.6x–1.8x) for readability on the `240x320` QVGA screen, scrubbed all third-party branding, mapped all dynamic (`super`) & physical partitions, and enabled native unencrypted `f2fs` Internal Storage (`/data` & `/sdcard`, 12 GB).
3. **LineageOS 18.1 GSI Bringup**:
   - Identified via `pstore` (`pmsg-ramoops-0`) that the Q1's Linux `4.19.127` kernel uses **64-bit Binder IPC (Protocol 8)** with 32-bit ARMv7 userspace (`arm32_binder64` / **`a64_bvS`**).
   - Patched `vendor_a` with `/vendor/etc/init/init.binderfs.rc` (to mount `/dev/binderfs`) and unencrypted `/vendor/etc/fstab.mt6735`, replaced the 601 MB Chinese bloatware `product_a` with a clean 4 MB `ext4` image, and booted **LineageOS 18.1 (`18.1-20240121-UNOFFICIAL-a64_bvS`)** cleanly (`sys.boot_completed=1`).
4. **100% Bit-for-Bit Factory Reversibility (End-to-End Verified)**:
   - All stock partitions are backed up, including a bit-for-bit verified `stock_vendor_a.img` mathematically recovered via Android's embedded **Reed-Solomon `RS(255,253)` FEC** (`0 / 35,274` SHA-256 block mismatches against the OEM-signed `AVB0` root digest).
   - Full round-trip verified live on hardware: **LineageOS 18.1 -> 100% relocked factory Android 11 (`verifiedbootstate=green`, `flash.locked=1`, `dm-verity` active on `/` and `/vendor`) -> re-unlocked -> TWRP 3.7.0_11 -> LineageOS 18.1**.

---

## Device Specifications (`Q-Tel Q1`)

| Property | Value |
|---|---|
| **Brand / Model** | `Q-Tel` / `Q1` |
| **Codename / Board** | `k37m_m01c` (`full_k37m_m01c`) |
| **SoC / Hardware** | MediaTek **MT6737M** (`hwcode=0x335`, `ro.hardware=mt6735`, quad-core Cortex-A53) |
| **Kernel** | `Linux 4.19.127 #1 SMP PREEMPT Tue Jun 24 20:57:56 CST 2025 armv7l` (32-bit ARMv7) |
| **Userspace ABI / Treble** | 32-bit `armeabi-v7a`, **Binder Protocol 8 (`arm32_binder64` / `a64_bvS`)**, VNDK `30` |
| **Stock OS** | Android 11 (SDK 30, spoofed as `13` in `ro.build.version.release`), build `RP1A.200720.011` / `M01C_XINGYU_V06_2025_06_24`, security patch `2022-09-01` |
| **RAM / Storage** | 2 GB RAM (`0x80000000`), 16 GB eMMC (`0x3ab800000`) |
| **Partition Scheme** | A/B (`slot _a` active), **Recovery-as-Boot** (no dedicated `recovery` partition), Dynamic Partitions (`super` = 2.50 GB), AVB 2.0 (v1.1) |
| **Display** | `240x320` QVGA portrait, `120 dpi` touch display (`fts_ts` / `mtk-tpd`) |
| **Physical Keypad** | T9 numeric + D-pad + Power/Menu/Back/Send (`mtk-kpd`) — **no physical Volume Up/Down keys** |
| **Hardware Security (eFuse)** | `SBC=False`, `SLA=False`, `DAA=False` (Preloader `0e8d:2000` enumerates ~2.8s on every boot) |
| **USB Controller** | `musb-hdrc` (stock ADB `0e8d:201c`, Preloader `0e8d:2000`, TWRP MTP+ADB `18d1:4ee2`) |

---

## Directory Structure

```text
qtel-q1-dev/
├── README.md                 # This overview
├── stock/                    # Complete 100% factory stock dumps, FEC recovery tool & restore guide
│   ├── README.md             # (1) How to extract from a live device, (2) How to restore & relock
│   ├── recover_vendor_fec.py # AVB dm-verity verifier & RS(255,253) FEC bit-for-bit recovery tool
│   ├── SHA256SUMS.txt        # Integrity checksums for all stock binaries
│   └── *.bin / *.img         # Stock boot_a, vbmeta_a, lk_a, seccfg, nvram, proinfo, frp, para, system_a, product_a, vendor_a
├── bootloader/               # Unlock/relock tool, mtkclient SecCfgV3 patch & reverse-engineering logs
│   ├── README.md             # Technical write-up, unlock guide, factory & custom-key relock
│   ├── unlock_q1_bootloader.py # Documented Python CLI for patching mtkclient, inspecting lk_a, unlocking & relocking
│   ├── seccfg_mtkclient.patch # Exact diff against upstream mtkclient seccfg.py
│   └── *.txt / *.log         # Device dumps, fastboot getvar & unlock verification logs
├── recovery/                 # Custom TWRP 3.7.0_11-Q-Tel-Q1 image, builder & helper images
│   ├── README.md             # Porting details, build instructions, flashing & usage guide
│   ├── build_twrp.py         # Reproducible TWRP recovery-as-boot image builder
│   ├── twrp_q1_boot.img      # Ready-to-flash TWRP 3.7.0_11-Q-Tel-Q1 boot image (20.72 MB)
│   ├── vbmeta_disabled.bin   # VBMeta with AVB verification & dm-verity disabled (flags=0x03)
│   ├── para_recovery.bin     # 512 KB 'boot-recovery' para image to force TWRP boot via Preloader
│   └── recovery.log          # Live verification log captured from TWRP
└── rom/                      # LineageOS 18.1 (a64_bvS) GSI, patched vendor_a & installation guide
    ├── README.md             # Full LineageOS 18.1 flashing & troubleshooting guide
    ├── NOTES.txt             # Technical bringup notes (Binder v8, binderfs, SELinux, product_a)
    ├── patch_vendor_for_gsi.sh # Script to build vendor_a_lineage.img from stock_vendor_a.img
    ├── lineage-18.1-20240121-UNOFFICIAL-a64_bvS.img.xz # LineageOS 18.1 arm32_binder64 vanilla GSI
    ├── vendor_a_lineage.img  # Pre-patched vendor_a (unencrypted fstab + init.binderfs.rc)
    ├── empty_product.img     # Clean 4 MB ext4 product_a image (removes Chinese bloatware)
    ├── init.binderfs.rc      # Vendor init script mounting /dev/binderfs
    └── fstab.mt6735.noenc    # Unencrypted fstab.mt6735
```

---

## Downloading Large Firmware Images (`> 100 MB`)
Because GitHub rejects individual files larger than `100 MB` in Git history, the five large partition images (`stock_system_a.img`, `stock_product_a.img`, `stock_vendor_a.img`, `vendor_a_lineage.img`, and `lineage-18.1-20240121-UNOFFICIAL-a64_bvS.img.xz`) are hosted as assets on **[Release `v1.0`](https://github.com/clysnelzum/qtel-q1-dev/releases/tag/v1.0)**.

Download them straight into the repository with GitHub CLI:
```bash
gh release download v1.0 -R clysnelzum/qtel-q1-dev -p "stock_*.img" -D stock/
gh release download v1.0 -R clysnelzum/qtel-q1-dev -p "vendor_a_lineage.img" -p "lineage-18.1-*.img.xz" -D rom/
```

## Quickstart Workflow (Clean Device to LineageOS 18.1)
1. **Back up stock partitions** — follow [stock/README.md](stock/README.md).
2. **Unlock the bootloader** — follow [bootloader/README.md](bootloader/README.md).
3. **Flash custom TWRP & disable AVB** — follow [recovery/README.md](recovery/README.md).
4. **Flash LineageOS 18.1 (`a64_bvS`)** — follow [rom/README.md](rom/README.md).

## Safety & Recovery Notes
- Because `SBC=False` on this hardware and `MT65xx Preloader` (`0e8d:2000`) appears briefly on every cold boot, **any soft-brick or bootloop can be recovered over USB** using `mtkclient` (remove the battery for 2 seconds, reinsert it, and plug in USB without holding any buttons while `mtkclient` is listening).
- Instead of `mtk reset` (which triggers a Legacy DA `FINISH_CMD` bug that leaves the PMIC latched until a battery pull), use `python3 bootloader/unlock_q1_bootloader.py wdt-reboot --mtk-venv <venv>` to trigger an immediate hardware Watchdog reset (`WDT_SWRST 0x10212014 = 0x1209`) cleanly over USB.
- On Linux desktops where the screen locks (e.g., `lightdm`), `uaccess` USB ACLs on `/dev/bus/usb/*` may drop for the desktop user; if `adb` or `fastboot` stops seeing the phone, run `sudo env HOME=$HOME adb kill-server && sudo env HOME=$HOME adb devices` (or add a `/etc/udev/rules.d/` rule for `0e8d` and `18d1`).
