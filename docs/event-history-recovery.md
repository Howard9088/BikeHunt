# Cold-cache event history recovery

## Observed incident

The publication cache path changed the GitHub Actions cache version. On the resulting cold run, the former 10 MiB download limit rejected the 18,764,258-byte public snapshot. Recovery fell back to repository event 85 without restoring per-offer baselines. Previously known offers then generated `new_offer` events again.

Verified prior publication: `a115bbd5acbec05e45e4733a9495b757263a3485`, generated `2026-10-14T23:42:34.595089+00:00`, event cursor **1257**, snapshot SHA-256 `0c8a47b6f75aeb0e249e41e7897345444c7bc3eeb49791c10c8b76a895e4b5e6`.

Affected publication: `203aae7b9e3a696c3ae3b45550508e78f6512779`, generated `2026-10-14T23:58:52.734856+00:00`, event cursor **1162**, snapshot SHA-256 `5272e121846dfcd67652f48ce936f466cd6dcdea136cceb2e72f4d205759c06e`.

## Bounded correction

`data/event_cursor_checkpoint.json` reserves the actual already-published cursor 1257. It contains no synthetic event or observation.

`data/event_history_recovery.json` retains both original 100-event windows, the prior 1,190 offer IDs and exact URL/price/currency/stock baseline, and both publication identities and hashes. All 100 affected visible `new_offer` rows exactly match the prior offer state; no uncertain change is suppressed.

Original replay rows remain in SQLite. A separate `suppressed_events` table excludes only proven replay keys from public history and outgoing notifications. Additional warm-cache rows outside the visible 100-row backup are eligible only when they are `new_offer` rows inside the affected publication’s ID/time window and exactly match the prior offer ID, URL, currency, decimal amount and stock. Unknown, changed and out-of-window rows remain intact. It records the reason and both source hashes. Unknown rows and real changes are preserved. Suppression is reversible without reconstructing deleted data.

Missing original historical events are inserted in original ID order above the largest local, published or checkpoint cursor. Their exact event keys, prices, stock, product metadata and `observed_at` remain unchanged. `original_id`, `recovery_snapshot_sha256` and `recovered_history=true` explain the remapping. Existing matching event keys are not inserted twice. A SQLite completion identity is exported in the manifest-bound snapshot and imported on future cold starts, so historical rows that naturally age out of the latest-100 window are never resurrected. Recovered history remains visible, but is excluded from notification queues and frontend unread/toast counts.

For the affected cold-cache public window, the result is 100 preserved replay rows plus 100 restored rows, IDs 1258–1357. The visible history again contains 76 price changes, 20 genuine new offers and 4 inventory changes. The next genuine event is greater than 1357. Warmer/newer caches can legitimately produce a higher cursor.

## Future recovery

The recovery script verifies manifest-bound schema 1 snapshots and schema 2 snapshots/status, with fixed same-site HTTPS paths and bounded reads (32 MiB catalog, 8 MiB status, 64 KiB manifest). A configured public site's unavailable or mismatched release stops collection rather than silently reverting to an old seed.

Per-offer baselines are restored before collecting, using actual public observation times and collection state. Newer local offers/status and outstanding source cooldowns survive. Restoration itself invokes no capture and never stamps recovery time onto data. Re-collecting all 1,190 unchanged recovered offers produces zero events.

The maximum reserved SQLite sequence is exposed even when the retained event rows have lower IDs. Public build fallback cannot reintroduce suppressed rows from an old JSON seed.
