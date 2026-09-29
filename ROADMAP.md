# Release notes and future improvements

## Reviewed in 0.2.0

- Preserve explicit Off during removal; refuse to abandon absent batteries with pending full-charge recovery.
- Flush the recovery record before changing charging, validate saved records, and bound lock waits.
- Detect both disabled-but-limited hardware and start-threshold mismatches; show missing readings as unknown.
- Keep action errors visible, discard stale pre-action polls, disable controls when status is invalid, and report a stopped guard.
- Share button focus behavior, skip disabled keyboard actions, support keyboard battery selection, and scroll/stack constrained panels.
- Add installer failure cleanup, a local uninstall script, and production QML regression harnesses using simulated batteries.
- Full findings and verification boundaries: [REVIEW.md](REVIEW.md).

## Fixed in 0.1.2

- An active temporary session now offers **Cancel full charge** instead of repeating the start action. Mouse and keyboard use the same action; cancellation stays available after unplugging while automatic recovery is pending.
- Full-charge highlighting depends on both the temporary-session state and confirmed disabled protection.

## Fixed in 0.1.1

- The protection button is now a true On/Off toggle. Explicit Off cancels temporary recovery and is respected by the guard.
- Mouse hover no longer latches the keyboard navigation highlight, including the full-charge and power-profile buttons.
- Live checks confirmed the 100% hardware cap remains after a guard interval in Off mode, and the panel keyboard action restores the 80% cap.
- 15 backend tests and 17 presentation assertions pass, including Off across unplug/reboot and failed-toggle rollback.

## Included in 0.1.0

The default widget conflated configured presets with active charge limits. Battery Care reads `ChargeThresholdEnabled`, displays actual sysfs end thresholds separately, and uses UPower charging states rather than guessing a threshold from low charging current or a long charge-time estimate.

The replacement adds reversible charge controls, persistent temporary-session recovery, battery health and cycles, explicit power source, keyboard operation, unsupported-hardware handling, and per-battery selection.

## Before publishing

- [x] Live full-charge/unplug test on ThinkPad X1 Gen 14: cap changed to 100%, then automatically returned to 80% after unplugging (2026-09-29).
- [x] Physical reboot/login with protection enabled: timer restarted successfully and the 75–80% limits remained active (2026-09-29).
- [ ] Test reboot/login recovery during an active temporary full-charge session; the completed reboot began in protection mode.
- Test on another supported laptop and a machine without threshold support.
- Test low-resolution and vertical bar layouts; verify other Omarchy themes.
- Decide on final author identity/repository URL, then submit to the plugin directory after review.
- Review minimum supported Omarchy/UPower versions and document package installation on those versions.

## Useful next features

1. Event-driven restoration on AC removal, while keeping periodic retry and durable recovery. This would catch brief unplug/replug events between polls.
2. Explicit “stop managing” UI with service cleanup; Omarchy currently does not run uninstall hooks.
3. Optional full-charge completion notification and an estimated time to the configured cap, only where reliable telemetry exists.
4. Short power-use history with clear sampling and retention controls.
5. Custom charge presets only through a supported, authorized backend; avoid raw root-level sysfs scripts.
6. Upstream the enabled-state indicator fix so the standard widget improves even for people who do not install Battery Care.

No performance-profile changes should silently alter charge protection. No preset should be labeled active without checking its actual enabled state. Battery diagnostics should distinguish estimates from hardware settings.
