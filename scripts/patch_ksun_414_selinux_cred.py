#!/usr/bin/env python3
from pathlib import Path
import sys

kernel_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")

# -----------------------------------------------------------------------------
# selinux.c credential compatibility
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# rules.c policy-layout compatibility
# Linux 4.14 stores policydb/rwlock inside selinux_state.ss rather than the
# newer selinux_state.policy + policy_mutex layout.
# -----------------------------------------------------------------------------
p = kernel_root / "KernelSU-Next/kernel/selinux/rules.c"
if not p.is_file():
    raise SystemExit(f"rules.c not found: {p}")

s = p.read_text()

if "KSU_LEGACY_414_SELINUX_POLICY_COMPAT" not in s:
    marker = '#define SELINUX_POLICY_INSTEAD_SELINUX_SS\n'
    if marker not in s:
        raise SystemExit("rules.c SELinux policy marker not found")
    compat = (
        marker
        + '\n#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)\n'
          '#define KSU_LEGACY_414_SELINUX_POLICY_COMPAT 1\n'
          '#endif\n'
    )
    s = s.replace(marker, compat, 1)

old_apply_setup = '''void apply_kernelsu_rules()
{
    struct selinux_policy *pol, *old_pol = selinux_state.policy;
    struct policydb *db;

    if (!getenforce()) {
        pr_info("SELinux permissive or disabled, apply rules!\\n");
    }

    mutex_lock(&selinux_state.policy_mutex);
    backup_sepolicy =
        ksu_dup_sepolicy(rcu_dereference_protected(old_pol, lockdep_is_held(&selinux_state.policy_mutex)));
    if (IS_ERR(backup_sepolicy)) {
        pr_err("failed to create backup sepolicy: %ld\\n", PTR_ERR(backup_sepolicy));
        backup_sepolicy = NULL;
    } else {
        backup_sepolicy->sidtab = kzalloc(sizeof(*backup_sepolicy->sidtab), GFP_KERNEL);
        if (!backup_sepolicy->sidtab) {
            pr_err("failed to alloc backup sidtab\\n");
            ksu_destroy_sepolicy(backup_sepolicy);
            backup_sepolicy = NULL;
        } else {
            int ret = policydb_load_isids(&backup_sepolicy->policydb, backup_sepolicy->sidtab);
            if (ret) {
                pr_err("failed to load isids for backup sepolicy: %d!\\n", ret);
                kfree(backup_sepolicy->sidtab);
                ksu_destroy_sepolicy(backup_sepolicy);
                backup_sepolicy = NULL;
            } else {
                pr_info("backup sepolicy success! latest_granting=%d\\n", backup_sepolicy->latest_granting);
            }
        }
    }
    pol = ksu_dup_sepolicy(rcu_dereference_protected(
        old_pol, lockdep_is_held(&selinux_state.policy_mutex)));
    if (IS_ERR(pol)) {
        pr_err("failed to dup selinux_policy: %ld\\n", PTR_ERR(pol));
        goto out_unlock;
    }

    db = &pol->policydb;
'''
new_apply_setup = '''void apply_kernelsu_rules()
{
    struct policydb *db;
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)
    struct selinux_ss *ss = selinux_state.ss;
#else
    struct selinux_policy *pol, *old_pol = selinux_state.policy;
#endif

    if (!getenforce()) {
        pr_info("SELinux permissive or disabled, apply rules!\\n");
    }

#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)
    if (!ss) {
        pr_err("SELinux 4.14 state has no ss\\n");
        return;
    }
    write_lock(&ss->policy_rwlock);
    db = &ss->policydb;
#else
    mutex_lock(&selinux_state.policy_mutex);
    backup_sepolicy =
        ksu_dup_sepolicy(rcu_dereference_protected(old_pol, lockdep_is_held(&selinux_state.policy_mutex)));
    if (IS_ERR(backup_sepolicy)) {
        pr_err("failed to create backup sepolicy: %ld\\n", PTR_ERR(backup_sepolicy));
        backup_sepolicy = NULL;
    } else {
        backup_sepolicy->sidtab = kzalloc(sizeof(*backup_sepolicy->sidtab), GFP_KERNEL);
        if (!backup_sepolicy->sidtab) {
            pr_err("failed to alloc backup sidtab\\n");
            ksu_destroy_sepolicy(backup_sepolicy);
            backup_sepolicy = NULL;
        } else {
            int ret = policydb_load_isids(&backup_sepolicy->policydb, backup_sepolicy->sidtab);
            if (ret) {
                pr_err("failed to load isids for backup sepolicy: %d!\\n", ret);
                kfree(backup_sepolicy->sidtab);
                ksu_destroy_sepolicy(backup_sepolicy);
                backup_sepolicy = NULL;
            } else {
                pr_info("backup sepolicy success! latest_granting=%d\\n", backup_sepolicy->latest_granting);
            }
        }
    }
    pol = ksu_dup_sepolicy(rcu_dereference_protected(
        old_pol, lockdep_is_held(&selinux_state.policy_mutex)));
    if (IS_ERR(pol)) {
        pr_err("failed to dup selinux_policy: %ld\\n", PTR_ERR(pol));
        goto out_unlock;
    }

    db = &pol->policydb;
#endif
'''
if old_apply_setup in s:
    s = s.replace(old_apply_setup, new_apply_setup, 1)
