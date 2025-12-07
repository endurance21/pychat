"""
FastAPI Chat Application Backend
Real-time group chat with WebSocket support
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Dict, Set, List, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
import json
import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data Models
class UserJoinRequest(BaseModel):
    """Request model for user joining a group"""
    username: str = Field(..., min_length=1, max_length=50)
    group_id: str = Field(..., min_length=1, max_length=4, pattern="^[A-Za-z0-9]+$")

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
            await websocket.send_json(data)
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    async def connect(self, websocket: WebSocket, username: str, group_id: str):
        """Connect a user to a group"""
        # Validate username uniqueness in group
        if group_id in self.group_users and username in self.group_users[group_id]:
            raise ValueError(f"Username '{username}' is already taken in group '{group_id}'")
        
        await websocket.accept()
        
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
            return
        
        username, group_id = self.connection_info[websocket]
        msg = Message(
            username=username,
            group_id=group_id,
            content=message,
            timestamp=datetime.now(),
            message_id=f"{group_id}_{datetime.now().timestamp()}_{username}"
        )
        
        # Add to queue for batching (optimization)
        self.message_queue.append(msg)
        
        # Ensure batch processor is running
        await self.start_batch_processor()
        
        # Also send immediately for very low latency (skip batching for single messages)
        # Or use batching for efficiency - we'll use immediate for lowest latency
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

    async def get_group_users(self, group_id: str) -> List[str]:
        """Get list of users in a group"""
        return list(self.group_users.get(group_id, set()))


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
    title="PyChat API",
    description="Real-time group chat application",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "PyChat API",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


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
    try:
        # Validate group_id format
        if not group_id or len(group_id) > 4 or not group_id.isalnum():
            await websocket.close(code=1008, reason="Invalid group_id format")
            return
        
        # Validate username
        if not username or len(username) > 50:
            await websocket.close(code=1008, reason="Invalid username format")
            return
        
        # Connect user
        await manager.connect(websocket, username, group_id)
        
        # Send welcome message
        await websocket.send_json({
            "type": "welcome",
            "message": f"Welcome to group '{group_id}', {username}!",
            "group_id": group_id,
            "username": username,
            "users": list(manager.group_users.get(group_id, set()))
        })
        
        # Listen for messages
        while True:
            data = await websocket.receive_text()
            
            # Parse message
            try:
                message_data = json.loads(data)
                message_content = message_data.get("message", "").strip()
                
                if message_content:
                    await manager.send_personal_message(message_content, websocket)
            except json.JSONDecodeError:
                # Handle plain text messages for simplicity
                if data.strip():
                    await manager.send_personal_message(data.strip(), websocket)
    
    except ValueError as e:
        logger.error(f"Value error: {e}")
        await websocket.close(code=1008, reason=str(e))
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)

