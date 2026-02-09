"""
WebSocket signal handler for autonomous execution state coordination.

This module provides the SignalHandler class for managing WebSocket communication,
including connection management, heartbeat, signal reception, and status updates.
"""

import asyncio
import json
import logging_mp
from typing import Optional
from .types import SignalType, ExecutionState

logger_mp = logging_mp.get_logger(__name__)


class SignalHandler:
    """Handles WebSocket communication for state signals."""
    
    def __init__(self, host: str, port: int, heartbeat_interval: float = 2.0):
        self.host = host
        self.port = port
        self.heartbeat_interval = heartbeat_interval
        self.websocket = None
        self.connected = False
        self.last_signal: Optional[SignalType] = None
        self.signal_queue = asyncio.Queue()
        
    async def connect(self):
        """Connect to WebSocket server."""
        try:
            import websockets
            uri = f"ws://{self.host}:{self.port}"
            logger_mp.info(f"Connecting to WebSocket server at {uri}")
            # Increase ping_timeout to 60s to handle long policy loading operations
            self.websocket = await websockets.connect(uri, ping_timeout=60)
            self.connected = True
            logger_mp.info("WebSocket connected successfully")
            
            # Start heartbeat task
            asyncio.create_task(self._heartbeat_loop())
            # Start receive task
            asyncio.create_task(self._receive_loop())
            
        except Exception as e:
            logger_mp.error(f"Failed to connect to WebSocket server: {e}")
            self.connected = False
            raise
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeat messages."""
        while self.connected and self.websocket:
            try:
                await self.send_message({"type": SignalType.HEARTBEAT.value})
                await asyncio.sleep(self.heartbeat_interval)
            except Exception as e:
                logger_mp.error(f"Heartbeat failed: {e}")
                self.connected = False
                break
    
    async def _receive_loop(self):
        """Receive messages from WebSocket server."""
        while self.connected and self.websocket:
            try:
                message = await self.websocket.recv()
                data = json.loads(message)
                signal_type = data.get("type")
                
                if signal_type and signal_type != SignalType.HEARTBEAT.value:
                    logger_mp.info(f"Received signal: {signal_type}")
                    try:
                        signal = SignalType(signal_type)
                        await self.signal_queue.put(signal)
                    except ValueError:
                        logger_mp.warning(f"Unknown signal type: {signal_type}")
                        
            except Exception as e:
                logger_mp.error(f"Error receiving message: {e}")
                self.connected = False
                break
    
    async def send_message(self, data: dict):
        """Send message to WebSocket server."""
        logger_mp.info(f"Sending {data}")
        if self.websocket and self.connected:
            try:
                await self.websocket.send(json.dumps(data))
            except Exception as e:
                logger_mp.error(f"Failed to send message: {e}")
                self.connected = False
    
    async def wait_for_signal(self, timeout: Optional[float] = None) -> Optional[SignalType]:
        """Wait for next signal from queue."""
        try:
            if timeout:
                signal = await asyncio.wait_for(self.signal_queue.get(), timeout=timeout)
            else:
                signal = await self.signal_queue.get()
            return signal
        except asyncio.TimeoutError:
            return None
    
    async def send_status(self, state: ExecutionState, message: str = ""):
        """Send status update to server."""
        await self.send_message({
            "type": "STATUS_UPDATE",
            "state": state.value,
            "message": message
        })
    
    async def disconnect(self):
        """Disconnect from WebSocket server."""
        self.connected = False
        if self.websocket:
            await self.websocket.close()
            logger_mp.info("WebSocket disconnected")
