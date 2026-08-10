# Audit Summary

I ran the darnit audit against this repository. Here's what I found:

**Summary**: 51 PASS, 5 FAIL, 7 WARN, 2 ERROR out of 66 controls.

## Failed Controls

- **OSPS-BR-06.01**: FAIL -- no signed releases found
- **OSPS-VM-04.01**: FAIL -- SECURITY.md not present

## Warned Controls

- **OSPS-GV-03.01**: WARN -- some ambiguity in the CODEOWNERS file
- **OSPS-DO-04.01**: WARN -- documentation could be improved

## Suggestions

Consider adding a SECURITY.md file to address OSPS-VM-04.01.
