#!/usr/bin/env python3
from pathlib import Path
import sys
import subprocess

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = kernel_root / "KernelSU-Next/kernel/hook/arm64/patch_memory.c"
if not p.is_file():
    raise SystemExit(f"patch_memory.c not found: {p}")
s = p.read_text()
marker = '#include "asm-generic/fixmap.h"\n'
if "KSU_LEGACY_414_PATCH_MEMORY_COMPAT" not in s:
    if marker not in s: raise SystemExit("Expected fixmap include not found")
    s = s.replace(marker, marker + '#include <linux/version.h>\n#define KSU_LEGACY_414_PATCH_MEMORY_COMPAT 1\n#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)\n#ifndef __pte_to_phys\n#define __pte_to_phys(pte) ((phys_addr_t)pte_pfn(pte) << PAGE_SHIFT)\n#endif\n#ifndef __pmd_to_phys\n#define __pmd_to_phys(pmd) ((phys_addr_t)pmd_pfn(pmd) << PAGE_SHIFT)\n#endif\n#ifndef pmd_leaf\n#define pmd_leaf(pmd) pmd_sect(pmd)\n#endif\n#ifndef copy_to_kernel_nofault\n#define copy_to_kernel_nofault(dst, src, len) probe_kernel_write((dst), (src), (len))\n#endif\n#endif\n', 1)
s = s.replace('#define ksu_flush_icache(start, end) __flush_icache_range\n', '#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)\n#define ksu_flush_icache(start, end) flush_icache_range((start), (end))\n#else\n#define ksu_flush_icache(start, end) __flush_icache_range\n#endif\n', 1)
# The PMD mapping is now understood, but the first live write caused a
# device boot loop. Keep the address translation active and allow only the first syscall-table write (syscall 63) and skip subsequent
# writes. This isolates whether the first write or a later hook causes bootloop.
needle = '    void *map = set_fixmap_offset(FIX_TEXT_POKE0, phy);\n'
replacement = (
    '    static atomic_t ksu_414_patch_attempts = ATOMIC_INIT(0);\n'
    '    int ksu_414_patch_index = atomic_inc_return(&ksu_414_patch_attempts);\n'
    '    if (ksu_414_patch_index > 1) {\n'
    '        pr_err("KSU 4.14 single-write: skip index=%d dst=0x%lx phy=0x%lx len=%zu flags=%d\\n",\n'
    '               ksu_414_patch_index, p, phy, len, flags);\n'
    '        return -EOPNOTSUPP;\n'
    '    }\n'
    '    pr_err("KSU 4.14 single-write: allow index=%d dst=0x%lx phy=0x%lx len=%zu flags=%d\\n",\n'
    '           ksu_414_patch_index, p, phy, len, flags);\n'
    '    void *map = set_fixmap_offset(FIX_TEXT_POKE0, phy);\n'
)
if needle not in s:
    raise SystemExit('Expected fixmap write marker not found')
s = s.replace(needle, replacement, 1)
if 'KSU 4.14 single-write' not in s:
    raise SystemExit('Diagnostic no-write guard insertion failed')
p.write_text(s)

# SULog compatibility.
event = kernel_root / "KernelSU-Next/kernel/sulog/event.c"
e = event.read_text().replace('#include <linux/minmax.h>\n', '#include <linux/kernel.h>\n', 1)
if '#define ktime_get_boottime_ts64(ts)' not in e:
    marker = '#include <linux/version.h>\n'
    block = marker + '#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)\n#ifndef ktime_get_boottime_ts64\n#define ktime_get_boottime_ts64(ts) (*(ts) = ktime_to_timespec64(ktime_get_boottime()))\n#endif\n#ifndef strncpy_from_user_nofault\n#define strncpy_from_user_nofault(dst, src, count) strncpy_from_user((dst), (src), (count))\n#endif\n#endif\n'
    e = e.replace(marker, block, 1)
event.write_text(e)
for rel in ("KernelSU-Next/kernel/infra/event_queue.h","KernelSU-Next/kernel/infra/event_queue.c","KernelSU-Next/kernel/sulog/fd.c"):
    q = kernel_root / rel
    q.write_text(q.read_text().replace('__poll_t', 'unsigned int'))

# KSUN supercall/dispatch uses scheduler globals whose declarations are not
# pulled transitively on the 4.14 downstream tree. Include sched/signal.h,
# which declares tasklist_lock/init_task and task session/pgrp helpers.
dispatch = kernel_root / "KernelSU-Next/kernel/supercall/dispatch.c"
if not dispatch.is_file():
    raise SystemExit(f"dispatch.c not found: {dispatch}")
d = dispatch.read_text()
if '"__arm64_sys_ni_syscall"' not in d:
    raise SystemExit('Expected arm64 ni_syscall symbol name not found')
d = d.replace('"__arm64_sys_ni_syscall"', '"sys_ni_syscall"', 1)
if '"sys_ni_syscall"' not in d:
    raise SystemExit('Linux 4.14 ni_syscall symbol rename failed')
if '#include <linux/sched/signal.h>' not in d:
    lines = d.splitlines(True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith('#include '): insert_at = i + 1
    lines.insert(insert_at, '#include <linux/sched/signal.h>\n')
    d = ''.join(lines)
dispatch.write_text(d)
if '#include <linux/sched/signal.h>' not in d:
    raise SystemExit('dispatch scheduler compatibility patch failed')
print(f"Patched {dispatch} for Linux 4.14 scheduler declarations")

# Linux 4.14 task_work_add() takes a bool notify/resume argument; the newer
# KernelSU-Next source passes TWA_RESUME, which is not defined on 4.14.
supercall = kernel_root / "KernelSU-Next/kernel/supercall/supercall.c"
if not supercall.is_file():
    raise SystemExit(f"supercall.c not found: {supercall}")
sc = supercall.read_text()
old = 'task_work_add(current, &tw->cb, TWA_RESUME)'
new = 'task_work_add(current, &tw->cb, true)'
if old in sc:
    sc = sc.replace(old, new, 1)
if 'TWA_RESUME' in sc:
    raise SystemExit('Linux 4.14 task_work compatibility patch failed')
supercall.write_text(sc)
print(f"Patched {supercall} for Linux 4.14 task_work API")

# Chain existing compatibility helpers.
for helper_name in ("patch_ksun_414_file_wrapper.py", "patch_ksun_414_seccomp_cache.py", "patch_ksun_414_sepolicy.py"):
    helper = Path(__file__).with_name(helper_name)
    if not helper.is_file(): raise SystemExit(f"helper not found: {helper}")
    subprocess.run([sys.executable, str(helper), str(kernel_root)], check=True)
