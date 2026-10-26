# Code and usability review — Battery Care 0.3.1

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

1. **Recovery polls every 15 seconds as a fallback.** Since 0.5.1 the panel also restores protection on UPower’s unplug event. Only with the widget disabled or the shell stopped can a brief unplug/replug between checks be missed.
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

## Screen & lock — 0.3.0

The new editor preserves current timeouts until Apply, keeps drafts isolated from polling, provides separate/shared source settings, and uses Omarchy's idle service instead of launching a second locker. Config writes reuse the verified-file helpers, preserve unrelated keys, check stale idle revisions and concurrent file edits, and back up each explicit save. There is no claim of a transaction with noncooperating external writers: a detected conflict is rejected, and users should avoid changing the same settings simultaneously through different tools.

The controller observes UPower source changes and a one-second activity monitor. Its startup grace period prevents treating an uninitialized activity monitor as permission to switch. It additionally checks Omarchy's idle-cycle and locked-screen state before changing timeout intervals. While idle, preferences can be saved but the active pair is retained; pending switches apply after activity resumes. This intentionally favors preserving the current lock deadline over changing an away session immediately.

Verification includes 23 new Python cases (82 total), 32 existing JavaScript assertions, the existing battery/button QML flows, a production settings-form flow, and a production IdleController flow using the real Python config backend with temporary files and simulated UPower/activity. These cover defaults, separate/shared selection, custom seconds, Apply/Cancel, draft retention, blocked idle/lock transitions, deferred switching on return, external/conflicting edits, symlink rejection, missing IPC, and backup failure. A live +1-second timeout change was acknowledged by Omarchy, then the original 150/300-second pair and prior idle configuration were restored and acknowledged. Normal-width UI and keyboard inspection was performed on the ThinkPad. Screen & lock now opens as a compact subview, hiding the battery overview; the popup caps its height to 620 logical pixels or the available screen space and scrolls overflow. A fifth QML flow checks that timeout menus choose upward/downward placement after layout.

Physical charger switching for idle profiles and a full unattended lock countdown still need live coverage; source/cycle transitions are simulated. No new timeout preferences are imposed merely by installing the feature. Release 0.3.0 builds on the previously published 0.2.1 file-safety fixes.


## Final release review — 0.3.0

Reviewed the complete feature diff, existing file/charge helpers, installation/removal, UI focus/layout, documentation, and validation harnesses. Fixed the following release findings:

- Idle IPC used the charge-state lock, so a slow shell response could obstruct charging actions. Idle configuration now uses a separate verified lock.
- Automatic switching could act on stale activity evidence after waiting for a lock or IPC. Requests now carry a timestamp, expire after one second, and recheck the live idle/lock state before selecting new intervals. A stale request remains pending until fresh activity.
- Controls allowed new edits during a save; a successful response could discard those edits. The form and Back/Cancel are disabled while saving; forced popup closure still cleans up its draft.
- A recovered status failure left an obsolete error visible. Successful reads now clear read failures while retaining failed-action errors until an explicit retry/reload.
- Existing zero/immediate timeouts could be displayed but rejected when preserving them through Apply. The backend now accepts that Omarchy value and the UI labels it Immediately, never disabled.
- Opening settings before their first response could focus an invisible control. The loading view now keeps an Escape-capable focus target.

Release validation: 82 Python tests, 32 JavaScript assertions, five production-QML flows, manifest validation, QML parsing, shell syntax checks, and a clean diff check. The new QML regressions exercise in-flight save protection and transient-vs-action error handling. These checks do not replace the remaining physical charger/lock-countdown coverage noted above.


## Patch review and marketplace follow-up — 0.3.1

The plugged-in display now uses a plug icon when connected without charging, retains the charging icon during active charging, and says “Plugged in · charge paused” during protection hold. Charge thresholds, recovery, and power-source detection are unchanged. Reviewed paused, charging, discharging, full, unknown, mismatch, and unsupported presentation paths. The user confirmed the updated display after a shell restart; a plugin rescan alone had retained imported JavaScript.