elif "struct selinux_ss *ss = selinux_state.ss;" not in s:
    raise SystemExit("Expected apply_kernelsu_rules setup block not found")

old_apply_end = '''    rcu_assign_pointer(selinux_state.policy, pol);
    synchronize_rcu();
    ksu_destroy_sepolicy(old_pol);

    reset_avc_cache();
out_unlock:
    mutex_unlock(&selinux_state.policy_mutex);
}
'''
new_apply_end = '''#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)
    reset_avc_cache();
    write_unlock(&ss->policy_rwlock);
#else
    rcu_assign_pointer(selinux_state.policy, pol);
    synchronize_rcu();
    ksu_destroy_sepolicy(old_pol);

    reset_avc_cache();
out_unlock:
    mutex_unlock(&selinux_state.policy_mutex);
#endif
}
'''
if old_apply_end in s:
    s = s.replace(old_apply_end, new_apply_end, 1)
elif "write_unlock(&ss->policy_rwlock);" not in s:
    raise SystemExit("Expected apply_kernelsu_rules finalization block not found")

old_handle_decl = '''int handle_sepolicy(void __user *user_data, u64 data_len)
{
    struct selinux_policy *pol, *old_pol;
    struct policydb *db;
'''
new_handle_decl = '''int handle_sepolicy(void __user *user_data, u64 data_len)
{
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)
    struct selinux_ss *ss = selinux_state.ss;
#else
    struct selinux_policy *pol, *old_pol;
#endif
    struct policydb *db;
'''
if old_handle_decl in s:
    s = s.replace(old_handle_decl, new_handle_decl, 1)
elif "struct selinux_ss *ss = selinux_state.ss;" not in s[s.find('int handle_sepolicy'):]:
    raise SystemExit("Expected handle_sepolicy declaration block not found")

old_handle_setup = '''    mutex_lock(&selinux_state.policy_mutex);

    old_pol = selinux_state.policy;
    pol = ksu_dup_sepolicy(rcu_dereference_protected(
        old_pol, lockdep_is_held(&selinux_state.policy_mutex)));
    if (IS_ERR(pol)) {
        ret = PTR_ERR(pol);
        pr_err("ksu_dup_sepolicy err: %d\\n", ret);
        goto out_unlock;
    }
    db = &pol->policydb;
'''
new_handle_setup = '''#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)
    if (!ss) {
        ret = -ENODEV;
        goto out_free;
    }
    write_lock(&ss->policy_rwlock);
    db = &ss->policydb;
#else
    mutex_lock(&selinux_state.policy_mutex);

    old_pol = selinux_state.policy;
    pol = ksu_dup_sepolicy(rcu_dereference_protected(
        old_pol, lockdep_is_held(&selinux_state.policy_mutex)));
    if (IS_ERR(pol)) {
        ret = PTR_ERR(pol);
        pr_err("ksu_dup_sepolicy err: %d\\n", ret);
        goto out_unlock;
    }
    db = &pol->policydb;
#endif
'''
if old_handle_setup in s:
    s = s.replace(old_handle_setup, new_handle_setup, 1)
