#!/usr/bin/env python3
"""
Q-Tel Q1 (MT6737M) vendor_a AVB dm-verity Verification & RS(255,253) FEC Recovery Tool
======================================================================================

Verifies an ext4 + AVB 2.0 hashtree image (such as vendor_a.img) against its embedded
AVB0 hashtree descriptor and, if modified blocks exist within the RS(255,253) FEC
erasure-recovery limit (<= 2 corrupted blocks per 141-block interleaved stripe),
mathematically reconstructs the exact original OEM factory image bit-for-bit.

Usage:
  python3 recover_vendor_fec.py --input vendor_a.img --verify-only
  python3 recover_vendor_fec.py --input vendor_a.img --output stock_vendor_a.img
"""

import argparse
import hashlib
import struct
import sys


def init_gf256():
    """Initialize GF(2^8) tables with primitive polynomial 0x11d (libfec default)."""
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11d
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


def parse_avb_hashtree(data: bytes):
    footer_off = len(data) - 64
    f_magic, f_maj, f_min, orig_img_sz, vb_off, vb_sz = struct.unpack(">4sIIQQQ", data[footer_off : footer_off + 36])
    if f_magic != b"AVBf":
        raise ValueError("Missing AVBf footer at end of image")

    vb = data[vb_off : vb_off + vb_sz]
    _, _, _, auth_sz, aux_sz, _, _, _, _, _, _, _, _, _, desc_off, desc_sz, _, _ = struct.unpack(">4sIIQQIQQQQQQQQQQQI", vb[:124])
    aux = vb[256 + auth_sz : 256 + auth_sz + aux_sz]
    desc = aux[desc_off : desc_off + desc_sz]
    tag, nb = struct.unpack(">QQ", desc[:16])
    if tag != 1:
        raise ValueError(f"Expected AVB Hashtree descriptor (tag=1), got tag={tag}")

    body = desc[16 : 16 + nb]
    dm_ver, img_sz, tree_off, tree_sz, data_bs, hash_bs, fec_roots, fec_off, fec_sz = struct.unpack(">IQQQIIIQQ", body[:56])
    halg = body[56:88].split(b"\x00")[0].decode()
    plen, slen, rlen, _ = struct.unpack(">IIII", body[88:104])
    off = 164
    pname = body[off : off + plen].decode(); off += plen
    salt = body[off : off + slen]; off += slen
    root_digest = body[off : off + rlen]
    return {
        "part": pname,
        "img_sz": img_sz,
        "tree_off": tree_off,
        "tree_sz": tree_sz,
        "data_bs": data_bs,
        "hash_bs": hash_bs,
        "fec_roots": fec_roots,
        "fec_off": fec_off,
        "fec_sz": fec_sz,
        "halg": halg,
        "salt": salt,
        "root_digest": root_digest,
    }


def check_blocks(data: bytearray, info: dict):
    hfn = hashlib.sha256 if info["halg"] == "sha256" else hashlib.sha1
    dlen = len(hfn().digest())
    pad_dlen = 32
    bs = info["data_bs"]
    nblocks = info["img_sz"] // bs
    hpb = info["hash_bs"] // pad_dlen

    levels = []
    cur = nblocks
    while cur > 1:
        cur = (cur + hpb - 1) // hpb
        levels.append(cur)

    leaf_off = info["tree_off"] + sum(levels[1:]) * info["hash_bs"]
    bad = []
    for b in range(nblocks):
        expected = data[leaf_off + b * pad_dlen : leaf_off + b * pad_dlen + dlen]
        actual = hfn(info["salt"] + data[b * bs : (b + 1) * bs]).digest()
        if actual != expected:
            bad.append(b)

    root_ok = hfn(info["salt"] + data[info["tree_off"] : info["tree_off"] + info["hash_bs"]]).digest() == info["root_digest"]
    return bad, root_ok, levels


