# Xiaomi Miio – CA4 fix

A drop-in replacement for Home Assistant's built-in **Xiaomi Home**
(`xiaomi_miio`) integration that stops entities from briefly turning
`unavailable` because of single failed polls. It was written for the
Smartmi/Zhimi evaporative humidifier `zhimi.humidifier.ca4`, but the update
tolerance applies to every device that uses the integration's default status
polling.

It is the unmodified core integration from Home Assistant **2026.10.4** plus a
small, isolated set of changes. Because it keeps the `xiaomi_miio` domain,
Home Assistant uses your existing configuration: config entries, tokens,
devices, entity IDs, automations and dashboards stay as they are.

## The problem

With the core integration, CA4 humidifiers go `unavailable` for about 15
seconds every now and then and come back on the next poll. The log shows

```
Error fetching zhimi.humidifier.ca4 data: Unable to discover the device <host>
```

and occasionally parser errors from python-miio such as
`construct.core.ConstError: ... parsing expected 8497 but parsed ...` or
`TypeError: byte indices must be integers or slices, not str`.

One failed poll is enough to mark the device unavailable, and it stays that
way until the next poll one update interval (15 s) later. Longer timeouts do
not help: the device either sends a malformed UDP reply or does not answer one
handshake, and answers normally a moment later.

## What this version changes

1. **Malformed replies to read commands are retried once.** A `ConstError` or
   the specific `TypeError` above in reply to a `get_*` command (such as
   `get_properties`) is retried once. A second malformed reply is raised as a
   normal `DeviceException`. Write commands (`set_properties`, on/off, target
   humidity, mode, …) are **never** sent twice.
2. **A failed device discovery is retried once** after 0.25 s before the poll
   counts as failed.
3. **Grace period.** If the poll still fails, the last known state is kept for
   two consecutive failed polls. The third consecutive failure marks the
   device unavailable as usual, and the first successful poll resets the
   counter. There is no grace before the first successful update after
   start-up.

Only communication errors are tolerated (`DeviceException`, timeouts,
`OSError`, `ConstError`); programming errors still surface normally.

The changes live in `miio_patch.py` and `resilience.py`. The core code itself
is only changed where they are wired in, which keeps updates to new Home
Assistant releases simple.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/quenthal/xiaomi-miio-ca4fix` with category
   **Integration**.
2. Find **Xiaomi Miio (CA4 fix)** and select **Download**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/xiaomi_miio` from the latest release to
`/config/custom_components/xiaomi_miio` and restart Home Assistant.

### After installation

Do **not** remove or re-add the Xiaomi Home integration in the UI. Existing
config entries are picked up automatically after the restart. The log shows

```
We found a custom integration xiaomi_miio which has not been tested by Home Assistant
```

which confirms that this version is in use.

If you previously copied a modified `xiaomi_miio` into `custom_components` by
hand, move that folder away (for example rename it to `xiaomi_miio.old`)
before installing, so no stale files are left behind.

## Logging

| Level   | Message                                                                 | Meaning                                                    |
| ------- | ----------------------------------------------------------------------- | ---------------------------------------------------------- |
| DEBUG   | `Temporary Xiaomi Miio discovery failure for … retrying status once`    | Discovery retry; usually succeeds and is not visible       |
| DEBUG   | `Malformed miIO response for read command … retrying once`              | Malformed reply retried                                    |
| WARNING | `Xiaomi Miio update failure 1/3 (2/3) for …; keeping last known state` | Poll and retry failed, last known state kept               |
| ERROR   | `Xiaomi Miio update failure 3/3 for …; device will be marked unavailable` | Real outage, device is unavailable                       |
| INFO    | `Xiaomi Miio device … recovered after … failed update cycle(s)`         | Device answers again                                       |

The logger is `custom_components.xiaomi_miio`, not
`homeassistant.components.xiaomi_miio`; update any `logger:` filters
accordingly. To see the retries temporarily:

```yaml
action: logger.set_level
data:
  custom_components.xiaomi_miio: debug
```

Debug logs contain device state and the first characters of the device token,
so do not post them publicly without redacting.

## Limitations

- **Stale state during the grace period.** If a command succeeds but the next
  poll fails, the UI can show the previous value for up to two polls.
  Automations reacting to the humidifier's sensors may see a value up to about
  45 seconds old during an outage.
- **Not updated with Home Assistant.** A custom integration shadows the
  built-in one, so Home Assistant updates do not update it. A new release of
  this repository is needed for each Home Assistant release that changes the
  integration. `hacs.json` declares the minimum Home Assistant version.
- **Process-wide patch.** The protocol patch changes python-miio's
  `MiIOProtocol.send` for the whole Home Assistant process. It is only
  installed for the python-miio version it was written for (0.5.12).
- This does not fix the root cause on the device or the network. It only
  keeps short glitches from showing up as unavailable entities.

## Uninstall / rollback

Remove (or rename) `/config/custom_components/xiaomi_miio` — or uninstall it in
HACS — and restart Home Assistant. The built-in integration takes over the same
config entries. Do not delete the integration in the UI, as that removes the
config entries.

## Versioning

Versions are `<Home Assistant base version>-ca4fix.<n>`, for example
`2026.10.4-ca4fix.1`. The git history keeps the unmodified upstream import in
its own commit, followed by the changes in this project.

## Development

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt ruff
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

## License

Apache License 2.0, like Home Assistant Core. This project contains code from
Home Assistant Core; see [NOTICE](NOTICE) for attribution and a list of the
changed files.
