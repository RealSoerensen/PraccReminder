#!/bin/bash
# Startup script for Azure Web App

echo "=== Starting PraccReminder Discord Bot ==="
echo "Working directory: $(pwd)"
echo "Python version: $(python --version)"
echo "Files in directory:"
ls -la

# Install dependencies if needed
echo "Installing dependencies..."
pip install -r requirements.txt

# Start the Flask wrapper with gunicorn
echo "Starting gunicorn server..."
gunicorn webapp:app --bind 0.0.0.0:8000 --timeout 600 --workers 1 --log-level info --access-logfile - --error-logfile -

