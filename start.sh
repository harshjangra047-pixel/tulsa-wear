#!/bin/bash
# Tulsa Wears - Start Server and Cloudflare Tunnel

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Stop existing if running
pkill -f "app.py" 2>/dev/null || true
pkill -f "cloudflared" 2>/dev/null || true
lsof -ti :5050 | xargs kill -9 2>/dev/null || true
sleep 1

# Truncate logs for a clean fresh run
> "$DIR/server.log"
> "$DIR/tunnel.log"

# Start Flask App with virtual environment
nohup "$DIR/venv/bin/python" "$DIR/app.py" >> "$DIR/server.log" 2>&1 &
sleep 2

# Start Cloudflare Tunnel
nohup "$DIR/cloudflared" tunnel --url http://127.0.0.1:5050 >> "$DIR/tunnel.log" 2>&1 &

TUNNEL_URL=""
for i in {1..15}; do
    TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$DIR/tunnel.log" | tail -n 1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    sleep 1
done

LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")

echo "========================================================"
echo "🌸 Tulsa Wears Atelier is RUNNING!"
echo "========================================================"
echo "Local (Mac):      http://127.0.0.1:5050"
echo "Network (Wi-Fi):  http://$LOCAL_IP:5050"
if [ -n "$TUNNEL_URL" ]; then
    echo "Public (Online):  $TUNNEL_URL"
    echo "Admin Portal:     $TUNNEL_URL/admin"
    echo "Website Designer: $TUNNEL_URL/admin/customizer"
fi
echo "========================================================"
