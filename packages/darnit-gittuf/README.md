# darnit-gittuf

Gittuf policy checks plugin for darnit.

Provides three controls:
- GT-01.01 GittufInitialized — checks .gittuf/policy.json and .gittuf/root.json exist
- GT-01.02 GittufPolicyValid — runs gittuf verify-ref HEAD
- GT-02.01 CommitsSigned — checks last 5 commits are cryptographically signed