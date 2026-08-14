/*
 * KernelSU-Next 4.14 兼容性补丁
 * 解决 crDroid 16.0 4.14.355 内核链接阶段 undefined reference 错误
 *
 * 1. ksu_handle_*: crDroid 内核预置了原版 KernelSU 手动钩子，
 *    KernelSU-Next v3.3.0 改用 syscall_hook 机制，这些钩子作为 no-op 即可。
 * 2. path_mount: 5.x 引入，4.14 用 do_mount + set_fs 实现
 * 3. __arm64_sys_setns: 4.17+ arm64 wrapper，4.14 包装 sys_setns
 * 4. seccomp_filter_release: 较新内核引入，4.14 转发到 put_seccomp_filter
 */
#include <linux/version.h>

#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)

#include <linux/fs.h>
#include <linux/namei.h>
#include <linux/mount.h>
#include <linux/seccomp.h>
#include <linux/sched.h>
#include <linux/uaccess.h>
#include <linux/dcache.h>
#include <linux/ptrace.h>
#include <linux/gfp.h>
#include <linux/errno.h>
#include <linux/filename.h>

/* ============================================================
 *  原版 KernelSU 手动钩子 (no-op stubs)
 *  KernelSU-Next 自有 syscall_hook_manager 接管实际钩子逻辑
 * ============================================================ */

int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
			 int *mode, int *flags)
{
	return 0;
}

int ksu_handle_vfs_read(struct file **file_ptr, char __user **buf_ptr,
			size_t *count_ptr, loff_t **pos)
{
	return 0;
}

int ksu_handle_stat(int *dfd, const char __user **filename_user)
{
	return 0;
}

int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
			void *argv, void *envp, int *flags)
{
	return 0;
}

/* ============================================================
 *  4.14 缺失的内核函数兼容实现
 * ============================================================ */

/* path_mount: Linux 5.x 引入，4.14 无此函数 */
extern long do_mount(const char *dev_name, const char __user *dir_name,
		     const char *type_page, unsigned long flags,
		     void *data_page);

int path_mount(const char *dev_name, struct path *path,
	       const char *type_page, unsigned long flags, void *data_page)
{
	char *page;
	char *dir;
	mm_segment_t old_fs;
	long ret;

	page = (char *)__get_free_page(GFP_KERNEL);
	if (!page)
		return -ENOMEM;

	dir = d_path(path, page, PAGE_SIZE);
	if (IS_ERR(dir)) {
		free_page((unsigned long)page);
		return PTR_ERR(dir);
	}

	old_fs = get_fs();
	set_fs(KERNEL_DS);
	ret = do_mount(dev_name, dir, type_page, flags, data_page);
	set_fs(old_fs);

	free_page((unsigned long)page);
	return (int)ret;
}

/* __arm64_sys_setns: arm64 4.17+ syscall wrapper 命名 */
asmlinkage long sys_setns(int fd, int nstype);

long __arm64_sys_setns(const struct pt_regs *regs)
{
	return sys_setns((int)regs->regs[0], (int)regs->regs[1]);
}

/* seccomp_filter_release: 较新内核引入，4.14 用 put_seccomp_filter */
extern void put_seccomp_filter(struct task_struct *tsk);

void seccomp_filter_release(struct task_struct *tsk)
{
	if (tsk)
		put_seccomp_filter(tsk);
}

#endif /* LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0) */
