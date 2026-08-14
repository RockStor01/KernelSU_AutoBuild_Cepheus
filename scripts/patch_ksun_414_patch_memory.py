#!/usr/bin/env python3
from pathlib import Path
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = kernel_root / "KernelSU-Next/kernel/hook/arm64/patch_memory.c"
if not p.is_file():
    raise SystemExit(f"patch_memory.c not found: {p}")

s = p.read_text()

marker = '#include "asm-generic/fixmap.h"\n'
if "KSU_LEGACY_414_PATCH_MEMORY_COMPAT" not in s:
    if marker not in s:
        raise SystemExit("Expected fixmap include not found in patch_memory.c")
    compat = (
        '#include <linux/version.h>\n'
        '#define KSU_LEGACY_414_PATCH_MEMORY_COMPAT 1\n'
        '#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)\n'
        '#ifndef __pte_to_phys\n'
        '#define __pte_to_phys(pte) ((phys_addr_t)pte_pfn(pte) << PAGE_SHIFT)\n'
        '#endif\n'
        '#ifndef copy_to_kernel_nofault\n'
        '#define copy_to_kernel_nofault(dst, src, len) probe_kernel_write((dst), (src), (len))\n'
        '#endif\n'
        '#endif\n'
    )
    s = s.replace(marker, marker + compat, 1)

old_icache = '#define ksu_flush_icache(start, end) __flush_icache_range\n'
new_icache = (
    '#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)\n'
    '#define ksu_flush_icache(start, end) flush_icache_range((start), (end))\n'
    '#else\n'
    '#define ksu_flush_icache(start, end) __flush_icache_range\n'
    '#endif\n'
)
if old_icache in s:
    s = s.replace(old_icache, new_icache, 1)

checks = (
    "KSU_LEGACY_414_PATCH_MEMORY_COMPAT",
    "#define __pte_to_phys",
    "#define copy_to_kernel_nofault",
    "flush_icache_range((start), (end))",
)
missing = [check for check in checks if check not in s]
if missing:
    raise SystemExit("patch_memory compatibility patch failed: " + ", ".join(missing))

p.write_text(s)
print(f"Patched {p}")

# Linux 4.14 has min/max helpers through linux/kernel.h but does not provide
# the newer standalone linux/minmax.h header used by KSUN v3.3.0 sulog.
# It also predates ktime_get_boottime_ts64() and strncpy_from_user_nofault().
sulog_event = kernel_root / "KernelSU-Next/kernel/sulog/event.c"
if not sulog_event.is_file():
    raise SystemExit(f"sulog event.c not found: {sulog_event}")
event_src = sulog_event.read_text()
if '#include <linux/minmax.h>\n' in event_src:
    event_src = event_src.replace('#include <linux/minmax.h>\n', '#include <linux/kernel.h>\n', 1)

compat_marker = '#include <linux/version.h>\n'
compat_block = (
    '#include <linux/version.h>\n'
    '#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)\n'
    '#ifndef ktime_get_boottime_ts64\n'
    '#define ktime_get_boottime_ts64(ts) (*(ts) = ktime_to_timespec64(ktime_get_boottime()))\n'
    '#endif\n'
    '#ifndef strncpy_from_user_nofault\n'
    '#define strncpy_from_user_nofault(dst, src, count) strncpy_from_user((dst), (src), (count))\n'
    '#endif\n'
    '#endif\n'
)
if 'KERNEL_VERSION(5, 0, 0)' not in event_src or 'ktime_get_boottime_ts64(ts)' not in event_src:
    if compat_marker not in event_src:
        raise SystemExit("sulog linux/version.h marker missing")
    event_src = event_src.replace(compat_marker, compat_block, 1)

checks = (
    '#include <linux/kernel.h>',
    '#define ktime_get_boottime_ts64(ts)',
    '#define strncpy_from_user_nofault(dst, src, count)',
)
missing = [check for check in checks if check not in event_src]
if missing:
    raise SystemExit("sulog Linux 4.14 compatibility patch failed: " + ", ".join(missing))
if '#include <linux/minmax.h>' in event_src:
    raise SystemExit("sulog minmax compatibility patch failed")
sulog_event.write_text(event_src)
print(f"Patched {sulog_event} for Linux 4.14 SULog compatibility")

# Linux 4.14 file_operations::poll returns unsigned int and predates __poll_t.
# KSUN v3.3.0 uses __poll_t in the shared event queue and SULog fd wrapper,
# so normalize all three declarations/definitions to the 4.14 ABI type.
for rel in (
    "KernelSU-Next/kernel/infra/event_queue.h",
    "KernelSU-Next/kernel/infra/event_queue.c",
    "KernelSU-Next/kernel/sulog/fd.c",
):
    poll_file = kernel_root / rel
    if not poll_file.is_file():
        raise SystemExit(f"SULog poll compatibility file not found: {poll_file}")
    poll_src = poll_file.read_text()
    if '__poll_t' in poll_src:
        poll_src = poll_src.replace('__poll_t', 'unsigned int')
    if '__poll_t' in poll_src:
        raise SystemExit(f"SULog __poll_t compatibility patch failed: {poll_file}")
    poll_file.write_text(poll_src)
    print(f"Patched {poll_file} for Linux 4.14 poll compatibility")

import subprocess

# Chain Linux 4.14 file_wrapper compatibility patch
file_wrapper_helper = Path(__file__).with_name("patch_ksun_414_file_wrapper.py")
if not file_wrapper_helper.is_file():
    raise SystemExit(f"file_wrapper helper not found: {file_wrapper_helper}")
subprocess.run([sys.executable, str(file_wrapper_helper), str(kernel_root)], check=True)

# Chain Linux 4.14 seccomp cache compatibility patch.
seccomp_cache_helper = Path(__file__).with_name("patch_ksun_414_seccomp_cache.py")
if not seccomp_cache_helper.is_file():
    raise SystemExit(f"seccomp_cache helper not found: {seccomp_cache_helper}")
subprocess.run([sys.executable, str(seccomp_cache_helper), str(kernel_root)], check=True)

# Chain the pinned KernelSU-Next legacy SELinux policy implementation for 4.14.
sepolicy_helper = Path(__file__).with_name("patch_ksun_414_sepolicy.py")
if not sepolicy_helper.is_file():
    raise SystemExit(f"sepolicy helper not found: {sepolicy_helper}")
subprocess.run([sys.executable, str(sepolicy_helper), str(kernel_root)], check=True)
