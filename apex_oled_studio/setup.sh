#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "Installing system dependencies..."
sudo apt update
sudo apt install -y python3 python3-venv python3-tk python3-pip libhidapi-hidraw0 libhidapi-libusb0

echo
echo "Creating Python virtual environment..."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo
echo "Apex OLED Studio is ready."
echo "Next:"
echo "  1. Run: ./install-udev.sh"
echo "  2. Unplug/replug the keyboard"
echo "  3. Run: ./run.sh"
