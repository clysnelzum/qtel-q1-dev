#!/usr/bin/env python3
"""
Q-Tel Q1 (k37m_m01c / MediaTek MT6737M) Bootloader Unlock & Relock Helper
=========================================================================

Automates:
  1. Patching two upstream bugs in mtkclient's SecCfgV3 implementation
     (blank factory seccfg initialization fails with hwtype=None and
     imginfo initialized as flat bytes instead of 20 x 0x68 blocks).
  2. Inspecting lk_a.bin to verify SecCfgV3 ("AND_SECCFG_v") and locate
     the embedded AVB 2.0 RSA-2048 public key modulus.
  3. Backing up critical MediaTek partitions via Preloader (0e8d:2000).
  4. Unlocking or relocking the bootloader via mtkclient without requiring
     physical Volume Up / Volume Down buttons (absent on the Q1 T9 keypad).

Usage:
  python3 unlock_q1_bootloader.py patch --mtk-venv /path/to/mtkclient/venv
  python3 unlock_q1_bootloader.py inspect-lk --lk ../stock/lk_a.bin --vbmeta ../stock/vbmeta_a.bin
  python3 unlock_q1_bootloader.py backup --mtk /path/to/mtk --out ./backup
  python3 unlock_q1_bootloader.py unlock --mtk /path/to/mtk
  python3 unlock_q1_bootloader.py relock-factory --mtk /path/to/mtk --seccfg ../stock/seccfg.bin
  python3 unlock_q1_bootloader.py wdt-reboot --mtk-venv /path/to/mtkclient/venv
"""

import argparse
import glob
import hashlib
import os
import struct
import subprocess
import sys


def find_mtkclient_file(venv_path: str, rel_path: str) -> str:
    pattern = os.path.join(venv_path, "lib", "python*", "site-packages", "mtkclient", rel_path)
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(f"Could not find mtkclient/{rel_path} under {venv_path}")
    return matches[0]


def cmd_patch(args):
    # 1. Patch SecCfgV3.__init__ in Library/Hardware/seccfg.py
    seccfg_path = args.seccfg_py or find_mtkclient_file(args.mtk_venv, os.path.join("Library", "Hardware", "seccfg.py"))
    print(f"[*] Patching {seccfg_path} ...")
    with open(seccfg_path, "r", encoding="utf-8") as f:
        src = f.read()

    old_block = """        self.hwtype = None
        self.data = None
        self.org_data = None
        self.hwc = _hwc
        self.mtk = mtk
        self.info_header = b"AND_SECCFG_v\\x00\\x00\\x00\\x00"
        self.magic = 0x4D4D4D4D
        self.seccfg_ver = 3
        self.seccfg_size = 0x1860
        self.seccfg_enc_len = 0x01000000  # 0x07F20000 for unlocked
        self.seccfg_enc_offset = 0
        self.endflag = 0x45454545
        self.sw_sec_lock_try = 0
        self.sw_sec_lock_done = 0
        self.page_size = 0
        self.page_count = 0
        self.imginfo = b"\\x00" * (0x68 * 20)"""

    new_block = """        self.hwtype = os.environ.get("SECCFG_HWTYPE", "V2")
        self.data = None
        self.org_data = None
        self.hwc = _hwc
        self.mtk = mtk
        self.info_header = b"AND_SECCFG_v\\x00\\x00\\x00\\x00"
        self.magic = 0x4D4D4D4D
        self.seccfg_ver = 3
        self.seccfg_size = 0x1860
        self.seccfg_enc_len = 0x01000000  # 0x07F20000 for unlocked
        self.seccfg_enc_offset = 0
        self.endflag = 0x45454545
        self.sw_sec_lock_try = 0
        self.sw_sec_lock_done = 0
        self.page_size = 0
        self.page_count = 0
        self.imginfo = [b"\\x00" * 0x68 for _ in range(20)]"""

    if 'os.environ.get("SECCFG_HWTYPE", "V2")' in src:
        print("[+] seccfg.py already patched.")
    elif old_block in src:
        src = src.replace(old_block, new_block, 1)
        with open(seccfg_path, "w", encoding="utf-8") as f:
            f.write(src)
        print("[+] Patched seccfg.py (SecCfgV3 hwtype=V2 + 20x0x68 imginfo list).")
    else:
        print("[!] Expected SecCfgV3.__init__ block not found; apply seccfg_mtkclient.patch manually.", file=sys.stderr)
        sys.exit(1)

    if args.seccfg_py:
        return

    # 2. Patch Legacy DA finish() bug (int `is` bytes) in Library/DA/legacy/dalegacy_lib.py
    dalegacy_path = find_mtkclient_file(args.mtk_venv, os.path.join("Library", "DA", "legacy", "dalegacy_lib.py"))
    with open(dalegacy_path, "r", encoding="utf-8") as f:
        dsrc = f.read()
    old_fin = """    def finish(self, value):
        self.usbwrite(self.Cmd.FINISH_CMD)  # D9
        ack = self.usbread(1)[0]
        if ack is self.Rsp.ACK:
            self.usbwrite(pack(">I", value))
            ack = self.usbread(1)[0]
            if ack is self.Rsp.ACK:
                return True
        return False"""
    new_fin = """    def finish(self, value):
        self.usbwrite(self.Cmd.FINISH_CMD)  # D9
        ack = self.usbread(1)
        if ack == self.Rsp.ACK:
            self.usbwrite(pack(">I", value))
            ack = self.usbread(1)
            if ack == self.Rsp.ACK:
                return True
        return False"""
    if new_fin in dsrc:
        print("[+] dalegacy_lib.py already patched.")
    elif old_fin in dsrc:
        with open(dalegacy_path, "w", encoding="utf-8") as f:
            f.write(dsrc.replace(old_fin, new_fin, 1))
        print("[+] Patched dalegacy_lib.py (fixed finish() ACK bytes comparison).")

    # 3. Patch `mtk da poke` AttributeError (missing args.filename) in Library/DA/mtk_da_handler.py
    dahandler_path = find_mtkclient_file(args.mtk_venv, os.path.join("Library", "DA", "mtk_da_handler.py"))
    with open(dahandler_path, "r", encoding="utf-8") as f:
        hsrc = f.read()
    old_poke = """            elif subcmd == "poke":
                addr = getint(args.address)
                filename = args.filename
                data = args.data
                self.da_poke(addr=addr, data=data, filename=filename)"""
    new_poke = """            elif subcmd == "poke":
                addr = getint(args.address)
                filename = getattr(args, "filename", None)
                data = args.data
                self.da_poke(addr=addr, data=data, filename=filename)"""
    if new_poke in hsrc:
        print("[+] mtk_da_handler.py already patched.")
    elif old_poke in hsrc:
        with open(dahandler_path, "w", encoding="utf-8") as f:
            f.write(hsrc.replace(old_poke, new_poke, 1))
        print("[+] Patched mtk_da_handler.py (fixed da poke getattr(args, 'filename', None)).")


