#!/bin/bash

# PyChat - Start Script
# This script starts both backend and frontend servers with ngrok

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get the project root directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# Check if ngrok should be used (set USE_NGROK=1 to enable)
USE_NGROK=${USE_NGROK:-0}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  PyChat - Starting Servers${NC}"
if [ "$USE_NGROK" = "1" ]; then
    echo -e "${CYAN}  (with ngrok tunnels)${NC}"
fi
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Error: Python 3 is not installed${NC}"
    exit 1
fi

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo -e "${YELLOW}Error: Node.js is not installed${NC}"
    exit 1
fi

# Check if ngrok is installed (if USE_NGROK is enabled)
if [ "$USE_NGROK" = "1" ]; then
    if ! command -v ngrok &> /dev/null; then
        echo -e "${YELLOW}Error: ngrok is not installed${NC}"
        echo -e "${YELLOW}Install it from: https://ngrok.com/download${NC}"
        echo -e "${YELLOW}Or set USE_NGROK=0 to run without ngrok${NC}"
        exit 1
    fi
fi

# Function to get ngrok URL from API
get_ngrok_url() {
    local api_port=${1:-4040}
    local max_attempts=5
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        sleep 2
        local response=$(curl -s http://localhost:${api_port}/api/tunnels 2>/dev/null)
        if [ ! -z "$response" ] && [ "$response" != "null" ]; then
            local url=$(echo "$response" | grep -o '"public_url":"https://[^"]*"' | head -1 | cut -d'"' -f4)
            if [ -z "$url" ]; then
                url=$(echo "$response" | grep -o '"public_url":"http://[^"]*"' | head -1 | cut -d'"' -f4)
            fi
            if [ ! -z "$url" ]; then
                echo "$url"
                return 0
            fi
        fi
        attempt=$((attempt + 1))
    done
    echo ""
    return 1
}

# Function to cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down server...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    if [ ! -z "$NGROK_PID" ]; then
        kill $NGROK_PID 2>/dev/null || true
    fi
    exit
}

trap cleanup SIGINT SIGTERM

# Build Frontend First
echo -e "${GREEN}[1/3] Building Frontend...${NC}"
cd "$FRONTEND_DIR"

# Install npm dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm install --silent
fi

# Build React app
echo "Building React app..."
npm run build

if [ ! -d "build" ]; then
    echo -e "${YELLOW}Error: Frontend build failed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Frontend built successfully${NC}"

# Start Backend Server
echo -e "${GREEN}[2/3] Starting Backend Server...${NC}"
cd "$BACKEND_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies if needed
if [ ! -f "venv/.deps_installed" ]; then
    echo "Installing Python dependencies..."
    pip install -q --upgrade pip
    pip install -r requirements.txt
    if [ $? -eq 0 ]; then
        touch venv/.deps_installed
    else
        echo -e "${YELLOW}Dependency installation failed. Trying with verbose output...${NC}"
        pip install -r requirements.txt
        exit 1
    fi
fi

# Start backend server (serves both API and frontend)
echo "Starting FastAPI server on http://localhost:8000"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Wait a moment for backend to start
sleep 3

# Start ngrok tunnel if enabled
NGROK_URL=""
NGROK_WS=""
NGROK_API_PORT=4040
NGROK_PID=""

if [ "$USE_NGROK" = "1" ]; then
    echo -e "${GREEN}[3/3] Starting ngrok tunnel (port 8000)...${NC}"
    echo -e "${CYAN}Exposing server on port 8000...${NC}"
    
    # Start ngrok for port 8000 (serves both frontend and backend)
    ngrok http 8000 --log=stdout > /tmp/ngrok.log 2>&1 &
    NGROK_PID=$!
    
    echo -e "${CYAN}Waiting for ngrok tunnel to be ready...${NC}"
    NGROK_URL=$(get_ngrok_url $NGROK_API_PORT)
    
    if [ ! -z "$NGROK_URL" ]; then
        # Convert https to wss for WebSocket
        NGROK_WS=$(echo "$NGROK_URL" | sed 's|^https://|wss://|' | sed 's|^http://|ws://|')
        echo -e "${GREEN}✓ Public URL: ${NGROK_URL}${NC}"
        echo -e "${GREEN}  WebSocket URL: ${NGROK_WS}${NC}"
    else
        echo -e "${YELLOW}Warning: Could not get ngrok URL. Check ngrok logs at /tmp/ngrok.log${NC}"
        echo -e "${YELLOW}You can check ngrok dashboard at http://localhost:${NGROK_API_PORT}${NC}"
        echo -e "${YELLOW}Make sure you've run: ngrok config add-authtoken YOUR_TOKEN${NC}"
    fi
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ Servers are running!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
# Save URLs to file
URLS_FILE="$PROJECT_ROOT/ngrok_urls.txt"
if [ "$USE_NGROK" = "1" ]; then
    # Save to file (no colors)
    {
        echo "# PyChat Ngrok URLs"
        echo "# Generated: $(date)"
        echo ""
        if [ ! -z "$NGROK_URL" ]; then
            echo "PUBLIC_URL=${NGROK_URL}"
            echo "WEBSOCKET_URL=${NGROK_WS}"
        else
            echo "# PUBLIC_URL=not available"
            echo "# WEBSOCKET_URL=not available"
        fi
        echo ""
        echo "# Ngrok Dashboard URL"
        echo "NGROK_DASHBOARD=http://localhost:${NGROK_API_PORT}"
    } > "$URLS_FILE"
    
    # Display with colors
    echo -e "${CYAN}Public URL (ngrok):${NC}"
    if [ ! -z "$NGROK_URL" ]; then
        echo -e "URL:  ${GREEN}${NGROK_URL}${NC}"
        echo -e "WebSocket: ${GREEN}${NGROK_WS}${NC}"
    else
        echo -e "${YELLOW}URL: not available${NC}"
    fi
    echo ""
    echo -e "${GREEN}✓ URLs saved to: ${URLS_FILE}${NC}"
    echo ""
fi

echo -e "${CYAN}Local URL:${NC}"
echo -e "${GREEN}http://localhost:8000${NC}"
echo ""

if [ "$USE_NGROK" = "1" ]; then
    echo -e "${CYAN}Ngrok dashboard: ${GREEN}http://localhost:${NGROK_API_PORT}${NC}"
    echo ""
fi
echo -e "${YELLOW}Press Ctrl+C to stop all servers${NC}"
echo ""

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID

