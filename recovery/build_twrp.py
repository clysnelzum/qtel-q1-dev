#!/usr/bin/env python3
"""
TWRP 3.7.0_11-Q-Tel-Q1 Recovery-as-Boot Image Builder
=====================================================

Builds twrp_q1_boot.img (Android Boot Image v2, <= 32 MB) for the Q-Tel Q1
(k37m_m01c / MediaTek MT6737M / 32-bit armeabi-v7a / Android 11 SDK 30):

  - Reuses the stock Q1 Linux 4.19.127 ARMv7 zImage kernel and DTB.
  - Preserves stock first_stage_ramdisk/ (with unencrypted fstab.mt6735) so
    normal Android boot continues to work identically on slot _a.
  - Adapts a 32-bit Android 11 (SDK 30) MediaTek TWRP ramdisk with:
      * MediaTek musb-hdrc USB ConfigFS bringup (kernel_init_done=1, cmode=1,
        mtp.gs0 + ffs.adb + ffs.fastboot).
      * 32-bit LD_LIBRARY_PATH fix (/system/lib:/vendor/lib/hw).
      * Q-Tel Q1 branding across prop.default and TWRP version banner.
      * Boosted font sizes in twres/ui.xml (~1.6x-1.8x) for 240x320 QVGA.
      * Accurate recovery.fstab and twrp.flags for Q1 dynamic & physical slots.

Also generates vbmeta_disabled.bin (flags=0x03) and para_recovery.bin.
"""

import argparse
import hashlib
import os
import shutil
import struct
import subprocess


