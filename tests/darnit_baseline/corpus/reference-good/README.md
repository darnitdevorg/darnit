# widget

widget is a command-line tool that prints ASCII widgets.

## Install

    pip install widget

## Usage

    widget draw --width 10    # print a widget 10 characters wide
    widget list               # list the available widget shapes
    widget --help             # show every command and option

## Building from source

Building requires Python 3.11 or newer and the build dependencies listed in
`pyproject.toml` (hatchling, and click at runtime):

    python -m pip install build
    python -m build

## Running the tests

The test suite runs on every pull request in CI (`.github/workflows/ci.yml`)
and must pass before a change is merged. To run it locally:

    python -m pip install -e ".[test]"
    python -m pytest

## Reporting bugs

Report defects in the GitHub issue tracker. Include the widget version, the
command you ran, what you expected, and what happened instead.

## Support

The latest minor release receives bug fixes and security updates. A release
stops receiving security updates when the next minor release has been out
for six months.
