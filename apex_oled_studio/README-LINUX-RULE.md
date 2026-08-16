# Linux Permission Rule Setup for SteelSeries Apex 7

This README explains how to set up the Linux `udev` permission rule needed by Apex OLED Studio so it can open and control the SteelSeries Apex 7 OLED without running the application with `sudo`.

Keyboard used with this setup:

```text
SteelSeries Apex 7
USB ID: 1038:1612
Expected OLED HID interface: 1
```

## 1. Create the udev rule

Open a Terminal and run:

```bash
sudo tee /etc/udev/rules.d/70-steelseries-apex7.rules >/dev/null <<'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="1038", ATTR{idProduct}=="1612", MODE="0660", GROUP="plugdev", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{idVendor}=="1038", ATTRS{idProduct}=="1612", MODE="0660", GROUP="plugdev", TAG+="uaccess"
EOF
```

This gives your normal Linux desktop user access to both the USB and `hidraw` interfaces used by the keyboard.

## 2. Add your user to the plugdev group

Run:

```bash
sudo usermod -aG plugdev "$USER"
```

Check your groups:

```bash
groups
```

If `plugdev` was newly added, log out of Linux and log back in.

## 3. Reload the udev rules

Run:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## 4. Reconnect the keyboard

Unplug the SteelSeries Apex 7 USB cable, wait a few seconds, then plug it back in.

This is important because the new rule is normally applied when the device reconnects.

## 5. Confirm Linux detects the Apex 7

Run:

```bash
lsusb | grep -i -E 'steelseries|1038'
```

You should see something similar to:

```text
Bus 001 Device 010: ID 1038:1612 SteelSeries ApS SteelSeries Apex 7
```

The important part is:

```text
1038:1612
```

## 6. Start Apex OLED Studio

Go to the app folder:

```bash
cd ~/Downloads/apex_oled_studio
```

Start it normally:

```bash
./run.sh
```

Then inside Apex OLED Studio:

1. Click **Refresh**
2. Select the Apex 7 if needed
3. Click **Test**
4. The connection should open successfully

Do not run the GUI with `sudo`.

## 7. Test the HID interfaces manually

If the application still says `open failed`, run:

```bash
cd ~/Downloads/apex_oled_studio

.venv/bin/python - <<'PY'
import hid

for i, d in enumerate(hid.enumerate(0x1038, 0x1612)):
    print("=" * 50)
    print("DEVICE:", i)
    print("Product:   ", d.get("product_string"))
    print("Interface: ", d.get("interface_number"))
    print("Path:      ", d.get("path"))

    try:
        dev = hid.device()
        dev.open_path(d["path"])
        print("OPEN:       SUCCESS")
        dev.close()
    except Exception as e:
        print("OPEN:       FAILED")
        print("ERROR:     ", e)
PY
```

The Apex 7 exposes multiple HID interfaces. Apex OLED Studio expects the OLED interface to be:

```text
Interface: 1
```

## 8. Check the installed rule

Run:

```bash
cat /etc/udev/rules.d/70-steelseries-apex7.rules
```

It should contain:

```text
SUBSYSTEM=="usb", ATTR{idVendor}=="1038", ATTR{idProduct}=="1612", MODE="0660", GROUP="plugdev", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{idVendor}=="1038", ATTRS{idProduct}=="1612", MODE="0660", GROUP="plugdev", TAG+="uaccess"
```

## Why both rules are included

Apex OLED Studio uses Python HIDAPI.

On Linux, HIDAPI can access hardware through different backends.

The first rule:

```text
SUBSYSTEM=="usb"
```

allows access to the USB device.

The second rule:

```text
KERNEL=="hidraw*"
```

allows access to Linux HID raw interfaces.

Using both prevents the situation where Linux detects the Apex 7 but Apex OLED Studio reports:

```text
open failed
```

## Important safety notes

Do not run Apex OLED Studio with:

```bash
sudo ./run.sh
```

The udev rule exists so your normal user account can access the keyboard.

Avoid using:

```text
MODE="0777"
```

The provided rule uses more restrictive permissions.

The rule only targets:

```text
Vendor ID:  1038
Product ID: 1612
```

so it is specific to the SteelSeries Apex 7.

## Remove the rule

To remove the Apex 7 permission rule:

```bash
sudo rm /etc/udev/rules.d/70-steelseries-apex7.rules
```

Reload udev:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and reconnect the keyboard.

## Quick setup

For future reference:

```bash
sudo tee /etc/udev/rules.d/70-steelseries-apex7.rules >/dev/null <<'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="1038", ATTR{idProduct}=="1612", MODE="0660", GROUP="plugdev", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{idVendor}=="1038", ATTRS{idProduct}=="1612", MODE="0660", GROUP="plugdev", TAG+="uaccess"
EOF

sudo usermod -aG plugdev "$USER"

sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then:

1. Log out and back in if `plugdev` was newly added.
2. Unplug and reconnect the Apex 7.
3. Start Apex OLED Studio normally.

```bash
cd ~/Downloads/apex_oled_studio
./run.sh
```

## Keyboard information

```text
Device: SteelSeries Apex 7
Vendor ID: 1038
Product ID: 1612
Expected OLED HID interface: 1
```

This README is intended for the Linux version of Apex OLED Studio.
