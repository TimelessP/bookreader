#!/usr/bin/env bash

set -e

#sudo apt update
#sudo apt install portaudio19-dev

python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
