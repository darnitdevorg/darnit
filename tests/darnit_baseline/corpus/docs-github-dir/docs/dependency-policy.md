# Dependency policy

New dependencies are selected only when they are actively maintained and use an
OSI-approved license; a maintainer approves each addition in review. Packages
are obtained from PyPI with hash checking. pip-tools pins every direct and
transitive dependency in requirements.txt, which tracks them, and a scheduled
job updates the pins weekly.
