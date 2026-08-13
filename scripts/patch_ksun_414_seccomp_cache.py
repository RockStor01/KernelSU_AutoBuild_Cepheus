#!/usr/bin/env python3
from pathlib import Path
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = kernel_root / "KernelSU-Next/kernel/infra/seccomp_cache.c"
if not p.is_file():
    raise SystemExit(f"seccomp_cache.c not found: {p}")

s = p.read_text()

# Linux 4.14 does not define the newer seccomp architecture cache-size
# constants used by KernelSU-Next.  On arm64 the native syscall count is
# already exported as __NR_syscalls via asm/unistd.h; compat has
# __NR_compat_syscalls when CONFIG_COMPAT is enabled.
if "KSU_LEGACY_414_SECCOMP_CACHE_COMPAT" not in s:
    marker = '#include <linux/seccomp.h>\n'
    if marker not in s:
        raise SystemExit("Expected linux/seccomp.h include not found")
    compat = (
        '#include <asm/unistd.h>\n'
        '#define KSU_LEGACY_414_SECCOMP_CACHE_COMPAT 1\n'
        '#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)\n'
        '#ifndef SECCOMP_ARCH_NATIVE_NR\n'
        '#define SECCOMP_ARCH_NATIVE_NR __NR_syscalls\n'
        '#endif\n'
        '#if defined(CONFIG_COMPAT) && !defined(SECCOMP_ARCH_COMPAT_NR)\n'
        '#define SECCOMP_ARCH_COMPAT 1\n'
        '#define SECCOMP_ARCH_COMPAT_NR __NR_compat_syscalls\n'
        '#endif\n'
        '#endif\n'
    )
    s = s.replace(marker, marker + compat, 1)

checks = (
    "KSU_LEGACY_414_SECCOMP_CACHE_COMPAT",
    "#define SECCOMP_ARCH_NATIVE_NR __NR_syscalls",
    "#define SECCOMP_ARCH_COMPAT_NR __NR_compat_syscalls",
)
missing = [x for x in checks if x not in s]
if missing:
    raise SystemExit("seccomp_cache compatibility patch failed: " + ", ".join(missing))

p.write_text(s)
print(f"Patched {p}")
