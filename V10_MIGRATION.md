# V10 repository migration

This overlay contains ordinary files only. Apply every listed file at its exact repository-relative path in one commit. It intentionally does not contain generated root reports/site/docs, so a partial source upload cannot silently mix public report versions. The first successful existing Actions workflow produces and commits all three output trees atomically at Git commit level.

## Unchanged security and data boundaries

- Same repository, existing two workflow names, schedules, concurrency group and contents-write permission only.
- No new Pages API deployment, id-token, credential, account, branch-protection or repository-permission change.
- Original root data CSVs and V9 ledger are untouched. Isolated v10_system/data holds byte-identical pinned input copies.
- The V10 seed release preserves the previously generated V10 seal; it is not reset during installation.
- Old root compatibility Python entrypoints route to V10. Existing v9 source is retained for history but no workflow executes it.

## Rollout and verification

1. Confirm the current main commit and reconcile unrelated changes before committing the overlay.
2. Confirm old V9 jobs cannot remain pending and overwrite later output; both workflow replacements must land together, under their unchanged common concurrency group.
3. After the source commit, observe its V10 workflow. It restores the seed CURRENT pointer, runs tests, reads HKJC, computes and verifies one complete release, then prepares output mirrors with rollback on failure.
4. The workflow commits CURRENT, immutable release directories and reports/site/docs together. It never stages the original root data directory. It does not publish any changed file on failure. A non-fast-forward push fails safely; rerun against current main instead of force-pushing.
5. Check the resulting commit, workflow status and exact original670822 URL. Compare the actual HTML marksix-report-version to the release ID in reports/version.json. Also compare the latest period/date and generated timestamp.
6. Distinguish runtime fallback from original Sites deployment. No claim of original-host redeployment is justified by a GitHub commit alone.

The compatibility projection uses schema marksix_official_v9 only for the old loader, explicitly labels engine_schema marksix_v10, preserves canonical_v10_analysis.json, and uses equivalent HKT timestamps to satisfy the loader's lexical time comparison. Its own checksum manifest covers projection bytes; its release ID identifies the canonical V10 analysis.

## Commands and failure behavior

`python v10_runner.py update` only prepares local Git worktree outputs; it never commits or pushes. `verify` validates native and compatibility copies together. A failure after any individual output-directory replacement restores all previous directories, the local current link and tracked CURRENT text. Public atomicity comes from the single successful Git commit.

The existing Pages-from-docs configuration must already be available. The workflow does not create or change it. No new hosting route is introduced.