def cmd_inspect_lk(args):
    lk = open(args.lk, "rb").read()
    magic = lk[:4]
    size = struct.unpack("<I", lk[4:8])[0]
    name = lk[8:40].split(b"\x00")[0].decode(errors="ignore")
    print(f"LK Header: magic={magic.hex()} size={hex(size)} name={name}")
    for marker in [b"AND_SECCFG_v", b"AB2D3F3B37890C1A", b"sec_fb_unlock.c", b"Yes (Volume UP)"]:
        idx = lk.find(marker)
        print(f"  marker {marker.decode():20s}: {hex(idx) if idx != -1 else 'NOT FOUND'}")

    if args.vbmeta and os.path.exists(args.vbmeta):
        v = open(args.vbmeta, "rb").read()
        _, _, _, auth_sz, _, _, _, _, _, _, pk_off, pk_sz = struct.unpack(">4sIIQQIQQQQQQ", v[:80])
        pk = v[256 + auth_sz + pk_off : 256 + auth_sz + pk_off + pk_sz]
        mod = pk[8:264]
        off = lk.find(mod)
        print(f"  AVB RSA-2048 pubkey SHA256 : {hashlib.sha256(pk).hexdigest()}")
        print(f"  256B RSA modulus in lk_a   : {hex(off) if off != -1 else 'NOT FOUND'}")


def cmd_backup(args):
    os.makedirs(args.out, exist_ok=True)
    parts = ["seccfg", "lk_a", "vbmeta_a", "boot_a", "proinfo", "nvram", "frp", "para"]
    files = [os.path.join(args.out, f"{p}.bin") for p in parts]
    cmd = ["sudo", args.mtk, "r", ",".join(parts), ",".join(files)]
    print("[*] Running:", " ".join(cmd))
    print("[*] Trigger reboot or connect powered-off device to catch MT65xx Preloader (0e8d:2000)...")
    subprocess.check_call(cmd)


def cmd_unlock(args):
    env = os.environ.copy()
    env["SECCFG_HWTYPE"] = args.hwtype
    cmd = ["sudo", f"SECCFG_HWTYPE={args.hwtype}", args.mtk, "da", "seccfg", "unlock"]
    print("[*] Running:", " ".join(cmd))
    print("[*] Sending 'v3' to initialize SecCfgV3 if seccfg is factory-blank...")
    subprocess.run(cmd, input=b"v3\n", check=True)
    print("[+] Done! Run 'python3 unlock_q1_bootloader.py wdt-reboot --mtk-venv <venv>' to reboot cleanly without pulling the battery.")


