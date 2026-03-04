#!/bin/bash

# NFL Mock Draft 2026 - Startup Script
# This script ensures port 8988 is available and starts the application

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Application port (CRITICAL: Always 8988)
PORT=8988

echo -e "${BLUE}🏈 2026 NFL Mock Draft - Startup Script${NC}"
echo -e "${BLUE}=========================================${NC}\n"

# Check if port 8988 is in use
echo -e "${YELLOW}🔍 Checking if port ${PORT} is in use...${NC}"

# Find process using port 8988
PID=$(lsof -ti:${PORT} 2>/dev/null || true)

if [ -n "$PID" ]; then
    echo -e "${YELLOW}⚠️  Found process running on port ${PORT} (PID: ${PID})${NC}"
    echo -e "${YELLOW}🔪 Killing process ${PID}...${NC}"

    # Try graceful kill first
    kill $PID 2>/dev/null || true

    # Wait a moment for graceful shutdown
    sleep 2

    # Check if still running
    if lsof -ti:${PORT} >/dev/null 2>&1; then
        echo -e "${RED}⚠️  Process didn't stop gracefully, forcing...${NC}"
        kill -9 $PID 2>/dev/null || true
        sleep 1
    fi

    # Verify it's killed
    if lsof -ti:${PORT} >/dev/null 2>&1; then
        echo -e "${RED}❌ Failed to free port ${PORT}${NC}"
        echo -e "${RED}   Please manually kill the process and try again${NC}"
        exit 1
    else
        echo -e "${GREEN}✅ Port ${PORT} is now free${NC}\n"
    fi
else
    echo -e "${GREEN}✅ Port ${PORT} is available${NC}\n"
fi

# Start the application
echo -e "${GREEN}🚀 Starting NFL Mock Draft 2026...${NC}"
echo -e "${BLUE}=========================================${NC}\n"

# Run the server
uv run server.py
