#!/bin/bash

# PyChat - Stop Script
# This script stops both backend and frontend servers

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Stopping PyChat servers...${NC}"

# Find and kill backend processes (uvicorn)
BACKEND_PIDS=$(ps aux | grep "[u]vicorn main:app" | awk '{print $2}')
if [ ! -z "$BACKEND_PIDS" ]; then
    echo -e "${GREEN}Stopping backend server (PID: $BACKEND_PIDS)...${NC}"
    echo $BACKEND_PIDS | xargs kill 2>/dev/null || true
    sleep 1
else
    echo -e "${YELLOW}Backend server not running${NC}"
fi


# Find and kill ngrok processes
NGROK_PIDS=$(ps aux | grep "[n]grok" | grep -v grep | awk '{print $2}')
if [ ! -z "$NGROK_PIDS" ]; then
    echo -e "${GREEN}Stopping ngrok tunnels (PID: $NGROK_PIDS)...${NC}"
    echo $NGROK_PIDS | xargs kill 2>/dev/null || true
    sleep 1
else
    echo -e "${YELLOW}Ngrok not running${NC}"
fi


# Also check for processes on port 8000
PORT_8000_PID=$(lsof -ti:8000 2>/dev/null || true)

if [ ! -z "$PORT_8000_PID" ]; then
    echo -e "${GREEN}Killing process on port 8000 (PID: $PORT_8000_PID)...${NC}"
    kill $PORT_8000_PID 2>/dev/null || true
fi

sleep 1
echo -e "${GREEN}✓ All servers stopped${NC}"