def extract_stock_boot(stock_boot_path: str, out_dir: str):
    os.makedirs(os.path.join(out_dir, "ramdisk"), exist_ok=True)
    data = open(stock_boot_path, "rb").read()
    k_size, k_addr, r_size, r_addr, s_size, s_addr, tags_addr, page_size, hdr_ver, os_ver = struct.unpack("<10I", data[8:48])
    dtb_size, dtb_addr = struct.unpack("<IQ", data[1648:1660])
    align = lambda x: ((x + page_size - 1) // page_size) * page_size
    off = page_size
    kernel = data[off : off + k_size]; off += align(k_size)
    ramdisk = data[off : off + r_size]; off += align(r_size)
    off += align(s_size)
    dtb = data[off : off + dtb_size]
    open(os.path.join(out_dir, "kernel"), "wb").write(kernel)
    open(os.path.join(out_dir, "ramdisk.raw"), "wb").write(ramdisk)
    open(os.path.join(out_dir, "dtb"), "wb").write(dtb)
    subprocess.check_call(
        ["bash", "-c", f"cd {out_dir}/ramdisk && gzip -dc ../ramdisk.raw | cpio -idmu --quiet"]
    )


def build_helpers(stock_vbmeta: str, out_dir: str):
    if stock_vbmeta and os.path.exists(stock_vbmeta):
        v = bytearray(open(stock_vbmeta, "rb").read())
        assert v[:4] == b"AVB0"
        v[120:124] = b"\x00\x00\x00\x03"  # HASHTREE_DISABLED | VERIFICATION_DISABLED
        open(os.path.join(out_dir, "vbmeta_disabled.bin"), "wb").write(v)
    p = bytearray(0x80000)
    p[:13] = b"boot-recovery"
    open(os.path.join(out_dir, "para_recovery.bin"), "wb").write(p)


def main():
    ap = argparse.ArgumentParser(description="Build TWRP 3.7.0_11-Q-Tel-Q1 recovery-as-boot image")
    ap.add_argument("--stock-boot", default="../stock/boot_a.bin")
    ap.add_argument("--stock-vbmeta", default="../stock/vbmeta_a.bin")
    ap.add_argument("--donor-ramdisk", default="/home/lfl/twrp_q1/donor_mtk/ramdisk")
    ap.add_argument("--noenc-fstab", default="../rom/fstab.mt6735.noenc")
    ap.add_argument("--work-dir", default="/tmp/twrp_q1_build")
    ap.add_argument("--output", default="./twrp_q1_boot.img")
    args = ap.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)
    stock_dir = os.path.join(args.work_dir, "stock_boot")
    work_rd = os.path.join(args.work_dir, "work_ramdisk")
    if os.path.exists(stock_dir):
        shutil.rmtree(stock_dir)
    if os.path.exists(work_rd):
        shutil.rmtree(work_rd)

    print("[1] Extracting stock kernel, DTB, and first_stage_ramdisk...")
    extract_stock_boot(args.stock_boot, stock_dir)
    stock_rd = os.path.join(stock_dir, "ramdisk")

    print("[2] Copying 32-bit Android 11 (SDK 30) MediaTek TWRP donor ramdisk...")
    subprocess.check_call(["cp", "-a", args.donor_ramdisk, work_rd])

    print("[3] Preserving stock first_stage_ramdisk (normal Android boot)...")
    dst_fsr = os.path.join(work_rd, "first_stage_ramdisk")
    if os.path.exists(dst_fsr):
        shutil.rmtree(dst_fsr)
    subprocess.check_call(["cp", "-a", os.path.join(stock_rd, "first_stage_ramdisk"), dst_fsr])
    if args.noenc_fstab and os.path.exists(args.noenc_fstab):
        shutil.copy2(args.noenc_fstab, os.path.join(dst_fsr, "fstab.mt6735"))
    os.makedirs(os.path.join(work_rd, "metadata"), exist_ok=True)

    print("[4] Cleaning third-party rc/artifacts and configuring MediaTek MT6737M USB...")
    for f in ["init.recovery.mt6739.rc", "init.recovery.samsung.rc", "ramdisk-files.txt", "ramdisk-files.sha256sum", "recovery.fstab"]:
        p = os.path.join(work_rd, f)
        if os.path.exists(p):
            os.remove(p)

    mtk_pl = os.path.join(stock_rd, "system/bin/mtk_plpath_utils")
    if os.path.exists(mtk_pl):
        shutil.copy2(mtk_pl, os.path.join(work_rd, "system/bin/mtk_plpath_utils"))

    init_mt6735 = """on early-init
    write /sys/module/musb_hdrc/parameters/kernel_init_done 1

on init
    setprop sys.usb.configfs 1
    setprop sys.usb.ffs.aio_compat 1
    setprop sys.usb.controller musb-hdrc

on fs
    write /sys/class/udc/musb-hdrc/device/cmode 1
    write /config/usb_gadget/g1/bcdDevice 0x0223
    write /config/usb_gadget/g1/bcdUSB 0x0200
    write /config/usb_gadget/g1/configs/b.1/MaxPower 500
    mkdir /dev/block/platform/mtk-msdc.0
    symlink /dev/block/platform/bootdevice /dev/block/platform/mtk-msdc.0/11230000.msdc0
    symlink /dev/block/platform/externdevice /dev/block/platform/mtk-msdc.0/11240000.msdc1

on post-fs
    write /sys/class/udc/musb-hdrc/device/cmode 1
    mkdir /config/usb_gadget/g1/functions/mtp.gs0
    write /config/usb_gadget/g1/functions/mtp.gs0/os_desc/interface.MTP/compatible_id "MTP"

on post-fs-data
    symlink /dev/block/mmcblk0boot0 /dev/block/platform/mtk-msdc.0/11230000.msdc0/by-name/preloader_a
    symlink /dev/block/mmcblk0boot1 /dev/block/platform/mtk-msdc.0/11230000.msdc0/by-name/preloader_b
"""
    open(os.path.join(work_rd, "init.recovery.mt6735.rc"), "w").write(init_mt6735)
    os.chmod(os.path.join(work_rd, "init.recovery.mt6735.rc"), 0o750)

    init_usb = """on property:sys.usb.config=none && property:sys.usb.configfs=1
    rm /config/usb_gadget/g1/configs/b.1/f2

on property:sys.usb.config=mtp,adb
    start adbd

on property:sys.usb.config=mtp,adb && property:sys.usb.ffs.ready=1 && property:sys.usb.configfs=1
    write /config/usb_gadget/g1/idProduct 0x4EE2
    write /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration "mtp,adb"
    symlink /config/usb_gadget/g1/functions/mtp.gs0 /config/usb_gadget/g1/configs/b.1/f1
    symlink /config/usb_gadget/g1/functions/ffs.adb /config/usb_gadget/g1/configs/b.1/f2
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}

on property:sys.usb.config=mtp && property:sys.usb.configfs=1
    write /config/usb_gadget/g1/idProduct 0x4EE1
    write /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration "mtp"
    symlink /config/usb_gadget/g1/functions/mtp.gs0 /config/usb_gadget/g1/configs/b.1/f1
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}
"""
    open(os.path.join(work_rd, "init.recovery.usb.rc"), "w").write(init_usb)
    os.chmod(os.path.join(work_rd, "init.recovery.usb.rc"), 0o750)

    init_rc_path = os.path.join(work_rd, "system/etc/init/hw/init.rc")
    init_rc = open(init_rc_path).read().replace(
        "export LD_LIBRARY_PATH /system/lib64:/vendor/lib64/hw",
        "export LD_LIBRARY_PATH /system/lib:/vendor/lib/hw",
    )
    open(init_rc_path, "w").write(init_rc)

    print("[5] Writing Q-Tel Q1 recovery.fstab, twrp.flags, and prop.default...")
    open(os.path.join(work_rd, "system/etc/recovery.fstab"), "w").write(
        """# Q-Tel Q1 (MT6737M / k37m_m01c) recovery.fstab
/dev/block/platform/bootdevice/by-name/md_udc /metadata ext4 noatime,nosuid,nodev,discard wait,check,formattable
/dev/block/platform/bootdevice/by-name/userdata /data f2fs noatime,nosuid,nodev,discard,noflush_merge,reserve_root=134217,resgid=1065 wait,check,quota,reservedsize=128M,formattable,resize,checkpoint=fs
/dev/block/platform/bootdevice/by-name/para /misc emmc defaults defaults
"""
    )
    open(os.path.join(work_rd, "system/etc/twrp.flags"), "w").write(
        """# Q-Tel Q1 (MT6737M / k37m_m01c) twrp.flags
/system_root    ext4    /dev/block/mapper/system_a                              flags=display="System";backup=0;wipeingui=0
/vendor         ext4    /dev/block/mapper/vendor_a                              flags=display="Vendor";backup=0;wipeingui=0
/product        ext4    /dev/block/mapper/product_a                             flags=display="Product";backup=0;wipeingui=0
/system_image   emmc    /dev/block/mapper/system_a                              flags=display="System Image";backup=1;flashimg=1
/vendor_image   emmc    /dev/block/mapper/vendor_a                              flags=display="Vendor Image";backup=1;flashimg=1
/product_image  emmc    /dev/block/mapper/product_a                             flags=display="Product Image";backup=1;flashimg=1

/boot           emmc    /dev/block/platform/bootdevice/by-name/boot_a           flags=display="Boot (Slot A)";backup=1;flashimg=1
/boot_b         emmc    /dev/block/platform/bootdevice/by-name/boot_b           flags=display="Boot (Slot B)";backup=1;flashimg=1
/dtbo           emmc    /dev/block/platform/bootdevice/by-name/dtbo_a           flags=display="DTBO (Slot A)";backup=1;flashimg=1
/vbmeta         emmc    /dev/block/platform/bootdevice/by-name/vbmeta_a         flags=display="VBMeta (Slot A)";backup=1;flashimg=1
/vbmeta_system  emmc    /dev/block/platform/bootdevice/by-name/vbmeta_system_a  flags=display="VBMeta System";backup=1;flashimg=1
/vbmeta_vendor  emmc    /dev/block/platform/bootdevice/by-name/vbmeta_vendor_a  flags=display="VBMeta Vendor";backup=1;flashimg=1
/lk             emmc    /dev/block/platform/bootdevice/by-name/lk_a             flags=display="Bootloader (LK)";backup=1
/seccfg         emmc    /dev/block/platform/bootdevice/by-name/seccfg           flags=display="SecCfg";backup=1
/nvram          emmc    /dev/block/platform/bootdevice/by-name/nvram            flags=display="NVRAM";backup=1
/nvdata         ext4    /dev/block/platform/bootdevice/by-name/nvdata           flags=display="NVDATA";backup=1
/proinfo        emmc    /dev/block/platform/bootdevice/by-name/proinfo          flags=display="ProInfo";backup=1
/protect_f      ext4    /dev/block/platform/bootdevice/by-name/protect1         flags=display="Protect1";backup=1
/protect_s      ext4    /dev/block/platform/bootdevice/by-name/protect2         flags=display="Protect2";backup=1
/logo           emmc    /dev/block/platform/bootdevice/by-name/logo             flags=display="Logo";backup=1;flashimg=1
/persistent     emmc    /dev/block/platform/bootdevice/by-name/frp              flags=display="FRP";backup=1

/external_sd    auto    /dev/block/mmcblk1p1    /dev/block/mmcblk1              flags=display="MicroSD";storage;wipeingui;removable
/usb_otg        auto    /dev/block/sda1         /dev/block/sda                  flags=display="USB-OTG";storage;wipeingui;removable
"""
    )

    prop_path = os.path.join(work_rd, "prop.default")
    fp = "Q-Tel/full_k37m_m01c/k37m_m01c:13/RP1A.200720.011/mp1k61v164bspP1:user/release-keys"
    overrides = {
        "ro.product.brand": "Q-Tel", "ro.product.device": "k37m_m01c", "ro.product.manufacturer": "Q-Tel",
        "ro.product.model": "Q1", "ro.product.name": "full_k37m_m01c",
        "ro.product.system.brand": "Q-Tel", "ro.product.system.device": "k37m_m01c", "ro.product.system.manufacturer": "Q-Tel",
        "ro.product.system.model": "Q1", "ro.product.system.name": "full_k37m_m01c",
        "ro.product.vendor.brand": "Q-Tel", "ro.product.vendor.device": "k37m_m01c", "ro.product.vendor.manufacturer": "Q-Tel",
        "ro.product.vendor.model": "Q1", "ro.product.vendor.name": "full_k37m_m01c",
        "ro.product.odm.brand": "Q-Tel", "ro.product.odm.device": "k37m_m01c", "ro.product.odm.manufacturer": "Q-Tel",
        "ro.product.odm.model": "Q1", "ro.product.odm.name": "full_k37m_m01c",
        "ro.product.product.brand": "Q-Tel", "ro.product.product.device": "k37m_m01c", "ro.product.product.manufacturer": "Q-Tel",
        "ro.product.product.model": "Q1", "ro.product.product.name": "full_k37m_m01c",
        "ro.product.system_ext.brand": "Q-Tel", "ro.product.system_ext.device": "k37m_m01c", "ro.product.system_ext.manufacturer": "Q-Tel",
        "ro.product.system_ext.model": "Q1", "ro.product.system_ext.name": "full_k37m_m01c",
        "ro.build.product": "k37m_m01c", "ro.build.display.id": "RP1A.200720.011", "ro.build.flavor": "full_k37m_m01c-eng",
        "ro.build.fingerprint": fp, "ro.product.build.fingerprint": fp, "ro.system.build.fingerprint": fp,
        "ro.vendor.build.fingerprint": fp, "ro.odm.build.fingerprint": fp, "ro.system_ext.build.fingerprint": fp,
        "ro.bootimage.build.fingerprint": fp,
        "ro.build.description": "full_k37m_m01c-user 13 RP1A.200720.011 mp1k61v164bspP1 release-keys",
        "ro.product.board": "k37m_m01c", "ro.board.platform": "mt6737m", "ro.hardware": "mt6735",
        "ro.adb.secure": "0", "ro.secure": "0", "ro.debuggable": "1",
        "ro.build.ab_update": "true", "ro.boot.dynamic_partitions": "true",
        "persist.sys.usb.config": "adb", "sys.usb.controller": "musb-hdrc", "sys.usb.configfs": "1",
        "ro.twrp.boot": "1", "ro.twrp.version": "3.7.0_11-Q-Tel-Q1",
    }
    out_lines, seen = [], set()
    for line in open(prop_path):
        low = line.lower()
        if any(b in low for b in ["samsung", "a02", "galaxy", "mt6739"]) and line.lstrip().startswith("#"):
            continue
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in overrides:
                if k not in seen:
                    out_lines.append(f"{k}={overrides[k]}\n")
                    seen.add(k)
                continue
            if any(b in low for b in ["samsung", "a02", "galaxy", "mt6739"]):
                continue
        out_lines.append(line)
    for k, v in overrides.items():
        if k not in seen:
            out_lines.append(f"{k}={v}\n")
    open(prop_path, "w").writelines(out_lines)

    print("[6] Boosting font sizes for 240x320 QVGA and branding TWRP binary...")
    ui_path = os.path.join(work_rd, "twres/ui.xml")
    ui = open(ui_path).read()
    for old, new in [
        ('name="font_l" filename="RobotoCondensed-Regular.ttf" size="54"', 'name="font_l" filename="RobotoCondensed-Regular.ttf" size="84"'),
        ('name="font_m" filename="RobotoCondensed-Regular.ttf" size="42"', 'name="font_m" filename="RobotoCondensed-Regular.ttf" size="68"'),
        ('name="font_s" filename="RobotoCondensed-Regular.ttf" size="36"', 'name="font_s" filename="RobotoCondensed-Regular.ttf" size="58"'),
        ('name="fixed" filename="DroidSansMono.ttf" size="30"', 'name="fixed" filename="DroidSansMono.ttf" size="52"'),
        ('name="keylabel" filename="RobotoCondensed-Regular.ttf" size="64"', 'name="keylabel" filename="RobotoCondensed-Regular.ttf" size="96"'),
        ('name="keylabel-small" filename="RobotoCondensed-Regular.ttf" size="46"', 'name="keylabel-small" filename="RobotoCondensed-Regular.ttf" size="72"'),
        ('name="keylabel-longpress" filename="RobotoCondensed-Regular.ttf" size="32"', 'name="keylabel-longpress" filename="RobotoCondensed-Regular.ttf" size="50"'),
    ]:
        ui = ui.replace(old, new)
    open(ui_path, "w").write(ui)

    rec_path = os.path.join(work_rd, "system/bin/recovery")
    rec_data = open(rec_path, "rb").read().replace(b"3.7.0_11-A022M-test1", b"3.7.0_11-Q-Tel-Q1\x00\x00\x00")
    open(rec_path, "wb").write(rec_data)

    print("[7] Packing ramdisk and Android Boot Image v2...")
    rd_gz = os.path.join(args.work_dir, "ramdisk_twrp.cpio.gz")
    subprocess.check_call(["bash", "-c", f"cd {work_rd} && find . | sort | cpio -H newc -o -R 0:0 --quiet | gzip -9 > {rd_gz}"])
    rd_data = open(rd_gz, "rb").read()

    stock = open(args.stock_boot, "rb").read()
    k_size, k_addr, r_size, r_addr, s_size, s_addr, tags_addr, page_size, hdr_ver, os_ver = struct.unpack("<10I", stock[8:48])
    name, cmdline, extra_cmdline = stock[48:64], stock[64:576], stock[608:1632]
    _, _, hdr_size = struct.unpack("<IQI", stock[1632:1648])
    _, dtb_addr = struct.unpack("<IQ", stock[1648:1660])
    kernel = open(os.path.join(stock_dir, "kernel"), "rb").read()
    dtb = open(os.path.join(stock_dir, "dtb"), "rb").read()

    h = hashlib.sha1()
    for blob in [kernel, rd_data, b"", b"", dtb]:
        h.update(blob); h.update(struct.pack("<I", len(blob)))
    img_id = h.digest() + b"\x00" * 12

    pad = lambda b: b if len(b) % page_size == 0 else b + b"\x00" * (page_size - (len(b) % page_size))
    header = bytearray(page_size)
    header[0:8] = b"ANDROID!"
    header[8:48] = struct.pack("<10I", len(kernel), k_addr, len(rd_data), r_addr, 0, s_addr, tags_addr, page_size, hdr_ver, os_ver)
    header[48:64] = name
    header[64:576] = cmdline
    header[576:608] = img_id
    header[608:1632] = extra_cmdline
    header[1632:1648] = struct.pack("<IQI", 0, 0, hdr_size)
    header[1648:1660] = struct.pack("<IQ", len(dtb), dtb_addr)

    out = bytes(header) + pad(kernel) + pad(rd_data) + pad(dtb)
    assert len(out) <= 0x2000000, "Output exceeds 32 MB boot_a partition!"
    open(args.output, "wb").write(out)
    build_helpers(args.stock_vbmeta, os.path.dirname(os.path.abspath(args.output)))
    print(f"[+] Built {args.output} ({len(out)/1024/1024:.2f} MB) successfully!")


if __name__ == "__main__":
    main()
