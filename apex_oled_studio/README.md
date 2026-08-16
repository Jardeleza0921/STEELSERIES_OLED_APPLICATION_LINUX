# Apex OLED Studio

A lightweight Linux GUI for modifying the 128×40 monochrome OLED screen on supported SteelSeries Apex keyboards.

## Current features

- Detect supported SteelSeries Apex OLED HID interfaces
- 128×40 live preview
- Type and position custom text
- Load PNG/JPG/BMP/GIF/WebP images
- Automatic resize and monochrome conversion
- Invert display
- Clear OLED
- Send directly over USB HID
- No SteelSeries GG required

## Known supported product IDs

- 1038:1610 — Apex Pro
- 1038:1612 — Apex 7
- 1038:1614 — Apex Pro TKL
- 1038:1618 — Apex 7 TKL
- 1038:161c — Apex 5
- 1038:1640 — Apex Pro Gen 3
- 1038:1644 / 1646 — Apex Pro TKL Wireless Gen 3 variants

## Linux Mint setup

Open a Terminal in this folder:

```bash
chmod +x setup.sh install-udev.sh run.sh install-desktop.sh
./setup.sh
./install-udev.sh
```

After `install-udev.sh`, unplug and reconnect the keyboard.

Then start the app:

```bash
./run.sh
```

Optional: add it to your application menu:

```bash
./install-desktop.sh
```

## Check what keyboard Linux sees

```bash
lsusb | grep -i steelseries
```

For older Apex Pro models you may see something similar to:

```text
1038:1610
```

For an Apex 7:

```text
1038:1612
```

## Troubleshooting

### No keyboard detected

1. Make sure the keyboard data cable is connected directly to the computer.
2. Run:

```bash
lsusb | grep -i steelseries
```

3. Run `./install-udev.sh`.
4. Unplug/replug the keyboard.
5. Start `./run.sh` again.

### Permission denied

Run:

```bash
./install-udev.sh
```

Then reconnect the keyboard.

### The image is reversed / shifted

This app implements the current known Apex OLED layouts for legacy and Gen 3 devices. If your exact firmware behaves differently, send the output of:

```bash
lsusb | grep -i steelseries
```

and we can add a device-specific profile.

## Project structure

```text
apex_oled_studio/
├── apex_oled_studio.py
├── requirements.txt
├── setup.sh
├── install-udev.sh
├── run.sh
├── install-desktop.sh
└── README.md
```
# STEELSERIES_OLED_APPLICATION_LINUX
