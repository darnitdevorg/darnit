# Decisions

One ADR per decision. ADRs are numbered and immutable once accepted: a decision
that turns out wrong gets a new ADR that supersedes it, never an edit in place.

`../where-decisions-live.md` says when something belongs here rather than in
the constitution, a feature spec or a design note. In short, an ADR records
reasoning and a constitution rule creates an obligation. Most decisions need
the first and not the second.

Proposals still under discussion are RFCs in `docs/rfcs/`. An accepted RFC
becomes an ADR here.

## Numbering

Files are named `NNNN-kebab-title.md` and numbered in order. A number is never
reused.

## Status values

- `proposed`: written, not yet agreed
- `accepted`: in force
- `superseded by ADR-NNNN`: replaced, with its text kept for the record

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-what-darnit-is.md) | darnit aligns a project's setup with a hygiene goal | proposed |
| [0002](0002-governance-follows-swansong.md) | Governance is a short enforced constitution, ADRs and an enforcement table | proposed |
| [0003](0003-docs-consolidation.md) | Consolidate the docs into governance, contracts, design notes and user docs | proposed |
