# WS73 board configuration export

The native Linux driver consumes two raw runtime configuration files alongside
the three SDK boot images: `bsle_custom.bin` (140 bytes) and `pm_config.bin`
(4 bytes). These runtime files do not have the boot images' ASCII SHA-256 header.
No firmware or calibration blob is distributed in this repository.

Export an explicit SDK efuse configuration candidate from the workspace:

```sh
python3 sparklink/tools/ws73-board-config.py \
  --ini ws73_SDK/build/config/ws73_cfg_default.ini \
  --output-dir .dev/ws73-sdk-default-candidate \
  --board ws73-sdk-default-unverified \
  --usb-link-check 0
```

Choose a fresh output directory each time. The script preserves existing files
and rejects missing inputs, duplicate selected fields, out-of-range values and
flash mode. Flash mode requires per-device flash calibration and addresses that
the efuse exporter cannot reconstruct. All active reference/frequency values
come from the selected INI; only unused flash fields, addresses and ABI padding
remain zero in efuse mode. The tool strictly parses `DEVICE_BT` and `HOST_PLAT`;
unrelated Wi-Fi fragments in the SDK INI do not become board parameters.

`--usb-link-check` is required because the SDK derives that bit from compile-time
configuration rather than an INI field. Select it from the matching deployment
configuration. The example's zero selects a candidate for subsequent validation.
The board label records provenance; it does not certify board compatibility.

The JSON manifest records the full input hash, exporter hash, selected numeric
values, explicit link-check setting and exact output hashes. A successful export
establishes the byte layout. It does not establish USB, BSLE, DLI or RF operation.
The SDK default's GPIO and power settings still require verification against the
actual dongles; do not treat them as a physical acceptance result.

With the current Linux worktree, pack the candidate into the isolated lab:

```sh
cd linux
python3 tools/testing/selftests/sparklink/ws73-lab.py pack \
  --runtime-config-dir ../.dev/ws73-sdk-default-candidate
```

The lab records the actual runtime files in its firmware manifest. The driver
logs the loaded hashes and fails that instance if either file is absent or has
the wrong size. The existing `WS73_BOOT_GATE` checks USB runtime binding only;
inspect the subsequent BSLE/DLI stages and errors separately. The first North
Star still requires real dual-device discovery through ordinary-user `slctl`.

Run the exporter tests without hardware:

```sh
cd sparklink
python3 -m unittest discover -s tools/tests -v
```

These tests use synthetic INI inputs and a complete hand-written byte oracle,
including packed channel-block halfwords, PM bit positions and inactive fields.
Protocol layout sources are the supplied SDK's `customize_bsle_ext.h`,
`customize_bsle.c`, `customize.h` and `customize_wifi.c`; implementation code was
written independently.
