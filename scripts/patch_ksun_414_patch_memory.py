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
sulog_event = kernel_root / "KernelSU-Next/kernel/sulog/event.c"
if not sulog_event.is_file():
    raise SystemExit(f"sulog event.c not found: {sulog_event}")
event_src = sulog_event.read_text()
if '#include <linux/minmax.h>\n' in event_src:
    event_src = event_src.replace('#include <linux/minmax.h>\n', '#include <linux/kernel.h>\n', 1)
if '#include <linux/minmax.h>' in event_src:
    raise SystemExit("sulog minmax compatibility patch failed")
if '#include <linux/kernel.h>' not in event_src:
    raise SystemExit("sulog legacy kernel.h include missing")
sulog_event.write_text(event_src)
print(f"Patched {sulog_event} for Linux 4.14 min/max compatibility")

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
