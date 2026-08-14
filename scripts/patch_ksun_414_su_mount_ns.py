#!/usr/bin/env python3
from pathlib import Path
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")

# -----------------------------------------------------------------------------
# su_mount_ns.c compatibility for Linux 4.14
# -----------------------------------------------------------------------------
p = kernel_root / "KernelSU-Next/kernel/infra/su_mount_ns.c"
if not p.is_file():
    raise SystemExit(f"su_mount_ns.c not found: {p}")

s = p.read_text()

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

# -----------------------------------------------------------------------------
# pkg_observer.c fsnotify compatibility for Linux 4.14
# -----------------------------------------------------------------------------
p = kernel_root / "KernelSU-Next/kernel/manager/pkg_observer.c"
if not p.is_file():
    raise SystemExit(f"pkg_observer.c not found: {p}")

s = p.read_text()

if "KSU_LEGACY_414_PKG_OBSERVER_COMPAT" not in s:
    marker = '#define MASK_SYSTEM (FS_CREATE | FS_MOVE | FS_EVENT_ON_CHILD)\n'
    if marker not in s:
        raise SystemExit("pkg_observer MASK_SYSTEM marker not found")
    s = s.replace(marker, marker + '#define KSU_LEGACY_414_PKG_OBSERVER_COMPAT 1\n', 1)

    old_cb = '''static int ksu_handle_inode_event(struct fsnotify_mark *mark, u32 mask,
                                  struct inode *inode, struct inode *dir,
                                  const struct qstr *file_name, u32 cookie)
{
    if (!file_name)
        return 0;
    if (mask & FS_ISDIR)
        return 0;
    if (file_name->len == 13 && !memcmp(file_name->name, "packages.list", 13)) {
        pr_info("packages.list detected: %d\\n", mask);
        track_throne(false);
    }
    return 0;
}

static const struct fsnotify_ops ksu_ops = {
\t.handle_inode_event = ksu_handle_inode_event,
};
'''

    new_cb = '''#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)
static int ksu_handle_event(struct fsnotify_group *group,
                            struct inode *inode,
                            struct fsnotify_mark *inode_mark,
                            struct fsnotify_mark *vfsmount_mark,
                            u32 mask, const void *data, int data_type,
                            const unsigned char *file_name, u32 cookie,
                            struct fsnotify_iter_info *iter_info)
{
    if (!file_name)
        return 0;
    if (mask & FS_ISDIR)
        return 0;
    if (!strcmp((const char *)file_name, "packages.list")) {
        pr_info("packages.list detected: %d\\n", mask);
        track_throne(false);
    }
    return 0;
}

static const struct fsnotify_ops ksu_ops = {
    .handle_event = ksu_handle_event,
};
#else
static int ksu_handle_inode_event(struct fsnotify_mark *mark, u32 mask,
                                  struct inode *inode, struct inode *dir,
                                  const struct qstr *file_name, u32 cookie)
{
    if (!file_name)
        return 0;
    if (mask & FS_ISDIR)
        return 0;
    if (file_name->len == 13 && !memcmp(file_name->name, "packages.list", 13)) {
        pr_info("packages.list detected: %d\\n", mask);
        track_throne(false);
    }
    return 0;
}

static const struct fsnotify_ops ksu_ops = {
    .handle_inode_event = ksu_handle_inode_event,
};
#endif
'''

    if old_cb not in s:
        raise SystemExit("Expected pkg_observer callback block not found")
    s = s.replace(old_cb, new_cb, 1)

old_add = '''\tif (fsnotify_add_inode_mark(m, inode, 0)) {
\t\tfsnotify_put_mark(m);
\t\treturn -EINVAL;
\t}
'''
new_add = '''#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)
\tif (fsnotify_add_mark(m, inode, NULL, 0)) {
#else
\tif (fsnotify_add_inode_mark(m, inode, 0)) {
#endif
\t\tfsnotify_put_mark(m);
\t\treturn -EINVAL;
\t}
'''
if 'fsnotify_add_inode_mark(m, inode, 0)' in s and 'fsnotify_add_mark(m, inode, NULL, 0)' not in s:
    if old_add not in s:
        raise SystemExit("Expected pkg_observer fsnotify_add_inode_mark block not found")
    s = s.replace(old_add, new_add, 1)

checks = (
    "KSU_LEGACY_414_PKG_OBSERVER_COMPAT",
    "static int ksu_handle_event(struct fsnotify_group *group",
    ".handle_event = ksu_handle_event",
    "fsnotify_add_mark(m, inode, NULL, 0)",
    ".handle_inode_event = ksu_handle_inode_event",
)
missing = [x for x in checks if x not in s]
if missing:
    raise SystemExit("pkg_observer compatibility patch failed: " + ", ".join(missing))

p.write_text(s)
print(f"Patched {p}")

# -----------------------------------------------------------------------------
# allowlist.c task_work / task lifetime / fallthrough compatibility for 4.14
# -----------------------------------------------------------------------------
p = kernel_root / "KernelSU-Next/kernel/policy/allowlist.c"
if not p.is_file():
    raise SystemExit(f"allowlist.c not found: {p}")

s = p.read_text()

# Needed for LINUX_VERSION_CODE and for put_task_struct() on this 4.14 tree.
if '#include <linux/version.h>' not in s:
    marker = '#include <linux/task_work.h>\n'
    if marker not in s:
        raise SystemExit("allowlist task_work include marker not found")
    s = s.replace(
        marker,
        marker + '#include <linux/version.h>\n'
                 '#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)\n'
                 '#include <linux/sched/task.h>\n'
                 '#endif\n',
        1,
    )

# Linux 4.14 task_work_add() takes bool notify; TWA_RESUME is a newer enum.
if 'KSU_LEGACY_414_ALLOWLIST_COMPAT' not in s:
    marker = '#define FILE_MAGIC 0x7f4b5355 // \' KSU\', u32\n'
    if marker not in s:
        raise SystemExit("allowlist FILE_MAGIC marker not found")
    compat = (
        '#define KSU_LEGACY_414_ALLOWLIST_COMPAT 1\n'
        '#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)\n'
        '#define KSU_TASK_WORK_NOTIFY true\n'
        '#else\n'
        '#define KSU_TASK_WORK_NOTIFY TWA_RESUME\n'
        '#endif\n'
    )
    s = s.replace(marker, compat + marker, 1)

if 'task_work_add(tsk, cb, TWA_RESUME)' in s:
    s = s.replace('task_work_add(tsk, cb, TWA_RESUME)',
                  'task_work_add(tsk, cb, KSU_TASK_WORK_NOTIFY)', 1)

# The fallthrough macro is not available in this 4.14 source.  A recognized
# comment is enough here because case 2 intentionally continues into case 3.
if '\n        fallthrough;\n    case 3:' in s:
    s = s.replace('\n        fallthrough;\n    case 3:',
                  '\n#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)\n'
                  '        /* fall through */\n'
                  '#else\n'
                  '        fallthrough;\n'
                  '#endif\n'
                  '    case 3:', 1)

checks = (
    "KSU_LEGACY_414_ALLOWLIST_COMPAT",
    "#include <linux/sched/task.h>",
    "#define KSU_TASK_WORK_NOTIFY true",
    "task_work_add(tsk, cb, KSU_TASK_WORK_NOTIFY)",
    "/* fall through */",
)
missing = [x for x in checks if x not in s]
if missing:
    raise SystemExit("allowlist compatibility patch failed: " + ", ".join(missing))

p.write_text(s)
print(f"Patched {p}")
