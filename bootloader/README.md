# Bootloader Unlock & Relock (`Q-Tel Q1` / MediaTek `MT6737M`)

This directory contains the Python helper script, upstream `mtkclient` patch, and verification logs for unlocking (and relocking) the Q-Tel Q1 bootloader completely over USB.

## Why Standard `fastboot flashing unlock` Fails on This Device
1. Inspecting `lk_a.bin` shows that standard `fastboot flashing unlock` displays a confirmation prompt requiring **Volume Up** to accept:
   ```text
   Yes (Volume UP):Unlock(may void warranty).
   No (Volume Down):Do not unlock bootloader.
   ```
2. Checking `/dev/input/event*` (`getevent -pl`) reveals that the Q1's physical T9 keypad (`mtk-kpd`) has **no Volume Up or Volume Down keys** (Volume keys only exist on `ACCDET`, the 3.5 mm headset jack).

## Hardware & Bootloader Analysis
Capturing `MT65xx Preloader` (`0e8d:2000`, which enumerates for ~2.8 seconds on every reboot) with `mtkclient` revealed:
- **SoC**: `MT6737M/MT6735G` (`hwcode = 0x335`, `hw_ver = 0xcb00`, `sej_base = 0x10008000`)
- **Hardware Security**: `SBC=False`, `SLA=False`, `DAA=False` (completely unprotected Preloader/DA)
- **`seccfg` partition**: Factory-blank (all `0x00` bytes across 512 KB)
- **`lk_a.bin` reverse engineering**:
  - Load address: `0x41e00000` (after 512-byte MTK header)
  - Uses **SecCfg V3** (`AND_SECCFG_v` string at offset `0x5db34`) with hardware SEJ/HACC encryption (`SECCFG_HWTYPE=V2` -> `sej_sec_cfg_hw`)
  - Embedded **AVB 2.0 RSA-2048 public key modulus** (256 raw big-endian bytes) located at offset `0x6721c`..`0x6731c`

## Upstream `mtkclient` Bugs Fixed (`seccfg_mtkclient.patch`)
`unlock_q1_bootloader.py patch` (and `seccfg_mtkclient.patch`) fixes four upstream bugs in `mtkclient` v2.1.4:
1. **`mtkclient/Library/Hardware/seccfg.py` (`SecCfgV3.__init__`)**: `self.hwtype` defaults to `None` instead of `"V2"` (SEJ/HACC V3), crashing when initializing a factory-blank `seccfg`.
2. **`mtkclient/Library/Hardware/seccfg.py` (`SecCfgV3.__init__`)**: `self.imginfo` is initialized as flat `b"\x00" * (0x68 * 20)` instead of `[b"\x00" * 0x68 for _ in range(20)]`, breaking iteration in `SecCfgV3.create()`.
3. **`mtkclient/Library/DA/legacy/dalegacy_lib.py` (`finish`)**: Reads `ack = self.usbread(1)[0]` (an `int`) and compares `if ack is self.Rsp.ACK:` (a `bytes` object `b"\x5A"`), which is always `False`, leaving Legacy DA hanging after `FINISH_CMD` (`0xD9`).
4. **`mtkclient/Library/DA/mtk_da_handler.py` (`da poke`)**: Reads `args.filename` unconditionally even though the CLI parser does not define it, raising `AttributeError` on `mtk da poke`.

In addition, `unlock_q1_bootloader.py wdt-reboot` bypasses `mtk reset` altogether by writing `0x00001209` to the MT6737M hardware watchdog reset register (`WDT_SWRST` at `0x10212014`) over Legacy DA `WRITE_REG32` (`0x7B`), triggering an immediate clean reboot over USB with no PMIC latch or battery pull.

---

