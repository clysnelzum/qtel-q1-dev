# Stock Firmware Backups, Extraction & Full Factory Restore (`Q-Tel Q1`)

This directory contains a **100% complete, bit-for-bit verified factory backup** of the Q-Tel Q1 (`k37m_m01c`, MediaTek MT6737M, build `M01C_XINGYU_V06_2025_06_24` / `RP1A.200720.011`).

## Contents

| File | Partition | Size | Purpose / Notes |
|---|---|---|---|
| `boot_a.bin` | `boot_a` (`mmcblk0p7`) | 32 MB | Stock Linux 4.19.127 kernel + DTB + stock recovery-as-boot ramdisk (`AVBf` intact) |
| `vbmeta_a.bin` | `vbmeta_a` (`mmcblk0p25`) | 8 MB | OEM-signed top-level AVB 2.0 descriptor (`flags=0`, chains `boot`, `vbmeta_system`, `vbmeta_vendor`) |
| `lk_a.bin` | `lk_a` (`mmcblk0p5`) | 512 KB | Stock Little Kernel bootloader (contains OEM RSA-2048 modulus at `0x6721c`) |
| `seccfg.bin` | `seccfg` (`mmcblk0p12`) | 512 KB | Factory-blank (all zeros) security configuration (`unlocked: no`) |
| `nvram.bin` | `nvram` (`mmcblk0p2`) | 5 MB | Calibration / IMEI / radio NVRAM (**device-specific — keep safe!**) |
| `proinfo.bin` | `proinfo` (`mmcblk0p1`) | 3 MB | Device/board product info |
| `frp.bin` | `frp` (`mmcblk0p19`) | 1 MB | Factory Reset Protection & OEM unlock flag |
| `para.bin` | `para` (`mmcblk0p6`) | 512 KB | Bootloader Control Block (BCB / `misc`) |
| `stock_system_a.img` | `super -> system_a` | 1.19 GB | Factory stock Android 11 system image (`AVBf` intact) |
| `stock_product_a.img` | `super -> product_a` | 630 MB | Factory stock product image (`AVBf` intact) |
| `stock_vendor_a.img` | `super -> vendor_a` | 141 MB | Factory stock vendor image — cryptographically verified (`0 / 35,274` SHA-256 block mismatches against OEM-signed `AVB0` root digest `41e5bccedb664cbce973ec483cf53ce3c2a3221598e7f4455e6c66bb7fdc2367`) |
| `fstab.mt6735.stock` | `/vendor/etc/fstab.mt6735` | 3.9 KB | Original encrypted stock fstab |
| `recover_vendor_fec.py` | Tool | — | Verifies AVB `dm-verity` SHA-256 hashtrees and recovers up to 2 corrupted blocks per RS(255,253) stripe |
| `SHA256SUMS.txt` | Checksums | — | SHA-256 hashes of all stock binaries |

> **Note on `stock_vendor_a.img`**: After `vendor_a` was temporarily resized and patched for unencrypted `/data`, `recover_vendor_fec.py` used the intact `dm-verity` SHA-256 hashtree (`0x89ca000..0x8ae2000`) to pinpoint the 18 modified 4 KB blocks and mathematically reconstructed all 18 blocks bit-for-bit using the embedded **Reed-Solomon `RS(255,253)` FEC** (`0x8ae2000..0x8bfc000`). You can re-verify its integrity at any time:
> ```bash
> python3 recover_vendor_fec.py --input stock_vendor_a.img --verify-only
> ```

---

## 1. How to Extract All Stock Images from a Live Device

### Prerequisites (Linux Host)
```bash
sudo apt-get update && sudo apt-get install -y adb fastboot python3-venv python3-dev libusb-1.0-0-dev
git clone --depth 1 https://github.com/bkerler/mtkclient.git
cd mtkclient && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt .
```
Ensure `ModemManager` is stopped (`sudo systemctl stop ModemManager`) so it does not claim `/dev/ttyACM0` during Preloader enumeration.

### Step 1A: Extract Raw Physical Partitions via MediaTek Preloader (`mtkclient`)
Because the Q-Tel Q1 enumerates `MT65xx Preloader` (`0e8d:2000`) for ~2.8 seconds on every boot and has `SBC=False`, you can dump every physical partition even on a **locked** device:

