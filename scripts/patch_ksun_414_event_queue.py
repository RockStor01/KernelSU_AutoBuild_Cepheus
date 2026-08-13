#!/usr/bin/env python3
from pathlib import Path
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
h = kernel_root / "KernelSU-Next/kernel/infra/event_queue.h"
c = kernel_root / "KernelSU-Next/kernel/infra/event_queue.c"

for p in (h, c):
    if not p.is_file():
        raise SystemExit(f"event_queue source not found: {p}")

hs = h.read_text()
cs = c.read_text()

# Linux 4.14 does not provide __poll_t. Keep the public prototype compatible
# with the native file_operations->poll return type on pre-4.16 kernels.
old_proto = "__poll_t ksu_event_queue_poll(struct ksu_event_queue *queue, struct file *file, poll_table *wait);\n"
new_proto = (
    "#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 16, 0)\n"
    "unsigned int ksu_event_queue_poll(struct ksu_event_queue *queue, struct file *file, poll_table *wait);\n"
    "#else\n"
    "__poll_t ksu_event_queue_poll(struct ksu_event_queue *queue, struct file *file, poll_table *wait);\n"
    "#endif\n"
)

if "KSU_LEGACY_414_EVENT_QUEUE_COMPAT" not in hs:
    include_marker = "#include <linux/wait.h>\n"
    if include_marker not in hs:
        raise SystemExit("Expected wait.h include not found in event_queue.h")
    hs = hs.replace(
        include_marker,
        include_marker +
        "#include <linux/version.h>\n"
        "#define KSU_LEGACY_414_EVENT_QUEUE_COMPAT 1\n",
        1,
    )

if old_proto in hs:
    hs = hs.replace(old_proto, new_proto, 1)
elif "unsigned int ksu_event_queue_poll" not in hs:
    raise SystemExit("Expected event_queue poll prototype not found")

# Old kernels use POLL* masks; EPOLL* aliases were introduced later.
if "KSU_LEGACY_414_EVENT_QUEUE_MASK_COMPAT" not in cs:
    marker = '#include "infra/event_queue.h"\n'
    if marker not in cs:
        raise SystemExit("Expected event_queue include not found in event_queue.c")
    compat = (
        "\n#define KSU_LEGACY_414_EVENT_QUEUE_MASK_COMPAT 1\n"
        "#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 16, 0)\n"
        "#ifndef EPOLLIN\n"
        "#define EPOLLIN POLLIN\n"
        "#endif\n"
        "#ifndef EPOLLRDNORM\n"
        "#define EPOLLRDNORM POLLRDNORM\n"
        "#endif\n"
        "#ifndef EPOLLHUP\n"
        "#define EPOLLHUP POLLHUP\n"
        "#endif\n"
        "#endif\n"
    )
    cs = cs.replace(marker, marker + compat, 1)

old_def = "__poll_t ksu_event_queue_poll(struct ksu_event_queue *queue, struct file *file, poll_table *wait)\n"
new_def = (
    "#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 16, 0)\n"
    "unsigned int ksu_event_queue_poll(struct ksu_event_queue *queue, struct file *file, poll_table *wait)\n"
    "#else\n"
    "__poll_t ksu_event_queue_poll(struct ksu_event_queue *queue, struct file *file, poll_table *wait)\n"
    "#endif\n"
)
if old_def in cs:
    cs = cs.replace(old_def, new_def, 1)
elif "unsigned int ksu_event_queue_poll" not in cs:
    raise SystemExit("Expected event_queue poll definition not found")

old_local = "    __poll_t mask = 0;\n"
new_local = (
    "#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 16, 0)\n"
    "    unsigned int mask = 0;\n"
    "#else\n"
    "    __poll_t mask = 0;\n"
    "#endif\n"
)
if old_local in cs:
    cs = cs.replace(old_local, new_local, 1)

checks_h = (
    "KSU_LEGACY_414_EVENT_QUEUE_COMPAT",
    "unsigned int ksu_event_queue_poll",
)
checks_c = (
    "KSU_LEGACY_414_EVENT_QUEUE_MASK_COMPAT",
    "#define EPOLLIN POLLIN",
    "#define EPOLLRDNORM POLLRDNORM",
    "#define EPOLLHUP POLLHUP",
    "unsigned int ksu_event_queue_poll",
    "unsigned int mask = 0",
)
missing = [x for x in checks_h if x not in hs] + [x for x in checks_c if x not in cs]
if missing:
    raise SystemExit("event_queue compatibility patch failed: " + ", ".join(missing))

h.write_text(hs)
c.write_text(cs)
print(f"Patched {h}")
print(f"Patched {c}")
