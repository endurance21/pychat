# PyChat

Group chat application with real-time WebSocket communication. Built with FastAPI (Python) and React.

## Requirements

- Python 3.9+
- Node.js 16+
- npm

## Setup

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

## Running

### Using scripts

Start server (builds frontend and serves from FastAPI):
```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

Start with ngrok (public URL):
```bash
USE_NGROK=1 ./scripts/start.sh
```

Stop server:
```bash
./scripts/stop.sh
```

Or press Ctrl+C in the terminal running start.sh

The script will:
1. Build the React frontend
2. Start FastAPI server on port 8000 (serves both API and frontend)
3. Optionally start ngrok tunnel if `USE_NGROK=1` is set

Open http://localhost:8000 in your browser (or the ngrok URL if enabled).

### Ngrok Setup

1. Install ngrok from https://ngrok.com/download
2. Sign up for a free account and get your authtoken
3. Run: `ngrok config add-authtoken YOUR_TOKEN`
4. Start with: `USE_NGROK=1 ./scripts/start.sh`

Public URL will be saved to `ngrok_urls.txt` file.

### Manual

1. Build frontend:
```bash
cd frontend
npm install
npm run build
```

2. Start backend (serves frontend too):
```bash
cd backend
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 in your browser.

## Usage

1. Enter a username (must be unique in the room)
2. Enter a room name (exactly 5 alphanumeric characters, e.g., "ABC12")
3. Click "Join Chat"
4. Start messaging

Multiple users can join the same room by using the same room name (exactly 5 characters).

## API

WebSocket: `ws://localhost:8000/ws/{username}/{group_id}`

REST:
- `GET /api` - API info
- `GET /health` - Health check
- `GET /groups/{group_id}/users` - List users in group

All other routes serve the React frontend.

## Project Structure

```
pychat/
├── backend/
│   ├── main.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
├── scripts/
│   ├── start.sh
│   └── stop.sh
└── README.md
```
