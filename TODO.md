# TODO

## Architecture / Robustness

- [ ] **Coordinator resumability**: Coordinator agents should maintain a persistent log/journal
  (e.g. `projects/<name>/logs/<stage>_journal.md`) so that if they are interrupted mid-run,
  they can read back their own journal on restart and pick up where they left off rather than
  starting from scratch. The journal should record: completed sub-tasks, decisions made, sources
  already queried, and next intended action.
