---
name: check-data-quality
description: Run quality checks on QSO candidates — redshift plausibility, photometry, cross-source consistency
argument-hint: <project> [source_ids]
---

Checks all candidate sources (or a specific subset) for:
- Redshift plausibility (1.5 <= z <= 5.0) — rejects implausible values
- Photometry completeness (flags faint_u if u_mag > 23.5)
- Cross-source z consistency — flags z_conflict if two nearby sources disagree by > 0.05

Writes flags back to the DB. Sources with `z_implausible` are set to `rejected`.

## Usage

```bash
# Check all candidates
python src/check_data_quality.py --project <project>

# Check specific sources
python src/check_data_quality.py --project <project> --source-ids 1,5,12
```

## Output (JSON to stdout)

```json
{"checked": 45, "flagged": 8, "rejected": 2}
```

## Notes

- `z_conflict` sources are flagged but NOT rejected — the sample-coordinator should
  spawn a literature-agent to resolve conflicts before making a final decision
- Cross-match uses 5 arcsec radius for same-object detection
