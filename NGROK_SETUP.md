# Ngrok Setup Guide

## Quick Setup (Recommended)

1. **Sign up for ngrok** (free): https://ngrok.com/signup

2. **Get your authtoken** from: https://dashboard.ngrok.com/get-started/your-authtoken

3. **Install ngrok** (if not already installed):
   ```bash
   # macOS
   brew install ngrok/ngrok/ngrok
   
   # Or download from: https://ngrok.com/download
   ```

4. **Add your authtoken**:
   ```bash
   ngrok config add-authtoken YOUR_AUTHTOKEN_HERE
   ```

   This automatically creates the config file at `~/.config/ngrok/ngrok.yml` (Linux/macOS) or `%APPDATA%\ngrok\ngrok.yml` (Windows) and adds your token.

5. **Verify it works**:
   ```bash
   ngrok version
   ```

6. **Start the app with ngrok**:
   ```bash
   USE_NGROK=1 ./scripts/start.sh
   ```

## Manual Config File Setup (Alternative)

If you prefer to use the config file approach:

1. **Copy the example config**:
   ```bash
   cp ngrok.yml.example ~/.config/ngrok/ngrok.yml
   # Or on Windows: copy ngrok.yml.example %APPDATA%\ngrok\ngrok.yml
   ```

2. **Edit the config file** and replace `YOUR_AUTHTOKEN_HERE` with your actual authtoken:
   ```yaml
   version: "2"
   authtoken: YOUR_ACTUAL_AUTHTOKEN_HERE
   
   tunnels:
     backend:
       addr: 8000
       proto: http
       bind_tls: true
       
     frontend:
       addr: 3000
       proto: http
       bind_tls: true
   ```

3. **Start using the config**:
   ```bash
   ngrok start --all
   ```

## Finding Your Authtoken

1. Go to https://dashboard.ngrok.com/get-started/your-authtoken
2. Sign in or create a free account
3. Copy the authtoken shown on the page
4. It looks like: `2abc123def456ghi789jkl012mno345pq_6rst7uvw8xyz9ABCD`

## Troubleshooting

- **Token not working?** Make sure you copied the entire token (no spaces)
- **Config file location?**
  - macOS/Linux: `~/.config/ngrok/ngrok.yml`
  - Windows: `%APPDATA%\ngrok\ngrok.yml`
- **Check ngrok status**: `ngrok config check`

## Notes

- Free ngrok accounts support one tunnel at a time
- For multiple tunnels, use the config file approach or upgrade to a paid plan
- The authtoken is personal - don't share it or commit it to git

