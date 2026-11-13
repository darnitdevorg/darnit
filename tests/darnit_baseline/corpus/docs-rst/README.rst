tinyq
=====

tinyq is a small job queue for Python applications. Install it with
``pip install tinyq`` and start a worker with ``tinyq worker``.

Design
------

tinyq has three components. The client library provides the ``enqueue``
call and is responsible for writing jobs to the broker. The broker is a
Redis instance that holds pending jobs. The worker process handles jobs:
it reads each job from the broker, runs it, and writes the result back.

Two actors interact with the system. An application developer uses the
client library to send jobs. An operator starts and stops workers and
can connect to the broker to inspect queues. Data flows from the client
to the broker, and from the broker through the worker back to the broker
as a result record.

Supported versions
------------------

We support the two most recent minor releases. The support scope covers
security fixes and critical bug fixes, and the support period for each
minor release is twelve months from its release date.

When a minor release reaches end of life, it no longer receives security
updates. We announce each end-of-life date in the release notes at least
three months in advance.

Verifying a release
-------------------

Every release is signed with Sigstore by our release workflow. To verify
that a release was produced by that workflow and not by someone else,
check the signature and the signer identity::

    cosign verify-blob tinyq-1.4.0.tar.gz \
      --bundle tinyq-1.4.0.tar.gz.sigstore.json \
      --certificate-identity https://github.com/corpus/tinyq/.github/workflows/release.yml@refs/tags/v1.4.0 \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com
