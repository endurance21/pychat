"""
FastAPI Chat Application Backend
Real-time group chat with WebSocket support
Serves React frontend as static files
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from typing import Dict, Set, List, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
import json
import asyncio
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data Models
class UserJoinRequest(BaseModel):
    """Request model for user joining a group"""
    username: str = Field(..., min_length=1, max_length=50)
    group_id: str = Field(..., min_length=5, max_length=5, pattern="^[A-Za-z0-9]+$")

class Message(BaseModel):
    """Message model"""
    username: str
    group_id: str
    content: str
    timestamp: datetime
    message_id: Optional[str] = None

class ConnectionManager:
    """
    Manages WebSocket connections and group membership
    Optimized for low latency with efficient message broadcasting
    """
    def __init__(self):
        # group_id -> Set[WebSocket]
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # WebSocket -> (username, group_id)
        self.connection_info: Dict[WebSocket, tuple[str, str]] = {}
        # group_id -> Set[username] for uniqueness checking
        self.group_users: Dict[str, Set[str]] = {}
        # Message queue for batching (optimization)
        self.message_queue: List[Message] = []
        self.batch_size = 10
        self.batch_timeout = 0.05  # 50ms batching window
        self._batch_task: Optional[asyncio.Task] = None
        # Rate limiting: WebSocket -> last message timestamp
        self.last_message_time: Dict[WebSocket, datetime] = {}
        self.RATE_LIMIT_SECONDS = 5
        # Typing indicators: group_id -> Set[username] who are currently typing
        self.typing_users: Dict[str, Set[str]] = {}
        # Typing timeouts: username -> asyncio.Task
        self.typing_timeouts: Dict[str, asyncio.Task] = {}

    async def start_batch_processor(self):
        """Start the message batching processor for low latency optimization"""
        if self._batch_task is None or self._batch_task.done():
            self._batch_task = asyncio.create_task(self._process_message_batch())

    async def _process_message_batch(self):
        """Process batched messages to reduce latency overhead"""
        while True:
            try:
                await asyncio.sleep(self.batch_timeout)
                if self.message_queue:
                    # Group messages by group_id for efficient broadcasting
                    messages_by_group: Dict[str, List[Message]] = {}
                    messages_to_send = self.message_queue[:self.batch_size]
                    self.message_queue = self.message_queue[self.batch_size:]
                    
                    for msg in messages_to_send:
                        if msg.group_id not in messages_by_group:
                            messages_by_group[msg.group_id] = []
                        messages_by_group[msg.group_id].append(msg)
                    
                    # Broadcast batched messages efficiently
                    for group_id, messages in messages_by_group.items():
                        if group_id in self.active_connections:
                            await self._broadcast_batch(group_id, messages)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in batch processor: {e}")

    async def _broadcast_batch(self, group_id: str, messages: List[Message]):
        """Broadcast a batch of messages to all connections in a group"""
        if group_id not in self.active_connections:
            return
        
        connections = self.active_connections[group_id].copy()
        if not connections:
            return
        
        # Prepare message data
        message_data = [{
            "username": msg.username,
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat(),
            "message_id": msg.message_id
        } for msg in messages]
        
        # Broadcast to all connections concurrently
        tasks = []
        for connection in connections:
            try:
                tasks.append(self._send_json(connection, {
                    "type": "messages",
                    "messages": message_data
                }))
            except Exception as e:
                logger.error(f"Error preparing broadcast: {e}")
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_json(self, websocket: WebSocket, data: dict):
        """Send JSON data through websocket"""
        try:
            # Check if connection is still active before sending
            if websocket.client_state.name == "DISCONNECTED":
                return
            await websocket.send_json(data)
        except Exception as e:
            # Connection might be closed, that's okay
            logger.debug(f"Error sending message (connection may be closed): {e}")

    async def connect(self, websocket: WebSocket, username: str, group_id: str):
        """Connect a user to a group (WebSocket must already be accepted)"""
        # Check if username is already taken
        if group_id in self.group_users and username in self.group_users[group_id]:
            # Check if there's an active connection for this username
            # If not, it's a stale entry and we should allow reconnection
            has_active_connection = False
            if group_id in self.active_connections:
                for conn in self.active_connections[group_id]:
                    if conn in self.connection_info:
                        conn_username, _ = self.connection_info[conn]
                        if conn_username == username:
                            # Check if connection is actually alive
                            try:
                                if conn.client_state.name != "DISCONNECTED":
                                    has_active_connection = True
                                    break
                            except Exception:
                                # Connection might be dead, remove it
                                try:
                                    await self.disconnect(conn)
                                except Exception:
                                    pass
            
            if has_active_connection:
                raise ValueError(f"Username '{username}' is already taken in group '{group_id}'")
            else:
                # Stale entry - clean it up and allow reconnection
                logger.info(f"Cleaning up stale connection for '{username}' in '{group_id}'")
                if group_id in self.group_users:
                    self.group_users[group_id].discard(username)
                # Clean up any dead connections for this username
                if group_id in self.active_connections:
                    dead_connections = []
                    for conn in self.active_connections[group_id]:
                        if conn in self.connection_info:
                            conn_username, _ = self.connection_info[conn]
                            if conn_username == username:
                                try:
                                    if conn.client_state.name == "DISCONNECTED":
                                        dead_connections.append(conn)
                                except Exception:
                                    dead_connections.append(conn)
                    for dead_conn in dead_connections:
                        try:
                            await self.disconnect(dead_conn)
                        except Exception:
                            pass
        
        # Add to connections
        if group_id not in self.active_connections:
            self.active_connections[group_id] = set()
        self.active_connections[group_id].add(websocket)
        self.connection_info[websocket] = (username, group_id)
        
        # Add to group users
        if group_id not in self.group_users:
            self.group_users[group_id] = set()
        self.group_users[group_id].add(username)
        
        logger.info(f"User '{username}' joined group '{group_id}'")
        
        # Notify others in the group
        await self._notify_user_joined(username, group_id, websocket)
        
        return websocket

    async def disconnect(self, websocket: WebSocket):
        """Disconnect a user from their group"""
        if websocket not in self.connection_info:
            return
        
        username, group_id = self.connection_info[websocket]
        
        # Remove from connections
        if group_id in self.active_connections:
            self.active_connections[group_id].discard(websocket)
            if not self.active_connections[group_id]:
                del self.active_connections[group_id]
        
        # Remove from group users
        if group_id in self.group_users:
            self.group_users[group_id].discard(username)
            if not self.group_users[group_id]:
                del self.group_users[group_id]
        
        del self.connection_info[websocket]
        
        # Clean up rate limiting data
        if websocket in self.last_message_time:
            del self.last_message_time[websocket]
        
        # Clean up typing indicators
        if group_id in self.typing_users:
            self.typing_users[group_id].discard(username)
        timeout_key = f"{group_id}:{username}"
        if timeout_key in self.typing_timeouts:
            self.typing_timeouts[timeout_key].cancel()
            del self.typing_timeouts[timeout_key]
        
        logger.info(f"User '{username}' left group '{group_id}'")
        
        # Notify others in the group
        await self._notify_user_left(username, group_id)

    async def _notify_user_joined(self, username: str, group_id: str, new_connection: WebSocket):
        """Notify group members when a user joins"""
        if group_id not in self.active_connections:
            return
        
        notification = {
            "type": "user_joined",
            "username": username,
            "group_id": group_id,
            "timestamp": datetime.now().isoformat()
        }
        
        tasks = []
        for connection in self.active_connections[group_id]:
            if connection != new_connection:
                tasks.append(self._send_json(connection, notification))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _notify_user_left(self, username: str, group_id: str):
        """Notify group members when a user leaves"""
        if group_id not in self.active_connections:
            return
        
        notification = {
            "type": "user_left",
            "username": username,
            "group_id": group_id,
            "timestamp": datetime.now().isoformat()
        }
        
        tasks = []
        for connection in self.active_connections[group_id]:
            tasks.append(self._send_json(connection, notification))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        """Send a message from a user to their group"""
        if websocket not in self.connection_info:
            return None
        
        # Rate limiting check
        if websocket in self.last_message_time:
            time_since_last = (datetime.now() - self.last_message_time[websocket]).total_seconds()
            if time_since_last < self.RATE_LIMIT_SECONDS:
                remaining = self.RATE_LIMIT_SECONDS - time_since_last
                return {
                    "error": "rate_limit",
                    "message": f"Please wait {int(remaining)} seconds before sending another message",
                    "remaining_seconds": int(remaining)
                }
        
        username, group_id = self.connection_info[websocket]
        msg = Message(
            username=username,
            group_id=group_id,
            content=message,
            timestamp=datetime.now(),
            message_id=f"{group_id}_{datetime.now().timestamp()}_{username}"
        )
        
        # Update last message time
        self.last_message_time[websocket] = datetime.now()
        
        # Send immediately for low latency
        if group_id in self.active_connections:
            message_data = {
                "type": "message",
                "username": msg.username,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "message_id": msg.message_id
            }
            
            tasks = []
            for connection in self.active_connections[group_id]:
                tasks.append(self._send_json(connection, message_data))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            return {"success": True}
        
        return None

    async def get_group_users(self, group_id: str) -> List[str]:
        """Get list of users in a group"""
        return list(self.group_users.get(group_id, set()))

    async def handle_typing(self, websocket: WebSocket, is_typing: bool):
        """Handle typing indicator from a user"""
        if websocket not in self.connection_info:
            return
        
        username, group_id = self.connection_info[websocket]
        
        if group_id not in self.typing_users:
            self.typing_users[group_id] = set()
        
        if is_typing:
            # Add user to typing set
            self.typing_users[group_id].add(username)
            
            # Cancel existing timeout if any
            timeout_key = f"{group_id}:{username}"
            if timeout_key in self.typing_timeouts:
                self.typing_timeouts[timeout_key].cancel()
            
            # Set timeout to remove typing indicator after 3 seconds
            async def remove_typing():
                try:
                    await asyncio.sleep(3)
                    # Check if connection still exists before broadcasting
                    if websocket not in self.connection_info:
                        # Connection was closed, just clean up
                        if timeout_key in self.typing_timeouts:
                            del self.typing_timeouts[timeout_key]
                        return
                    
                    if group_id in self.typing_users:
                        self.typing_users[group_id].discard(username)
                        await self._broadcast_typing(group_id, username, False)
                    if timeout_key in self.typing_timeouts:
                        del self.typing_timeouts[timeout_key]
                except asyncio.CancelledError:
                    # Task was cancelled, that's fine
                    pass
                except Exception as e:
                    logger.error(f"Error in typing timeout task: {e}")
                    if timeout_key in self.typing_timeouts:
                        del self.typing_timeouts[timeout_key]
            
            self.typing_timeouts[timeout_key] = asyncio.create_task(remove_typing())
        else:
            # Remove user from typing set
            self.typing_users[group_id].discard(username)
            timeout_key = f"{group_id}:{username}"
            if timeout_key in self.typing_timeouts:
                self.typing_timeouts[timeout_key].cancel()
                del self.typing_timeouts[timeout_key]
        
        # Broadcast typing status to other users in the group
        await self._broadcast_typing(group_id, username, is_typing)

    async def _broadcast_typing(self, group_id: str, username: str, is_typing: bool):
        """Broadcast typing indicator to all users in group except the sender"""
        if group_id not in self.active_connections:
            return
        
        typing_list = list(self.typing_users.get(group_id, set()))
        
        notification = {
            "type": "typing",
            "username": username,
            "is_typing": is_typing,
            "typing_users": typing_list,
            "timestamp": datetime.now().isoformat()
        }
        
        tasks = []
        # Create a copy of connections to avoid modification during iteration
        connections_copy = list(self.active_connections[group_id])
        for connection in connections_copy:
            # Only send to active connections that still exist in connection_info
            if connection in self.connection_info:
                conn_username, _ = self.connection_info[connection]
                if conn_username != username:  # Don't send to the person typing
                    tasks.append(self._send_json(connection, notification))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Clean up any connections that failed
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    # Connection might be dead, will be cleaned up on next disconnect
                    logger.debug(f"Failed to send typing indicator: {result}")


# Global connection manager
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown"""
    # Startup
    logger.info("Starting chat server...")
    await manager.start_batch_processor()
    yield
    # Shutdown
    logger.info("Shutting down chat server...")
    if manager._batch_task:
        manager._batch_task.cancel()
        try:
            await manager._batch_task
        except asyncio.CancelledError:
            pass


