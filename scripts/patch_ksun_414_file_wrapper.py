#!/usr/bin/env python3
from pathlib import Path
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = kernel_root / "KernelSU-Next/kernel/infra/file_wrapper.c"
if not p.is_file():
    raise SystemExit(f"file_wrapper.c not found: {p}")

s = p.read_text()

marker = '#include <linux/mount.h>\n'
if 'KSU_LEGACY_414_FILE_WRAPPER_COMPAT' not in s:
    if marker not in s:
        raise SystemExit('Expected mount include not found in file_wrapper.c')
    compat = (
        '#define KSU_LEGACY_414_FILE_WRAPPER_COMPAT 1\n'
        '#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 16, 0)\n'
        '#define KSU_LEGACY_414_FILE_WRAPPER 1\n'
        '#else\n'
        '#define KSU_LEGACY_414_FILE_WRAPPER 0\n'
        '#endif\n'
    )
    s = s.replace(marker, marker + compat, 1)

s = s.replace(
    'static __poll_t ksu_wrapper_poll(struct file *fp, struct poll_table_struct *pts)\n',
    '#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 16, 0)\n'
    'static unsigned int ksu_wrapper_poll(struct file *fp, struct poll_table_struct *pts)\n'
    '#else\n'
    'static __poll_t ksu_wrapper_poll(struct file *fp, struct poll_table_struct *pts)\n'
    '#endif\n',
    1
)

start = s.find('#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)\nstatic int ksu_wrapper_iopoll')
if start >= 0:
    end = s.find('#endif\n', start)
    if end >= 0:
        end += len('#endif\n')
        block = s[start:end]
        s = s[:start] + '#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 16, 0)\n' + block + '#endif\n' + s[end:]

s = s.replace(
    '    p->ops.iopoll = fp->f_op->iopoll ? ksu_wrapper_iopoll : NULL;\n',
    '#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 16, 0)\n'
    '    p->ops.iopoll = fp->f_op->iopoll ? ksu_wrapper_iopoll : NULL;\n'
    '#endif\n',
    1
)

s = s.replace(
    '#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 12, 0)\n'
    '    p->ops.fop_flags = fp->f_op->fop_flags;\n'
    '#else\n'
    '    p->ops.mmap_supported_flags = fp->f_op->mmap_supported_flags;\n'
    '#endif\n',
    '#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 12, 0)\n'
    '    p->ops.fop_flags = fp->f_op->fop_flags;\n'
    '#elif LINUX_VERSION_CODE >= KERNEL_VERSION(4, 16, 0)\n'
    '    p->ops.mmap_supported_flags = fp->f_op->mmap_supported_flags;\n'
    '#endif\n',
    1
)

for lhs in (
    '    p->ops.remap_file_range =\n        fp->f_op->remap_file_range ? ksu_wrapper_remap_file_range : NULL;\n',
    '    p->ops.fadvise = fp->f_op->fadvise ? ksu_wrapper_fadvise : NULL;\n',
):
    if lhs in s:
        s = s.replace(lhs, '#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 16, 0)\n' + lhs + '#endif\n', 1)

# Hide wrapper implementations for APIs not present in this 4.14 tree.
for func in ('ksu_wrapper_remap_file_range', 'ksu_wrapper_fadvise'):
    idx = s.find('static ', s.find(func) - 80)
    if idx >= 0:
        next_marker = s.find('\nstatic ', s.find('{', idx))
        if next_marker > idx:
            block = s[idx:next_marker+1]
            if '#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 16, 0)' not in block:
                s = s[:idx] + '#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 16, 0)\n' + block + '#endif\n' + s[next_marker+1:]