The maintainer confirmed the earlier lock/unit fixes but identified the local installer's predictable backup destination as an additional blocker. `backup_config.py` now reuses the verified directory/file helpers: descriptor-based no-follow reads, owner/type/permission/link-count checks, a random destination, private flushed temporary contents, and no-clobber hard-link publication. Existing destination collisions are refused, never replaced or followed. A missing configuration needs no backup; an unsafe source or backup failure aborts before widget enable and cleans up only a newly created development link.

Validation: 88 Python tests, 39 JavaScript assertions, five QML flows, manifest validation, shell syntax, and diff checks passed. Six new installer tests cover repeated backups, permissions, existing file/symlink/dangling-symlink/hard-link/directory/FIFO collisions, unsafe source/directory rejection, missing config, and failure cleanup. The timeout-menu harness initially failed because the compositor resized its window; it now places its bottom selector relative to the actual window height, and all five flows passed on rerun. No production dropdown change was needed. Previously documented hardware/idle coverage limits remain applicable.

## 0.4.0 — Omarchy 4 compatibility and translations

Added 13 complete catalogs (English, German, Spanish, French, Portuguese, Italian, Polish, Russian, Arabic, Hindi, Japanese, Korean, Simplified Chinese), native 4.5 language switching, and an older-shell system-locale fallback. The native-only component is loaded dynamically so missing I18n/Translations types do not prevent older shells from loading the plugin. Catalog names are validated from POSIX locales; regional catalogs fall back to the base language and English. Technical diagnostics remain intact when no translation is available. Number formatting uses the native service or Qt locale. Arabic layout mirroring follows the selected language.

The bar detects the separate label property at runtime, retaining the original combined icon/percentage on old shells and using separate fields on 4.5. No battery, charge recovery, installer, or idle backend behavior was changed.

Validation includes catalog coverage/placeholder checks, POSIX locale precedence/normalization/path rejection, model regressions, all Python cases, and six production-QML flows on both the installed 4.5 shell and the official v4.0.0 and v4.0.4 shell sources. The legacy fixture lacks I18n and Translations and checks German selected by de_AT.UTF-8, base-language fallback, localized numbers, and the old bar API. Current Qt introduces a Color name collision in the old upstream UI; a namespace-only transformation in a disposable fixture qualifies Commons.Color so strict runtime checks can run. An unmodified-source diagnostic run also passed all behavioral assertions, with those upstream color warnings. This is not a full old OS/Qt/Quickshell installation test. Native-speaker review of new translations and exhaustive visual layout review in every language remain open quality work.

## Energy use and charger warnings — 0.5.0

Added and reviewed 2026-10-26 on the ThinkPad X1 Gen 14 (Intel `xe` graphics).

- **Per-app energy impact** reads systemd cgroup `cpu.stat` and DRM `fdinfo` counters without privileges and stores nothing. Each DRM client is counted once. Launcher scopes are named after the program they run. Watt estimates appear only after 5 minutes of uninterrupted battery readings and are labeled as estimates.
- **Live incident that motivated the charger warning:** with a weak or intermittent USB-C connection, firmware reported `Charging` and 0 W while stored energy fell by about 9 W. The panel previously showed “Charging · protection on, 0.0 W”. Net power is now measured from stored energy over at least 30 seconds. A plugged-in battery losing more than 1 W is flagged in the panel and by a critical desktop notification.
- Verified against sysfs while charging: the energy delta measured +33.6 W against firmware `power_now` of 34.5–35.9 W, and percentage, thresholds, health, cycles, and guard state matched. A charger showing 51 W output corresponds to about 36–39 W into the battery, plus system load and conversion losses. The panel labels this rate **Into battery**.
- Tests: new Python sampler tests (`tests/test_energy.py`), Node tests for impact, watts, measured flow, drain detection, and time to the limit, plus a QML panel check of energy sampling and error handling.
- Not yet observed live: the drain warning and notification firing (covered by tests using the −9 W readings from the incident), and watt estimates after 5 minutes on battery.
