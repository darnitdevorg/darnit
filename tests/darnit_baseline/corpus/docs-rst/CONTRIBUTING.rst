Contributing to tinyq
=====================

Tests
-----

Tests are run by CI on every pull request and on every push to main.
To run them locally before you open a pull request, install the
development requirements and use pytest::

    pip install -r requirements-dev.txt
    pytest

Dependencies
------------

We manage dependencies with pip-tools; each library is pinned in
requirements.txt and updated weekly by a scheduled job. New dependencies
are selected only when they are actively maintained and use an
OSI-approved license, and a maintainer must approve each addition in
review. Packages are obtained from PyPI with hash checking, and the
pinned requirements files track every direct and transitive dependency.
