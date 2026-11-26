# darnit-amber

Scientific reproducibility for darnit. Two parts:

- **`darnit-amber`**, a command that records an experiment's run, verifies it, and reruns it.
- **The `amber` framework** for `darnit audit`, whose checks read a repository, including the runs it records.

## Record, verify, rerun

Requirements: git, [Witness](https://github.com/in-toto/witness) on `PATH`, and Docker or Podman to rerun in an image.

```
darnit-amber run --results results/ -- python train.py     # in the experiment's clean git checkout
darnit-amber verify                                        # check the newest run
darnit-amber rerun                                         # verify it, run it again, compare
```

**`run`** _(Linux support only for now)_

- Clones the checkout. Only changed committed to git are used for further steps.
- Runs the experiment under `witness` in order to record:
    - the command used to run this experiments along with its exit code.
    - the files that are opened by the experiment. This allows us to understand what implicit dependecies
      are required in order to run a given experiment.
    - each opened file get mapped to a _source_ which stores information about how to recreate this file in
      a fresh environment.
- Signs `amber.intoto.json` and `witness.intoto.json` in-toto attestations that record this information. These
  along with the results and outputs get bundled into the `--output` directory.

**`verify`** checks a `run` to ensure the following:

- its id is the digest of its statement;
- the statement and Witness's attestation agree on the command, exit code and results;
- the copies of the results are those results;
- the lock matches the trace;
- the signature is valid.

It prints each check and exits 0 only when all pass.

**`rerun`**

1. Verifies the run (it never runs anything from a run that does not verify).
2. With `--host-environment` (the command runs on this machine, as you), asks first. `--yes` skips the question.
3. Rebuilds the run's environment as a Docker image from the lock and runs the same command at the same commit inside it. `--host-environment` runs it on this machine instead.
4. Compares the results.
5. Opens a shell where it ran (`--no-shell` to skip). `--sign` also records the rerun as a signed run of its own.

| grade                      | meaning                                                  |
| -------------------------- | -------------------------------------------------------- |
| `drift`                    | a result changed                                         |
| `same_environment`         | results identical, same packages and files               |
| `different_environment`    | results identical, environment differs (see result.json) |
| `environment_not_compared` | results identical, no lock to compare                    |

It exits 2 on drift.

## Signing

By default a run is signed **keyless** with [Sigstore](https://www.sigstore.dev/). After the experiment finishes you sign in (a browser link, or automatically in CI), and the run is signed as that identity and logged in Rekor. There is no key to keep.

`--key key.pem` signs with your own key instead. The bundle then carries `key.pub`, and every signature gets an RFC 3161 timestamp (`--no-timestamp` turns that off, and verify then fails).

A run names its signer, and by default `verify` and `rerun` check it against that name. This shows the run was not changed, not who made it, so pass the signer you expect:

```
darnit-amber verify --identity researcher@uni.edu --issuer https://github.com/login/oauth
darnit-amber verify --pubkey researcher.pub
```

This is an optional step, without either `--identity --issuer` or `--pubkey`, the claimed identity is printed to the terminal.

## The bundle

`.amber/` in the experiment's checkout by default (`--output` picks another place):

```
.amber/
  key.pub                       only for runs signed with --key
  runs/<id>/
    amber.sigstore.json         the statement, signed keyless (or amber.intoto.json, signed with a key)
    witness.intoto.json         Witness's attestation
    outputs/<path>              copies of the results
  reruns/<time>-<id>/           each rerun: its own runs/, the checkout it ran in, Dockerfile,
                                commands.log, result.json
```

The run id is the sha256 of the statement. The statement holds the repository and commit, the command, exit code, result digests, the environment lock, the signer, and the digest of Witness's attestation.

Witness records the command's stdout, so an experiment that prints a secret stores it.

## Audit: `darnit audit -f amber`

The audit only reads the repository; it never runs the experiment.

| control  | level | checks                                                               |
| -------- | ----- | -------------------------------------------------------------------- |
| RE-01.01 | 1     | dependencies are pinned (lock files)                                 |
| RE-01.02 | 1     | a build environment is declared (Dockerfile, Nix flake, ...)         |
| RE-02.01 | 2     | no network fetches while building, from a verified run's trace or CI |
| RE-02.02 | 2     | provenance exists                                                    |
| RE-02.03 | 2     | a run of the audited commit is in `.amber/`, verifies, and exited 0  |
| RE-03.01 | 3     | the build is bit-for-bit reproducible                                |

RE-02.03 passes only for a signer the operator trusts. The `repro_run_verified` step's settings list them: `trusted_keys` (key fingerprints) or `trusted_identities` (`[identity, issuer]` pairs). Without one, the control is inconclusive. A run of the commit that does not verify fails it.

The other checks read text and files: a signal can show a requirement is unmet, but a mention cannot show it is met. So they can conclude only FAIL. A PASS from them is evidence, and the control goes on to review.
