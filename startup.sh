#!/bin/bash
# Startup script for Azure Web App

echo "Starting PraccReminder Discord Bot..."

# Install dependencies if needed
pip install -r requirements.txt

# Run the Flask wrapper
python webapp.py