def cmd_relock_factory(args):
    if not os.path.exists(args.seccfg):
        print(f"[!] Factory seccfg backup not found: {args.seccfg}", file=sys.stderr)
        sys.exit(1)
    cmd = ["sudo", args.mtk, "w", "seccfg", args.seccfg]
    print("[!] WARNING: Only relock after restoring 100% stock boot_a, vbmeta_a, system_a, product_a, and vendor_a!")
    print("[*] Running:", " ".join(cmd))
    subprocess.check_call(cmd)
    print("[+] Wrote factory seccfg. Run 'python3 unlock_q1_bootloader.py wdt-reboot --mtk-venv <venv>' to reboot cleanly without pulling the battery.")


def cmd_wdt_reboot(args):
    """Trigger a clean hardware Watchdog SW reset (MT6737M WDT_SWRST 0x10212014 = 0x1209)
    directly from an active Legacy DA session, avoiding the PMIC power-off latch
    caused by 'mtk reset' (FINISH_CMD 0xD9)."""
    py = os.path.join(args.mtk_venv, "bin", "python")
    if not os.path.exists(py):
        py = sys.executable
    helper = (
        "import os, struct\n"
        "from mtkclient.Library.Connection.usblib import UsbClass\n"
        "from mtkclient.config.usb_ids import default_ids\n"
        "usb = UsbClass(portconfig=default_ids, loglevel=20)\n"
        "assert usb.connect(), 'Could not connect to active Legacy DA (0e8d:2000)'\n"
        "usb.usbwrite(b'\\x7a' + struct.pack('>I', 0x10212000))\n"
        "wdt_mode = struct.unpack('>I', usb.usbread(4))[0]\n"
        "ack = usb.usbread(1)\n"
        "assert ack == b'\\x5a', f'Unexpected Legacy DA ACK: {ack!r}'\n"
        "print(f'[+] Legacy DA synced (WDT_MODE=0x{wdt_mode:08x}). Triggering WDT_SWRST...')\n"
        "usb.usbwrite(b'\\x7b' + struct.pack('>II', 0x10212014, 0x00001209))\n"
        "try:\n"
        "    usb.usbread(1)\n"
        "except Exception:\n"
        "    pass\n"
        "try:\n"
        "    usb.close()\n"
        "except Exception:\n"
        "    pass\n"
        "if os.path.exists('.state'):\n"
        "    os.remove('.state')\n"
        "print('[+] Hardware WDT reset sent; device is rebooting without battery pull.')\n"
    )
    cmd = ["sudo", py, "-c", helper]
    subprocess.check_call(cmd)


def main():
    p = argparse.ArgumentParser(description="Q-Tel Q1 (MT6737M) Bootloader Unlock/Relock Tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_patch = sub.add_parser("patch", help="Patch mtkclient's SecCfgV3 bugs")
    p_patch.add_argument("--mtk-venv", default="/home/lfl/bootloader_unlock/mtkclient/venv")
    p_patch.add_argument("--seccfg-py", default=None, help="Direct path to seccfg.py")
    p_patch.set_defaults(func=cmd_patch)

    p_lk = sub.add_parser("inspect-lk", help="Inspect lk_a.bin for SecCfg version and AVB pubkey")
    p_lk.add_argument("--lk", default="../stock/lk_a.bin")
    p_lk.add_argument("--vbmeta", default="../stock/vbmeta_a.bin")
    p_lk.set_defaults(func=cmd_inspect_lk)

    p_bak = sub.add_parser("backup", help="Back up critical partitions via Preloader")
    p_bak.add_argument("--mtk", default="mtk")
    p_bak.add_argument("--out", default="./backup")
    p_bak.set_defaults(func=cmd_backup)

    p_unl = sub.add_parser("unlock", help="Unlock bootloader via SecCfgV3 (HACC/SEJ V2)")
    p_unl.add_argument("--mtk", default="mtk")
    p_unl.add_argument("--hwtype", default="V2", choices=["V2", "V3", "V4", "SW"])
    p_unl.set_defaults(func=cmd_unlock)

    p_rel = sub.add_parser("relock-factory", help="Restore factory-blank seccfg to relock bootloader")
    p_rel.add_argument("--mtk", default="mtk")
    p_rel.add_argument("--seccfg", default="../stock/seccfg.bin")
    p_rel.set_defaults(func=cmd_relock_factory)

    p_wdt = sub.add_parser("wdt-reboot", help="Trigger hardware WDT_SWRST reboot from Legacy DA (no battery pull)")
    p_wdt.add_argument("--mtk-venv", default="/home/lfl/bootloader_unlock/mtkclient/venv")
    p_wdt.set_defaults(func=cmd_wdt_reboot)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
