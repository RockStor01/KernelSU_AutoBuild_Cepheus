/*
 * KernelSU-Next 4.14 compatibility shim for symbols required by the
 * crDroid cepheus 4.14 tree at link time.
 */
#include <linux/version.h>

#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)

#include <linux/dcache.h>
#include <linux/errno.h>
#include <linux/fs.h>
#include <linux/gfp.h>
#include <linux/mount.h>
#include <linux/namei.h>
#include <linux/ptrace.h>
#include <linux/sched.h>
#include <linux/seccomp.h>
#include <linux/uaccess.h>

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

asmlinkage long sys_setns(int fd, int nstype);

long __arm64_sys_setns(const struct pt_regs *regs)
{
	return sys_setns((int)regs->regs[0], (int)regs->regs[1]);
}

extern void put_seccomp_filter(struct task_struct *tsk);

void seccomp_filter_release(struct task_struct *tsk)
{
	if (tsk)
		put_seccomp_filter(tsk);
}

#endif