def main():
    ap = argparse.ArgumentParser(description="Verify or recover OEM AVB hashtree image using RS(255,253) FEC")
    ap.add_argument("--input", required=True, help="Input image path")
    ap.add_argument("--output", help="Output recovered image path")
    ap.add_argument("--verify-only", action="store_true", help="Only verify hashes without modifying")
    args = ap.parse_args()

    data = bytearray(open(args.input, "rb").read())
    info = parse_avb_hashtree(data)
    print(f"[*] Partition: {info['part']} | img_sz={hex(info['img_sz'])} | alg={info['halg']} | fec_roots={info['fec_roots']}")
    print(f"[*] Root digest: {info['root_digest'].hex()}")

    bad, root_ok, levels = check_blocks(data, info)
    print(f"[*] Root hash matches AVB0: {root_ok}")
    print(f"[*] Mismatched 4KB blocks : {len(bad)} / {info['img_sz'] // info['data_bs']}")
    if bad:
        print(f"    Bad blocks: {bad}")

    if args.verify_only or not bad:
        sys.exit(0 if (root_ok and not bad) else 1)

    if info["fec_roots"] != 2:
        raise NotImplementedError("Only fec_roots=2 (RS(255,253)) is implemented in this tool")

    bs = info["data_bs"]
    n_fec_blocks = (info["img_sz"] + info["tree_sz"]) // bs
    rsn = 255 - info["fec_roots"]
    rounds = (n_fec_blocks + rsn - 1) // rsn
    fec_off = info["fec_off"]

    buckets = {}
    for b in bad:
        buckets.setdefault(b % rounds, []).append(b)
    max_e = max(len(v) for v in buckets.values())
    if max_e > 2:
        print(f"[!] Cannot recover: stripe has {max_e} erasures (> 2).", file=sys.stderr)
        sys.exit(1)

    exp, log = init_gf256()
    gmul = lambda a, b: 0 if (a == 0 or b == 0) else exp[log[a] + log[b]]
    gdiv = lambda a, b: 0 if a == 0 else exp[log[a] + 255 - log[b]]

    for rd, blks in sorted(buckets.items()):
        erased_js = [b // rounds for b in blks]
        erased_set = set(erased_js)
        print(f"[*] Recovering stripe {rd:3d}: blocks {blks} ...")
        for bo in range(bs):
            cw = rd * bs + bo
            p0 = data[fec_off + cw * 2]
            p1 = data[fec_off + cw * 2 + 1]
            s0 = 0
            s1 = 0
            for j in range(rsn):
                if j in erased_set:
                    bval = 0
                else:
                    blk = j * rounds + rd
                    bval = data[blk * bs + bo] if blk < n_fec_blocks else 0
                s0 ^= bval
                s1 = gmul(s1, 2) ^ bval
            s0 ^= p0 ^ p1
            s1 = gmul(s1, 2) ^ p0
            s1 = gmul(s1, 2) ^ p1
            if len(erased_js) == 1:
                j1 = erased_js[0]
                m1 = s0
                assert s1 == gmul(m1, exp[254 - j1]), f"Syndrome cross-check failed at round={rd} bo={bo}"
                data[(j1 * rounds + rd) * bs + bo] = m1
            else:
                j1, j2 = erased_js
                a1 = exp[254 - j1]
                a2 = exp[254 - j2]
                m2 = gdiv(s1 ^ gmul(a1, s0), a1 ^ a2)
                m1 = s0 ^ m2
                data[(j1 * rounds + rd) * bs + bo] = m1
                data[(j2 * rounds + rd) * bs + bo] = m2

    bad_after, root_ok_after, _ = check_blocks(data, info)
    print(f"[+] Post-recovery mismatches: {len(bad_after)} / {info['img_sz'] // bs} | root_ok={root_ok_after}")
    assert not bad_after and root_ok_after

    out_path = args.output or (args.input + ".recovered")
    open(out_path, "wb").write(data)
    print(f"[+] Saved 100% verified OEM-identical image to {out_path}")


if __name__ == "__main__":
    main()
