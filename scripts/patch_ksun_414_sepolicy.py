#!/usr/bin/env python3
from pathlib import Path
from urllib.request import urlopen
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
target = kernel_root / "KernelSU-Next/kernel/selinux/sepolicy.c"
if not target.is_file():
    raise SystemExit(f"sepolicy.c not found: {target}")

# KernelSU-Next legacy branch is maintained specifically for old non-GKI kernels.
# Pin the source revision so this build remains reproducible.
LEGACY_COMMIT = "a54e4fa46c6cc25bcaa055cf14d790194beffed8"
URL = f"https://raw.githubusercontent.com/KernelSU-Next/KernelSU-Next/{LEGACY_COMMIT}/kernel/selinux/sepolicy.c"

try:
    data = urlopen(URL, timeout=30).read().decode("utf-8")
except Exception as exc:
    raise SystemExit(f"failed to fetch pinned legacy sepolicy.c: {exc}")

required = (
    '#include "ss/policydb.h"',
    'static bool add_filename_trans(',
    'static bool add_typeattribute(',
    '#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 9, 0)',
)
missing = [x for x in required if x not in data]
if missing:
    raise SystemExit("legacy sepolicy validation failed: " + ", ".join(missing))

# The legacy branch also includes compat/kernel_compat.h for vendor trees that
# carry the legacy compat layer. KSUN v3.3.0 does not ship that directory, and
# this sepolicy implementation does not use anything from that header. Remove
# the stale include so the pinned legacy policy code can build standalone.
stale_include = '#include "compat/kernel_compat.h" // Add check Huawei Device\n'
data = data.replace(stale_include, "")
if 'compat/kernel_compat.h' in data:
    raise SystemExit("failed to remove unavailable legacy kernel_compat.h include")

# v3.3.0 user space / manager stays untouched; only the in-kernel SELinux
# policy implementation is replaced with the upstream KSUN legacy implementation
# that targets old policydb/flex_array layouts such as Linux 4.14.
target.write_text(data)
print(f"Patched {target} from KernelSU-Next legacy {LEGACY_COMMIT} (standalone 4.14 mode)")
