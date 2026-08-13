#!/usr/bin/env python3
from pathlib import Path
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = kernel_root / "KernelSU-Next/kernel/infra/su_mount_ns.c"
if not p.is_file():
    raise SystemExit(f"su_mount_ns.c not found: {p}")

s = p.read_text()

# KernelSU-Next v3.3.0 targets newer kernels where mount UAPI constants live
# in <uapi/linux/mount.h>. This crDroid Linux 4.14 tree has no such header;
# the MS_* mount flags used here are provided by <linux/fs.h> / uapi fs.h.
if "KSU_LEGACY_414_SU_MOUNT_NS_COMPAT" not in s:
    old = '#include <uapi/linux/mount.h>\n'
    if old not in s:
        raise SystemExit("Expected uapi/linux/mount.h include not found")
    new = (
        '#define KSU_LEGACY_414_SU_MOUNT_NS_COMPAT 1\n'
        '#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 2, 0)\n'
        '#include <uapi/linux/mount.h>\n'
        '#endif\n'
    )
    s = s.replace(old, new, 1)

# ksys_unshare() is not available in this Linux 4.14 tree; sys_unshare() is.
# Keep newer kernels on ksys_unshare while using the native 4.14 syscall helper.
if "KSU_LEGACY_UNSHARE_COMPAT" not in s:
    marker = '#define KSU_LEGACY_414_SU_MOUNT_NS_COMPAT 1\n'
    if marker not in s:
        raise SystemExit("su_mount_ns compatibility marker not found")
    compat = (
        '#define KSU_LEGACY_UNSHARE_COMPAT 1\n'
        '#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)\n'
        '#define ksu_unshare sys_unshare\n'
        '#else\n'
        '#define ksu_unshare ksys_unshare\n'
        '#endif\n'
    )
    s = s.replace(marker, marker + compat, 1)

if 'ksys_unshare(CLONE_NEWNS)' in s:
    s = s.replace('ksys_unshare(CLONE_NEWNS)', 'ksu_unshare(CLONE_NEWNS)', 1)

checks = (
    "KSU_LEGACY_414_SU_MOUNT_NS_COMPAT",
    "#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 2, 0)",
    "KSU_LEGACY_UNSHARE_COMPAT",
    "#define ksu_unshare sys_unshare",
    "ksu_unshare(CLONE_NEWNS)",
)
missing = [x for x in checks if x not in s]
if missing:
    raise SystemExit("su_mount_ns compatibility patch failed: " + ", ".join(missing))

p.write_text(s)
print(f"Patched {p}")
