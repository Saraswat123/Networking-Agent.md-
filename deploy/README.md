# deploy/ — systemd service files

## Components

| File | Purpose |
|------|---------|
| `networking-agent.service` | Long-running MCP server (stdio; started by Claude Code / MCP client) |
| `pipeline-loop.service` | One-shot: reply monitor + daily apply (run by timer) |
| `pipeline-loop.timer` | Run `pipeline-loop.service` every 6 hours |

## Install (Linux/macOS with systemd)

```bash
# 1. Build the binary
cargo build --release
sudo cp target/release/networking-agent /opt/networking-agent/
sudo cp -r agents/ /opt/networking-agent/

# 2. Copy env template
sudo cp deploy/networking-agent.service /etc/systemd/system/
sudo cp deploy/pipeline-loop.service    /etc/systemd/system/
sudo cp deploy/pipeline-loop.timer      /etc/systemd/system/

# 3. Set API keys
sudo mkdir -p /etc/
sudo tee /etc/networking-agent.env > /dev/null <<'EOF'
GITHUB_TOKEN=ghp_...
HUNTER_API_KEY=...
APOLLO_API_KEY=...
NETWORKING_DB=/opt/networking-agent/data/networking.db
EOF
sudo chmod 600 /etc/networking-agent.env

# 4. Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now pipeline-loop.timer

# Check timer status
systemctl list-timers pipeline-loop.timer
journalctl -u pipeline-loop.service -f
```

## macOS (launchd alternative)

For macOS without systemd, use a LaunchAgent plist:
```bash
# Run once every 6 hours (21600 seconds)
cat > ~/Library/LaunchAgents/com.networking-agent.pipeline.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.networking-agent.pipeline</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/opt/networking-agent/agents/reply_monitor.py</string>
  </array>
  <key>StartInterval</key><integer>21600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/pipeline.log</string>
  <key>StandardErrorPath</key><string>/tmp/pipeline-err.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.networking-agent.pipeline.plist
```