## Files in This Directory
- `unlock_q1_bootloader.py` — Documented CLI tool to patch `mtkclient`, inspect `lk_a.bin`, back up partitions, unlock via SecCfgV3, and relock to factory `seccfg`.
- `seccfg_mtkclient.patch` — Unified diff of the `SecCfgV3.__init__` fix for `mtkclient`.
- `device_info.txt` & `all_props.txt` — Full pre-unlock ADB device/property dump.
- `fastboot_getvar.txt` — Complete `fastboot getvar all` output (locked state).
- `mtk_unlock_v3_V2.log` — Log of successful SecCfgV3 hardware-encrypted unlock (`0x1A00/0x1A00`).
- `fastboot_unlocked_verify.txt` — Post-unlock Fastboot verification (`unlocked: yes`, `secure: no`).

---

## Step-by-Step Unlock Procedure

### 1. Install `mtkclient` and Apply the Patch
```bash
sudo apt-get install -y adb fastboot python3-venv python3-dev libusb-1.0-0-dev
git clone --depth 1 https://github.com/bkerler/mtkclient.git
cd mtkclient && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt .

# Patch SecCfgV3 bugs in the venv
python3 unlock_q1_bootloader.py patch --mtk-venv /path/to/mtkclient/venv
```

### 2. Inspect `lk_a.bin` (Optional Verification)
```bash
python3 unlock_q1_bootloader.py inspect-lk --lk ../stock/lk_a.bin --vbmeta ../stock/vbmeta_a.bin
```

### 3. Back Up Critical Partitions First
```bash
python3 unlock_q1_bootloader.py backup --mtk /path/to/mtkclient/venv/bin/mtk --out ./backup
```
*(Reboot the device via `adb reboot` / `fastboot reboot`, or pull/reinsert the battery and plug in USB while `mtkclient` is listening.)*

### 4. Unlock the Bootloader
```bash
python3 unlock_q1_bootloader.py unlock --mtk /path/to/mtkclient/venv/bin/mtk --hwtype V2
# Clean hardware Watchdog reboot (no PMIC latch, no battery pull required!):
python3 unlock_q1_bootloader.py wdt-reboot --mtk-venv /path/to/mtkclient/venv
```
*(Note: standard `mtk reset` sends `FINISH_CMD` `0xD9` with a Python `int is bytes` bug in upstream `dalegacy_lib.py:finish()` that leaves the PMIC latched until a battery pull. `wdt-reboot` writes `0x00001209` to `MT6737M WDT_SWRST` at `0x10212014` over Legacy DA `WRITE_REG32` `0x7B`, triggering an immediate clean cold/warm reboot over USB.)*

### 5. Verify Unlocked State
- **In Android (`adb shell getprop`)**:
  - `ro.boot.flash.locked`: `0`
  - `ro.boot.vbmeta.device_state`: `unlocked`
  - `ro.boot.verifiedbootstate`: `orange`
- **In Fastboot (`adb reboot bootloader`)**:
  - `fastboot getvar unlocked` -> `yes`
  - `fastboot getvar secure` -> `no`

---

## Relocking the Bootloader

### Option 1: 100% Factory Relock (Original OEM Key)
Restore all 5 factory-signed stock images (`stock_system_a.img`, `stock_product_a.img`, `stock_vendor_a.img`, `boot_a.bin`, `vbmeta_a.bin`) as documented in [../stock/README.md](../stock/README.md), wipe `userdata` + `metadata`, and then restore factory-blank `seccfg.bin`:
```bash
python3 unlock_q1_bootloader.py relock-factory --mtk /path/to/mtkclient/venv/bin/mtk --seccfg ../stock/seccfg.bin
python3 unlock_q1_bootloader.py wdt-reboot --mtk-venv /path/to/mtkclient/venv
```

### Option 2: Self-Signed Relock with Custom AVB Key (Advanced)
Because `SBC=False` (Preloader does not verify `lk_a`'s signature) and the 256-byte RSA-2048 modulus used by `lk_a` to validate `vbmeta_a` sits at offset `0x6721c` of `lk_a.bin`, it is also possible to replace those 256 bytes with your own RSA-2048 public key modulus, sign custom `vbmeta_a` / `boot_a` / `system_a` / `vendor_a` images with `avbtool`, and relock `seccfg` for a `green` Verified Boot state on custom firmware (e.g., LineageOS 18.1 + TWRP). Always keep `../stock/lk_a.bin` backed up before experimenting.
