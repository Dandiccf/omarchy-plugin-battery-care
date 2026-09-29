# Code and usability review — Battery Care 0.2.1

Reviewed 2026-09-29 on Omarchy 4.0.4-1 / ThinkPad X1 Gen 14.

The review covered every product source file: the Python UPower adapter, state and recovery logic, systemd integration, QML panel and controls, JavaScript presentation model, manifest, installation/removal, and user documentation. Confirmed issues below were corrected. This is a review of the current implementation, not a claim of exhaustive hardware compatibility.

## Findings and fixes

| Area | Finding | Resolution |
|---|---|---|
| Removal | Releasing management enabled protection even after explicit Off. An absent battery's pending recovery could be discarded. | Preserve Off, restore protection/full modes, and refuse release if a temporary-session battery is absent or restoration fails. |
| Recovery durability | Atomic rename alone did not guarantee the recovery record reached disk before lifting the cap. | Flush file contents and directory metadata before changing charging. A failed save prevents the hardware action. |
| State validation | Malformed individual records could break recovery; corrupt state also prevented ordinary monitoring. | Validate record shape/mode/boot ID. Keep monitoring available with an explicit state error and disable mutations; do not silently erase the file. |
| Authorization | Background recovery requested interactive authorization. | Only explicit user actions allow an authorization prompt. Background failures remain retryable. |
| Contention | A status/action process could wait indefinitely for another helper's lock. | Bound lock acquisition to five seconds and return an actionable error. |
| Limit accuracy | Disabled UPower protection with an independently limited hardware cap was not flagged; start thresholds were not compared. | Check end thresholds in both modes and start thresholds when enabled. |
| Telemetry | Missing values appeared as zero; an empty plugged-in battery could be labeled as holding at its limit. | Preserve unknown values and correct the empty/holding distinction. |
| Status/action race | A status request issued before a charge action could overwrite its result. | Tag requests with an action generation and discard outdated results. |
| Errors | A routine poll could erase an action failure. Process failures could leave stale controls enabled. | Separate action, status, recovery, and profile errors. Persist action errors until dismissed/retried; disable controls when readings are invalid. |
| Guard visibility | A stopped timer was not visible in the panel. | Check managed-state guard availability and explain how to restart it by enabling protection. |
| Mouse/keyboard | Repeated hover handlers were prone to the previous stuck-highlight bug; keyboard navigation included disabled actions. | Shared production CareButton component; skip unavailable controls and keep selection distinct from hover. |
| Multi-battery access | Battery selection had no keyboard path and the selector could overflow. | Add `[` / `]` selection, wrap the selector, and disable selection while a charge action is pending. |
| Layout | A height-capped popup clipped content without scrolling. Narrow layouts retained wide rows. | Scroll the panel, reveal keyboard-selected controls, and stack narrow charge/profile/stat sections. |
| Installation | A failed enable could leave a newly created development link. | Remove only a newly created link on failure; preserve existing links and unrelated data. Add a guarded local uninstall script. |

## Verification actually performed

- **59 Python tests**: recovery transitions, reboot/unplug simulations, Off persistence, unsupported/replaced/absent batteries, failed authorization, removal behavior, corrupt state, telemetry validation, durable-save failure, inactive guard, installer failure/rollback, and 25 file-safety regression cases added in 0.2.1.
- **32 JavaScript assertions**: status labels, active/preset distinction, action selection, unknown values, empty state, keyboard navigation, and temporary full-charge presentation.
- **Two isolated QML test flows using the production components**: shared button hover/keyboard-state bindings; panel Off/full/cancel command routing (including cancel while on battery), stale/invalid status, persistent errors, corrupt-state lockout, and keyboard battery selection. The panel harness uses a stateful simulated Python backend and does not write battery controls.
- Omarchy manifest validation, QML parsing, and shell script syntax checks.
- Live plugin loading, normal-width screenshot inspection, and runtime-log inspection with no plugin loading/runtime errors observed.
- Live hardware after loading the reviewed version: start threshold **75%**, end threshold **80%**, UPower enabled, no threshold mismatch, timer enabled/active, last recovery service result successful.
- Earlier in this same session: actual 80%→100% full-charge action, physical unplug restoration to 80%, explicit Off surviving a guard check, and a physical reboot with protection already enabled.

The button QML harness exercises hover signals and bindings; it is not a substitute for all pointer interactions across every theme. The panel screenshot is the normal laptop layout. Responsive layout code has been reviewed/parsed but still needs visual coverage on smaller displays, vertical bars, and other themes.

## Remaining limitations and release checks

1. **Recovery polls every 15 seconds.** A brief unplug/replug entirely between checks may be missed. Cancel full charge or unplug for at least one interval; event-driven AC handling remains a future improvement.
2. **Recovery is a user-session service.** After reboot it resumes at login, not before login or in firmware. A physical reboot during an active full-charge session remains untested; automated boot-ID recovery passes. The completed physical reboot started in protection mode.
3. **Hardware coverage is one ThinkPad.** Multiple-battery, unsupported-device, and several failure cases are simulated. Other UPower versions, firmware limits, and laptops need live testing before a broad compatibility claim.
4. **Limits come from UPower.** The plugin does not offer arbitrary custom percentages or forcibly drain a battery that is already above the limit. Other charge managers can still change the same hardware; disagreements are reported.
5. **Removal must release management first.** Omarchy does not run plugin uninstall hooks. Use the local uninstall script or run `battery.py release` before removing a git-installed copy.

## Marketplace file-safety follow-up — 0.2.1

The marketplace maintainer identified two gaps in the original review: the status lock used a truncating, symlink-following open, and fixed unit paths could overwrite foreign files. The local uninstaller also removed unit filenames without verifying their contents.

- Directory access now uses pinned directory descriptors and refuses symlink traversal. The state directory is verified as user-owned and made private; unsafe shared-writable paths are rejected.
- The lock opens without truncation using `O_NOFOLLOW`, followed by regular-file, owner, hard-link-count, and permission checks. State reads/writes use the same file checks and directory descriptors; saves retain file/directory fsync.
- Both unit destinations are checked before installation. Existing files must be user-owned, safe regular files with exact generated contents. New files are flushed and published with a no-clobber hard link from a unique temporary file, so a competing destination is never overwritten. Exact 0.2.0 units at the same helper path are compatible without rewriting them.
- Release checks the units before touching charging or recovery state, restores pending sessions, and removes only verified units. The local uninstaller delegates cleanup to release and no longer blindly deletes fixed unit paths.
- Added regression cases for symlinks (including dangling links and ancestors), hard links, FIFOs, foreign owners, shared-writable directories, nontruncating locks, foreign/modified units, concurrent destination creation, legacy compatibility, and safe removal. These use temporary directories and simulated UPower/systemctl; they do not change hardware settings.
- Re-ran all 59 Python tests, 32 JavaScript assertions, both QML flows, manifest validation, and shell syntax checks. Live status still reports enabled 75–80% protection with no mismatch or guard warning; the existing units pass ownership/content checks and the recovery service exits successfully.

The plugin is submitted as [marketplace issue #9273](https://github.com/omacom/omarchy-plugin-marketplace/issues/9273). Marketplace approval is separate from these local checks.
