#!/bin/bash
# Tulsa Wears - Stop Server and Tunnel

pkill -f "app.py" 2>/dev/null && echo "Flask server stopped." || echo "Flask server was not running."
pkill -f "cloudflared" 2>/dev/null && echo "Tunnel stopped." || echo "Tunnel was not running."
lsof -ti :5050 | xargs kill -9 2>/dev/null || true

