#!/bin/bash
# Networking Agent — First-time setup
# Run: bash setup.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}━━━ Networking Agent Setup ━━━${NC}"
echo ""

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Step 1: .env file ──────────────────────────────────────────────────────────
echo -e "${BOLD}[1/5] Environment variables${NC}"
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo -e "${YELLOW}  Created .env from template. Fill in your keys:${NC}"
    echo "    ANTHROPIC_API_KEY   → claude.ai/settings/keys"
    echo "    GITHUB_TOKEN        → github.com/settings/tokens (read:user, read:org)"
    echo "    GMAIL_APP_PASSWORD  → myaccount.google.com/apppasswords (needs 2FA)"
    echo "    HUNTER_API_KEY      → hunter.io (free 25/mo)"
    echo "    UK_CH_API_KEY       → find-and-update.company-information.service.gov.uk/get-started"
    echo ""
    echo -e "${YELLOW}  Edit the file now:${NC} nano $REPO_DIR/.env"
    echo ""
    read -p "  Press Enter when .env is filled in, or Ctrl+C to exit..."
else
    echo -e "  ${GREEN}✓${NC} .env already exists"
fi

# Load .env
set -a
source "$REPO_DIR/.env"
set +a

# ── Step 2: Python deps ────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[2/5] Python dependencies${NC}"
if ! python3 -c "import anthropic" 2>/dev/null; then
    echo "  Installing..."
    pip3 install -r "$REPO_DIR/agents/requirements.txt" --quiet
    echo -e "  ${GREEN}✓${NC} Installed"
else
    echo -e "  ${GREEN}✓${NC} Already installed"
fi

# ── Step 3: Rust build ────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[3/5] Rust MCP server${NC}"
if [ ! -f "$REPO_DIR/target/release/networking-agent" ]; then
    echo "  Building (takes ~60s first time)..."
    cd "$REPO_DIR" && cargo build --release 2>&1 | tail -5
    echo -e "  ${GREEN}✓${NC} Built → target/release/networking-agent"
else
    echo -e "  ${GREEN}✓${NC} Already built"
fi

# ── Step 4: SQLite DB ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[4/5] SQLite database${NC}"
DB_PATH="${NETWORKING_DB:-$HOME/networking-agent.db}"
if [ ! -f "$DB_PATH" ]; then
    echo "  Initializing DB at $DB_PATH..."
    "$REPO_DIR/target/release/networking-agent" --init-db 2>/dev/null || true
    # If --init-db not supported, sqlx migrations via cargo sqlx is used at runtime
    echo -e "  ${GREEN}✓${NC} Will initialize on first run"
else
    echo -e "  ${GREEN}✓${NC} DB exists at $DB_PATH"
fi

# ── Step 5: MCP server registration ───────────────────────────────────────────
echo ""
echo -e "${BOLD}[5/5] Register MCP server with Claude Code${NC}"
echo ""
echo "  Run this command to register:"
echo ""
echo -e "  ${YELLOW}claude mcp add networking-agent \\"
echo "    -s user \\"
echo "    -e GITHUB_TOKEN=\"${GITHUB_TOKEN:-ghp_...}\" \\"
echo "    -e HUNTER_API_KEY=\"${HUNTER_API_KEY:-...}\" \\"
echo "    -e NETWORKING_DB=\"$DB_PATH\" \\"
echo -e "    -- $REPO_DIR/target/release/networking-agent${NC}"
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "${BOLD}━━━ Setup complete ━━━${NC}"
echo ""
echo "  Test commands:"
echo ""
echo "  # Check pipeline is empty"
echo "  cd $REPO_DIR/agents && python cli.py dashboard"
echo ""
echo "  # Discover YC companies (needs ANTHROPIC_API_KEY + GITHUB_TOKEN)"
echo "  python cli.py run --query 'AI infrastructure' --mode yc --limit 5 --no-bridge"
echo ""
echo "  # Generate CV from a job description"
echo "  python cli.py cv --jd /path/to/jd.txt --company 'Anthropic' --role 'MCP Engineer'"
echo ""
echo "  # Classify non-technical companies (Track B)"
echo "  python cli.py classify --mode manual --company 'Apex Wealth' --location 'London, UK' --sector 'wealth management'"
echo ""
echo "  # Look up UK company"
echo "  python cli.py lookup --company 'Apex Capital Management' --country uk"
echo ""