```bash
mkdir -p stock_dump
# Start mtkclient first, then either run 'adb reboot' / 'fastboot reboot'
# or power off (pull/reinsert battery) and plug in USB without holding any keys:
sudo /path/to/mtkclient/venv/bin/mtk r \
  seccfg,lk_a,vbmeta_a,boot_a,proinfo,nvram,frp,para \
  stock_dump/seccfg.bin,stock_dump/lk_a.bin,stock_dump/vbmeta_a.bin,stock_dump/boot_a.bin,stock_dump/proinfo.bin,stock_dump/nvram.bin,stock_dump/frp.bin,stock_dump/para.bin

# Optional: dump the entire 2.5 GB super partition directly via Preloader
# sudo /path/to/mtkclient/venv/bin/mtk r super stock_dump/super.bin

# Reboot cleanly out of Legacy DA mode via hardware WDT reset (no battery pull required)
python3 ../bootloader/unlock_q1_bootloader.py wdt-reboot --mtk-venv /path/to/mtkclient/venv
```

### Step 1B: Extract Dynamic Partitions (`system_a`, `vendor_a`, `product_a`) from TWRP
Once the bootloader is unlocked and custom TWRP (`../recovery/twrp_q1_boot.img`) is running, TWRP maps the logical partitions inside `super` under `/dev/block/mapper/`. Pull them cleanly **before modifying anything**:

```bash
adb devices -l   # confirm 'recovery'
adb pull /dev/block/mapper/system_a  stock_dump/stock_system_a.img
adb pull /dev/block/mapper/vendor_a  stock_dump/stock_vendor_a.img
adb pull /dev/block/mapper/product_a stock_dump/stock_product_a.img
```

You can verify `stock_vendor_a.img` immediately:
```bash
python3 recover_vendor_fec.py --input stock_dump/stock_vendor_a.img --verify-only
```

---

## 2. How to Flash Stock Images Back to a Live Device (Full Factory Restore)

If you cloned this repository from GitHub, first download the three large stock images (`> 100 MB`) from [Release `v1.0`](https://github.com/clysnelzum/qtel-q1-dev/releases/tag/v1.0) into `stock/`:
```bash
gh release download v1.0 -R clysnelzum/qtel-q1-dev -p "stock_*.img" -D .
```

Verify checksums first:
```bash
sha256sum -c SHA256SUMS.txt
```

### Step 2A: Restore Dynamic Partitions (`system_a`, `vendor_a`, `product_a`) in `fastbootd`
Boot into TWRP (`adb reboot recovery`), then enter userspace `fastbootd`:
```bash
adb reboot fastboot
fastboot getvar is-userspace   # must print: is-userspace: yes

fastboot flash system_a  stock_system_a.img
fastboot flash product_a stock_product_a.img
fastboot flash vendor_a  stock_vendor_a.img
```

### Step 2B: Restore Stock Boot, VBMeta, and Wipe Userdata in Bootloader `fastboot`
Reboot from `fastbootd` into bootloader `fastboot`:
```bash
fastboot reboot bootloader
fastboot devices -l

fastboot flash boot_a   boot_a.bin
fastboot flash vbmeta_a vbmeta_a.bin
fastboot erase userdata
fastboot erase metadata
```

> If you want to stay **unlocked** on stock firmware, stop here and run `fastboot reboot` (or flash `../recovery/vbmeta_disabled.bin` instead of `vbmeta_a.bin` if you plan to modify partitions).

### Step 2C: Relock the Bootloader to 100% Factory `green` AVB State (Optional)
Only do this after **Step 2A and Step 2B** have restored all 5 stock signed images (`system_a`, `product_a`, `vendor_a`, `boot_a`, `vbmeta_a`) cleanly!

```bash
# Start relock helper while triggering fastboot reboot to catch Preloader (0e8d:2000)
(sleep 4 && fastboot reboot bootloader) &
python3 ../bootloader/unlock_q1_bootloader.py relock-factory \
  --mtk /path/to/mtkclient/venv/bin/mtk --seccfg seccfg.bin
# Reboot cleanly via hardware WDT reset (no PMIC latch, no battery pull!)
python3 ../bootloader/unlock_q1_bootloader.py wdt-reboot --mtk-venv /path/to/mtkclient/venv
```
First boot of freshly-wiped stock Android 11 takes ~3.5–4 minutes while FBE metadata encryption, F2FS formatting, and `dm-verity` verification complete, after which the device enumerates stock MTP (`0e8d:2008`, `Q-Tel Q1`). This entire restore + relock + boot cycle has been verified live on hardware with:
- `ro.boot.verifiedbootstate = green`
- `ro.boot.flash.locked = 1`
- `ro.boot.vbmeta.device_state = locked`
- `sys.boot_completed = 1`
- `dm-verity` active on `/` (`dm-4`) and `/vendor` (`dm-5`) + FBE-encrypted `/data` (`dm-9`)
- `fastboot getvar unlocked` -> `no`, `fastboot getvar secure` -> `yes`

> **Warning**: Never flash someone else's `nvram.bin` or `proinfo.bin` unless repairing corrupted IMEI/calibration data; keep those backups strictly tied to your specific unit.
