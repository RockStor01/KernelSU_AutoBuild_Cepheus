#!/usr/bin/env python3
from pathlib import Path
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = kernel_root / "KernelSU-Next/kernel/selinux/selinux.c"
if not p.is_file():
    raise SystemExit(f"selinux.c not found: {p}")

s = p.read_text()

if "KSU_LEGACY_414_SELINUX_CRED_COMPAT" not in s:
    marker = '#include "ksu.h"\n'
    if marker not in s:
        raise SystemExit("selinux.c ksu.h include marker not found")
    compat = r'''

#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 8, 0)
#define KSU_LEGACY_414_SELINUX_CRED_COMPAT 1
#define ksu_selinux_cred(cred) ((struct task_security_struct *)((cred)->security))
#else
#define ksu_selinux_cred(cred) selinux_cred(cred)
#endif
'''
    s = s.replace(marker, marker + compat, 1)

s = s.replace('tsec = selinux_cred(cred);', 'tsec = ksu_selinux_cred(cred);')
s = s.replace('const struct task_security_struct *tsec = selinux_cred(cred);',
              'const struct task_security_struct *tsec = ksu_selinux_cred(cred);')

checks = (
    "KSU_LEGACY_414_SELINUX_CRED_COMPAT",
    "#define ksu_selinux_cred(cred) ((struct task_security_struct *)((cred)->security))",
    "tsec = ksu_selinux_cred(cred);",
    "const struct task_security_struct *tsec = ksu_selinux_cred(cred);",
)
missing = [x for x in checks if x not in s]
if missing:
    raise SystemExit("selinux credential compatibility patch failed: " + ", ".join(missing))

p.write_text(s)
print(f"Patched {p}")
