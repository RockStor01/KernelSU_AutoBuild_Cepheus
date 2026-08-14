#!/usr/bin/env python3
from pathlib import Path
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = kernel_root / "KernelSU-Next/kernel/feature/selinux_hide.c"
if not p.is_file():
    raise SystemExit(f"selinux_hide.c not found: {p}")

s = p.read_text()
marker = "KSU_LEGACY_414_SELINUX_HIDE_STUB"

if marker not in s:
    legacy = r'''#include <linux/version.h>
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)
#define KSU_LEGACY_414_SELINUX_HIDE_STUB 1
#include "selinux_hide.h"

/*
 * Linux 4.14 uses selinux_state.ss and has no struct selinux_policy snapshot
 * layout.  The SELinux-hide feature depends on the newer replaceable policy
 * object, so keep KernelSU core functional and expose no-op hooks here rather
 * than fabricating incompatible SELinux internals.
 */
void ksu_selinux_hide_init(void) {}
void ksu_selinux_hide_exit(void) {}
void ksu_selinux_hide_drop_backup_if_unused(void) {}
void ksu_selinux_hide_handle_second_stage(void) {}
void ksu_selinux_hide_handle_post_fs_data(void) {}

#else
'''
    s = legacy + s + '\n#endif /* Linux >= 4.17 SELinux-hide implementation */\n'

checks = (
    "KSU_LEGACY_414_SELINUX_HIDE_STUB",
    "void ksu_selinux_hide_init(void) {}",
    "void ksu_selinux_hide_drop_backup_if_unused(void) {}",
    "#else",
)
missing = [x for x in checks if x not in s]
if missing:
    raise SystemExit("SELinux-hide 4.14 stub patch failed: " + ", ".join(missing))

p.write_text(s)
print(f"Patched {p}")