# For 4.14, use the native anon_inode_getfile() instead of the newer secure anon-inode implementation.
needle = '#elif LINUX_VERSION_CODE >= KERNEL_VERSION(5, 16, 0)\n#define ksu_anon_inode_create_getfile_compat anon_inode_getfile_secure\n#else\n'
if needle in s:
    s = s.replace(
        needle,
        '#elif LINUX_VERSION_CODE >= KERNEL_VERSION(5, 16, 0)\n'
        '#define ksu_anon_inode_create_getfile_compat anon_inode_getfile_secure\n'
        '#elif LINUX_VERSION_CODE < KERNEL_VERSION(4, 16, 0)\n'
        'static struct file *ksu_anon_inode_create_getfile_compat(\n'
        '    const char *name, const struct file_operations *fops, void *priv, int flags,\n'
        '    const struct inode *context_inode)\n'
        '{\n'
        '    return anon_inode_getfile(name, fops, priv, flags);\n'
        '}\n'
        '#else\n',
        1
    )

s = s.replace(
    '    struct inode_security_struct *wrapper_sec = selinux_inode(wrapper_inode);\n',
    '#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 16, 0)\n'
    '    struct inode_security_struct *wrapper_sec = wrapper_inode->i_security;\n'
    '#else\n'
    '    struct inode_security_struct *wrapper_sec = selinux_inode(wrapper_inode);\n'
    '#endif\n',
    1
)

# Linux 4.14 keeps anon_inode_mnt private inside fs/anon_inodes.c.  Our 4.14
# path already uses anon_inode_getfile() directly, so the KSU init routine must
# not try to borrow or access that internal mount pointer.
old_init = '''void __init ksu_file_wrapper_init(void)
{
#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 16, 0)
    static const struct file_operations tmp = { .owner = THIS_MODULE };
    struct file *dummy = anon_inode_getfile("dummy", &tmp, NULL, 0);
    if (IS_ERR(dummy)) {
        pr_err(
            "file_wrapper: initialize anon_inode_mnt failed, can't get file: %ld\\n",
            PTR_ERR(dummy));
        return;
    }
    anon_inode_mnt = dummy->f_path.mnt;
    if (unlikely(!anon_inode_mnt)) {
        pr_err("file_wrapper: initialize anon_inode_mnt failed, got NULL\\n");
    }
    fput(dummy);
#endif
}
'''
new_init = '''void __init ksu_file_wrapper_init(void)
{
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 16, 0)
    /* 4.14 uses anon_inode_getfile() directly; anon_inode_mnt is private. */
    return;
#elif LINUX_VERSION_CODE < KERNEL_VERSION(5, 16, 0)
    static const struct file_operations tmp = { .owner = THIS_MODULE };
    struct file *dummy = anon_inode_getfile("dummy", &tmp, NULL, 0);
    if (IS_ERR(dummy)) {
        pr_err(
            "file_wrapper: initialize anon_inode_mnt failed, can't get file: %ld\\n",
            PTR_ERR(dummy));
        return;
    }
    anon_inode_mnt = dummy->f_path.mnt;
    if (unlikely(!anon_inode_mnt)) {
        pr_err("file_wrapper: initialize anon_inode_mnt failed, got NULL\\n");
    }
    fput(dummy);
#endif
}
'''
if old_init in s:
    s = s.replace(old_init, new_init, 1)
elif '4.14 uses anon_inode_getfile() directly; anon_inode_mnt is private.' not in s:
    raise SystemExit('Expected ksu_file_wrapper_init block not found')

checks = (
    'KSU_LEGACY_414_FILE_WRAPPER_COMPAT',
    'static unsigned int ksu_wrapper_poll',
    'return anon_inode_getfile(name, fops, priv, flags);',
    'wrapper_inode->i_security',
    '4.14 uses anon_inode_getfile() directly; anon_inode_mnt is private.',
)
missing = [x for x in checks if x not in s]
if missing:
    raise SystemExit('file_wrapper compatibility patch failed: ' + ', '.join(missing))

p.write_text(s)
print(f'Patched {p}')

# Chain Linux 4.14 event_queue compatibility patch.
import subprocess
event_queue_helper = Path(__file__).with_name("patch_ksun_414_event_queue.py")
if not event_queue_helper.is_file():
    raise SystemExit(f"event_queue helper not found: {event_queue_helper}")
subprocess.run([sys.executable, str(event_queue_helper), str(kernel_root)], check=True)