elif "write_lock(&ss->policy_rwlock);" not in s[s.find('int handle_sepolicy'):]:
    raise SystemExit("Expected handle_sepolicy setup block not found")

old_success = '''    rcu_assign_pointer(selinux_state.policy, pol);
    synchronize_rcu();
    ksu_destroy_sepolicy(old_pol);

    reset_avc_cache();
    ret = success_cmd_count;
    goto out_unlock;

out_drop_new_policy:
    ksu_destroy_sepolicy(pol);
out_unlock:
    mutex_unlock(&selinux_state.policy_mutex);
out_free:
    kvfree(payload);

    return ret;
}
'''
new_success = '''#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 17, 0)
    reset_avc_cache();
    ret = success_cmd_count;
    goto out_unlock;

out_drop_new_policy:
    /* 4.14 edits the live policydb under policy_rwlock. */
out_unlock:
    write_unlock(&ss->policy_rwlock);
#else
    rcu_assign_pointer(selinux_state.policy, pol);
    synchronize_rcu();
    ksu_destroy_sepolicy(old_pol);

    reset_avc_cache();
    ret = success_cmd_count;
    goto out_unlock;

out_drop_new_policy:
    ksu_destroy_sepolicy(pol);
out_unlock:
    mutex_unlock(&selinux_state.policy_mutex);
#endif
out_free:
    kvfree(payload);

    return ret;
}
'''
if old_success in s:
    s = s.replace(old_success, new_success, 1)
elif "4.14 edits the live policydb under policy_rwlock" not in s:
    raise SystemExit("Expected handle_sepolicy finalization block not found")

checks = (
    "KSU_LEGACY_414_SELINUX_POLICY_COMPAT",
    "struct selinux_ss *ss = selinux_state.ss;",
    "db = &ss->policydb;",
    "write_lock(&ss->policy_rwlock);",
    "write_unlock(&ss->policy_rwlock);",
    "4.14 edits the live policydb under policy_rwlock",
)
missing = [x for x in checks if x not in s]
if missing:
    raise SystemExit("rules.c legacy SELinux policy patch failed: " + ", ".join(missing))

p.write_text(s)
print(f"Patched {p}")

# -----------------------------------------------------------------------------
# sepolicy.c: the duplicate/replacement selinux_policy helpers rely on the
# newer struct selinux_policy layout and are not used by our 4.14 live-policy
# path. Exclude only that helper section on legacy kernels.
# -----------------------------------------------------------------------------
p = kernel_root / "KernelSU-Next/kernel/selinux/sepolicy.c"
if not p.is_file():
    raise SystemExit(f"sepolicy.c not found: {p}")

s = p.read_text()
if "KSU_LEGACY_414_SEPOLICY_DUP_GUARD" not in s:
    marker = '// ======== sepolicy ========\n\n'
    if marker not in s:
        raise SystemExit("sepolicy.c duplicate-policy section marker not found")
    s = s.replace(
        marker,
        marker
        + '#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 17, 0)\n'
          '#define KSU_LEGACY_414_SEPOLICY_DUP_GUARD 1\n',
        1,
    )
    s = s.rstrip() + '\n#endif /* >= 4.17: struct selinux_policy helpers */\n'

if "KSU_LEGACY_414_SEPOLICY_DUP_GUARD" not in s or "struct selinux_policy helpers" not in s:
    raise SystemExit("sepolicy.c legacy duplicate-policy guard failed")

p.write_text(s)
print(f"Patched {p}")
