# Nespresso for Home Assistant

Local Bluetooth control and monitoring for supported Nespresso machines in Home Assistant.

This custom integration is prepared for Home Assistant 2026.8.3 and requires Home Assistant 2026.8.0 or newer. It supports Bluetooth discovery, direct pairing, reuse of an existing authentication token, translated sensor states, brewing actions, and the capsule counter.

> [!WARNING]
> Repeated Bluetooth pairing can permanently exhaust the machine's pairing-key storage. Testing indicates that failure can occur after roughly 25 new pairings; recovery then requires a JTAG programmer and manually erasing flash sectors. Reuse an existing authentication token whenever possible and avoid unnecessary pairing attempts or factory resets.

## Installation with HACS

1. Open HACS in Home Assistant.
2. Open the menu in the top-right corner and choose **Custom repositories**.
3. Add `https://github.com/michelnet/ha_nespresso_integration` as an **Integration** repository.
4. Find **Nespresso**, choose **Download**, and restart Home Assistant.
5. Go to **Settings > Devices & services > Add integration**, search for **Nespresso**, and follow the setup flow.

The machine must be within Bluetooth range of a connectable Home Assistant Bluetooth adapter or proxy. You can either pair a factory-reset machine or supply a known authentication token.

### Manual installation

Copy `custom_components/nespresso` into the `custom_components` directory of your Home Assistant configuration, restart Home Assistant, and add the integration from **Settings > Devices & services**.

## Actions

The integration provides `nespresso.coffee` and `nespresso.caps`. Use the device picker in Home Assistant's automation or script editor whenever possible.

`device_id` remains optional for backward compatibility when exactly one Nespresso machine is configured. When multiple machines are configured, it is required so the action has an unambiguous target.

### Brew a predefined drink

Selector values are stable lowercase identifiers:

```yaml
action: nespresso.coffee
data:
  device_id: YOUR_NESPRESSO_DEVICE_ID
  brew_type: lungo
  brew_temp: medium
```

Available drink values are `ristretto`, `espresso`, `lungo`, `americano`, and `hot_water`. Available temperature values are `low`, `medium`, and `high`. Support for a drink or temperature depends on the machine model.

### Brew a custom recipe

Provide both `coffee_ml` and `water_ml`. Supplying only one custom volume is rejected.

```yaml
action: nespresso.coffee
data:
  device_id: YOUR_NESPRESSO_DEVICE_ID
  brew_temp: high
  coffee_ml: 60
  water_ml: 40
```

### Set the capsule counter

```yaml
action: nespresso.caps
data:
  device_id: YOUR_NESPRESSO_DEVICE_ID
  caps: 80
```

The displayed counter is updated immediately after the machine accepts the command and is confirmed again during the next device poll.

## State normalization in 0.2.0

Machine states are now exposed as stable lowercase `snake_case` values, while Home Assistant translates their labels in the user interface. For example, the former display value `Heat Up` is now the automation-safe state `heat_up` and is shown as **Heating up**, **Aufheizen**, or another localized label.

Update automations and templates that compare old title-cased values. Always compare against the raw lowercase value, such as `ready`, `brewing`, `not_empty`, or `level_2`, rather than a translated label.

## Troubleshooting

### The machine only brews once

The lid or slider must be cycled between brew operations.

### Pairing fails

Confirm that the machine is in pairing mode and close enough to a connectable Bluetooth adapter. If pairing also fails with `bluetoothctl`, investigate the host Bluetooth adapter and driver. Avoid repeated pairing attempts because of the pairing-key storage warning above.

### The integration is configured but no entities appear

The authentication token may not have been installed correctly. Remove the integration entry, verify the token or reset the machine once, and configure it again. Do not repeatedly pair the machine.

## Credits

This project is derived from the GPL-3.0-licensed [Nespresso BLE integration by tikismoke](https://github.com/tikismoke/home-assistant-nespressoble) and the successor implementation by [bulldog5046](https://github.com/bulldog5046/ha_nespresso_integration). It has been substantially modified since the original fork, including a major rewrite in August 2026. Additional reverse-engineering notes are available in [`reverse_engineering/README.md`](reverse_engineering/README.md).

This integration is an independent community project and is not affiliated with or endorsed by Nespresso.

## License

This project is distributed under the [GNU General Public License version 3](LICENSE).
