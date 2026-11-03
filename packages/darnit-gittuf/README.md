# darnit-gittuf

Gittuf policy checks plugin for darnit.

Provides three controls:
- GT-01.01 GittufInitialized — checks `refs/gittuf/policy` exists and offers initial setup
- GT-01.02 GittufPolicyValid — runs gittuf verify-ref HEAD
- GT-02.01 CommitsSigned — checks last 5 commits are cryptographically signed

## Initial setup (GT-01.01)

Install `git`, `gittuf`, and `ssh-keygen` on PATH and configure your Git author
and committer identity. Have the maintainer confirm `gittuf_root_key` through
`confirm_project_data`: provide the absolute local path to an existing SSH
private key, never its contents or a `.pub` path.

Signing must work without a passphrase prompt. Use an unencrypted key or unlock
the key in `ssh-agent` before starting Darnit, with the agent available to that
process. Interactive passphrase entry is not supported by this remediation.

After approval, the registered handler runs `gittuf trust init`, `trust stage
--local-only`, and `trust apply --local-only` in the repository. It refuses setup
if any `refs/gittuf/*` already exist. It leaves HEAD, Git configuration, and
working-tree files untouched. Branch policies and additional key holders remain
maintainer decisions; nothing is pushed.

## Test coverage

The real-gittuf onboarding tests currently provide **local-only coverage**: CI
does not install gittuf, so those tests skip when the binary is absent. With
gittuf installed on PATH, run them locally from the workspace root:

```bash
uv run pytest tests/darnit_gittuf/test_onboarding.py -v
```
