#!/bin/bash
set -e

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Setup complete!"
echo "Run the project with: source .venv/bin/activate && python main.py"