# FastAPI app
app = FastAPI(
    title="PyChat",
    description="Real-time group chat application",
    version="1.0.0",
    lifespan=lifespan
)

# Serve static files from React build
FRONTEND_BUILD_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "build")
if os.path.exists(FRONTEND_BUILD_DIR):
    # Mount static files (JS, CSS, images, etc.)
    app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_BUILD_DIR, "static")), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/api")
async def api_info():
    """API information endpoint"""
    return {
        "message": "PyChat API",
        "status": "running",
        "version": "1.0.0"
    }


# Serve React app for all non-API routes (must be last)
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve React frontend for all routes except API/WebSocket"""
    # Exclude API routes, WebSocket, and static files
    if (full_path.startswith("api/") or 
        full_path.startswith("ws/") or 
        full_path.startswith("groups/") or 
        full_path.startswith("static/") or
        full_path == "health"):
        raise HTTPException(status_code=404, detail="Not found")
    
    # Serve index.html for React routes (SPA)
    index_path = os.path.join(FRONTEND_BUILD_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        raise HTTPException(
            status_code=503, 
            detail="Frontend not built. Please run 'npm run build' in the frontend directory"
        )


@app.get("/groups/{group_id}/users")
async def get_group_users(group_id: str):
    """Get list of users in a group"""
    users = await manager.get_group_users(group_id)
    return {"group_id": group_id, "users": users}


@app.websocket("/ws/{username}/{group_id}")
async def websocket_endpoint(websocket: WebSocket, username: str, group_id: str):
    """
    WebSocket endpoint for real-time chat
    Path parameters: username and group_id
    """
    logger.info(f"WebSocket connection attempt: username='{username}', group_id='{group_id}'")
    
    # Accept the WebSocket connection first to avoid 403 errors
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for '{username}' in group '{group_id}'")
    
    try:
        # Validate group_id format (must be exactly 5 alphanumeric characters)
        group_id = group_id.strip()
        if len(group_id) != 5 or not group_id.isalnum():
            logger.warning(f"Invalid group_id format: '{group_id}' (length={len(group_id)})")
            await websocket.close(code=1008, reason="Room name must be exactly 5 alphanumeric characters")
            return
        
        # Validate username
        if not username or len(username) > 50:
            logger.warning(f"Invalid username format: '{username}'")
            await websocket.close(code=1008, reason="Invalid username format")
            return
        
        # Connect user (this will validate and add to connections)
        try:
            await manager.connect(websocket, username, group_id)
            logger.info(f"User '{username}' successfully connected to group '{group_id}'")
        except ValueError as e:
            # Username already taken or other validation error
            logger.warning(f"Connection rejected for '{username}' in '{group_id}': {e}")
            await websocket.close(code=1008, reason=str(e))
            return
        
        # Send welcome message
        try:
            await websocket.send_json({
                "type": "welcome",
                "message": f"Welcome to group '{group_id}', {username}!",
                "group_id": group_id,
                "username": username,
                "users": list(manager.group_users.get(group_id, set()))
            })
            logger.debug(f"Welcome message sent to '{username}'")
        except Exception as e:
            logger.error(f"Failed to send welcome message: {e}")
            await manager.disconnect(websocket)
            return
        
        # Listen for messages
        logger.info(f"Starting message loop for '{username}' in '{group_id}'")
        while True:
            try:
                # Check if connection is still open before receiving
                if websocket.client_state.name == "DISCONNECTED":
                    logger.info(f"Connection already disconnected for '{username}', breaking loop")
                    break
                    
                data = await websocket.receive_text()
                logger.debug(f"Received message from '{username}': {len(data)} bytes")
                
                # Parse message
                try:
                    message_data = json.loads(data)
                    
                    # Check for typing indicator
                    if "typing" in message_data:
                        is_typing = message_data.get("typing", False)
                        await manager.handle_typing(websocket, is_typing)
                        continue
                    
                    # Handle regular message
                    message_content = message_data.get("message", "").strip()
                    
                    if message_content:
                        # Stop typing indicator when sending message
                        await manager.handle_typing(websocket, False)
                        result = await manager.send_personal_message(message_content, websocket)
                        # If rate limited, send error response
                        if result and "error" in result:
                            try:
                                await websocket.send_json({
                                    "type": "rate_limit",
                                    "message": result["message"],
                                    "remaining_seconds": result["remaining_seconds"]
                                })
                            except Exception as send_error:
                                logger.debug(f"Could not send rate limit message: {send_error}")
                                break
                except json.JSONDecodeError:
                    # Handle plain text messages for simplicity
                    if data.strip():
                        # Stop typing indicator when sending message
                        await manager.handle_typing(websocket, False)
                        result = await manager.send_personal_message(data.strip(), websocket)
                        if result and "error" in result:
                            try:
                                await websocket.send_json({
                                    "type": "rate_limit",
                                    "message": result["message"],
                                    "remaining_seconds": result["remaining_seconds"]
                                })
                            except Exception as send_error:
                                logger.debug(f"Could not send rate limit message: {send_error}")
                                break
            except WebSocketDisconnect:
                # Normal client disconnect, break out of loop
                logger.info(f"WebSocket disconnect received for '{username}' (normal closure)")
                break
    
    except ValueError as e:
        logger.error(f"Value error for '{username}': {e}")
        try:
            await websocket.close(code=1008, reason=str(e))
        except Exception:
            pass
    except WebSocketDisconnect:
        # Normal client disconnect
        logger.info(f"WebSocket disconnect exception for '{username}'")
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error for '{username}': {e}", exc_info=True)
        try:
            await manager.disconnect(websocket)
        except Exception as cleanup_error:
            logger.error(f"Error during disconnect cleanup: {cleanup_error}")
        # Try to close the connection properly if still open
        try:
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass  # Connection might already be closed
    finally:
        # Clean up connection if not already done
        if websocket in manager.connection_info:
            logger.info(f"Cleaning up WebSocket connection for '{username}' in '{group_id}'")
            await manager.disconnect(websocket)

