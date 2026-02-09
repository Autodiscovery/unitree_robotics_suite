"""
Dummy WebSocket server for testing autonomous.py

This server provides a simple CLI interface to manually send signals
to the autonomous execution script for testing purposes.

Signal Flow:
  1. START_EXECUTION - Start Policy 1 execution
  2. POLICY_SUCCESS - Signal Policy 1 completion (triggers navigation)
  3. NAV_COMPLETE - Signal navigation completion (triggers Policy 2)
  4. ABORT - Emergency abort
  5. POLICY_2_COMPLETE - Signal Policy 2 completion (triggers return to A)

Note: Policy 1 retries automatically on timeout (no manual signal needed).
      Policy 2 runs for timeout duration only (ignores success signals).

Usage:
    python signal_server.py --port 8765
"""

import asyncio
import websockets
import json
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SignalServer:
    """WebSocket server for sending manual signals to autonomous execution."""
    
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.server = None
        self.robot_state = "idle"  # Track robot execution state for signal filtering
        
    async def register_client(self, websocket):
        """Register a new client connection."""
        self.clients.add(websocket)
        client_addr = websocket.remote_address
        logger.info(f"Client connected: {client_addr}")
        logger.info(f"Total clients: {len(self.clients)}")
        
    async def unregister_client(self, websocket):
        """Unregister a client connection."""
        self.clients.remove(websocket)
        client_addr = websocket.remote_address
        logger.info(f"Client disconnected: {client_addr}")
        logger.info(f"Total clients: {len(self.clients)}")
        
    async def handle_client(self, websocket):
        """Handle incoming client connection."""
        await self.register_client(websocket)
        
        try:
            async for message in websocket:
                try: 
                    data = json.loads(message)
                    msg_type = data.get("type", "UNKNOWN")
                    
                    if msg_type == "HEARTBEAT":
                        # Respond to heartbeat
                        await websocket.send(json.dumps({"type": "HEARTBEAT_ACK"}))
                    elif msg_type == "STATUS_UPDATE":
                        # Log status updates from robot and track state
                        state = data.get("state", "unknown")
                        msg = data.get("message", "")
                        self.robot_state = state  # Update tracked state
                        logger.info(f"Robot Status: [{state}] {msg}")
                    elif msg_type == "READY_FOR_NAV":
                        # Robot is ready for navigation
                        msg = data.get("message", "")
                        logger.info(f"🤖 READY_FOR_NAV: {msg}")
                        print("\n" + "="*60)
                        print("🚀 ROBOT IS READY FOR NAVIGATION")
                        print("   Send NAV_COMPLETE signal when navigation is done")
                        print("="*60 + "\n")
                    elif msg_type == "POLICY_2_COMPLETE":
                        # Policy 2 complete
                        msg = data.get("message", "")
                        logger.info(f"🏁 POLICY_2_COMPLETE: {msg}")
                        print("\n" + "="*60)
                        print("🏁 POLICY 2 COMPLETION SIGNAL RECEIVED")
                        print("   Robot should return to Goal A")
                        print("="*60 + "\n")
                        
                        # Broadcast to all clients (especially the nav manager)
                        await self.broadcast_signal("POLICY_2_COMPLETE", msg)
                    elif msg_type == "START_EXECUTION":
                        msg = data.get("message", "")
                        logger.info(f"🚀 START_EXECUTION received. Delaying 3s...")
                        print("\n" + "="*60)
                        print("🚀 START_EXECUTION RECEIVED")
                        print("   Broadcasting in 3 seconds...")
                        print("="*60 + "\n")
                        
                        await asyncio.sleep(3)
                        await self.broadcast_signal("START_EXECUTION", msg)

                    elif msg_type == "NAV_COMPLETE":
                        msg = data.get("message", "")
                        logger.info(f"🏁 NAV_COMPLETE received. Delaying 3s...")
                        print("\n" + "="*60)
                        print("🏁 NAV_COMPLETE RECEIVED")
                        print("   Broadcasting in 3 seconds...")
                        print("="*60 + "\n")
                        
                        await asyncio.sleep(3)
                        await self.broadcast_signal("NAV_COMPLETE", msg)

                    elif msg_type == "GPIO_TRIGGER":
                        # GPIO switch signal from G1 robot
                        gpio = data.get("gpio", "unknown")
                        msg = data.get("message", "")
                        timestamp = data.get("timestamp", "")
                        logger.info(f"🔘 GPIO_TRIGGER received: GPIO{gpio} - {msg}")
                        
                        # Filter based on robot state - only accept during Policy 1 execution
                        if self.robot_state == "executing_policy_1":
                            logger.info(f"✅ GPIO signal accepted (robot in Policy 1 execution)")
                            # Convert to POLICY_SUCCESS and broadcast to robot
                            await self.broadcast_signal("POLICY_SUCCESS", f"GPIO{gpio} switch triggered")
                            print("\n" + "="*60)
                            print("✅ GPIO SWITCH TRIGGERED - POLICY 1 SUCCESS")
                            print(f"   GPIO{gpio} switch pressed at {timestamp}")
                            print("="*60 + "\n")
                        else:
                            logger.info(f"🚫 GPIO signal filtered (robot state: {self.robot_state})")
                            print(f"⚠️  GPIO signal ignored (robot not executing Policy 1, current state: {self.robot_state})")
                    else:
                        logger.info(f"Received: {data}")
                        
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {message}")
                    
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister_client(websocket)
    
    async def broadcast_signal(self, signal_type: str, message: str = ""):
        """Broadcast a signal to all connected clients."""
        if not self.clients:
            logger.warning("No clients connected to send signal to")
            return
        
        data = {
            "type": signal_type,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"Broadcasting signal: {signal_type}")
        
        # Send to all clients
        disconnected = set()
        for client in self.clients:
            try:
                await client.send(json.dumps(data))
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
        
        # Remove disconnected clients
        for client in disconnected:
            await self.unregister_client(client)
    
    async def start_server(self):
        """Start the WebSocket server."""
        logger.info(f"Starting WebSocket server on {self.host}:{self.port}")
        # Increase ping_timeout to 60s to handle long client operations (e.g., policy loading)
        self.server = await websockets.serve(self.handle_client, self.host, self.port, ping_timeout=60)
        logger.info("Server started successfully")
        logger.info("Waiting for clients to connect...")

        
    async def stop_server(self):
        """Stop the WebSocket server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("Server stopped")


async def interactive_cli(server: SignalServer):
    """Interactive CLI for sending signals."""
    
    print("\n" + "="*60)
    print("AUTONOMOUS EXECUTION SIGNAL SERVER")
    print("="*60)
    print("\nAvailable Commands:")
    print("  1 - Send START_EXECUTION")
    print("  2 - Send POLICY_SUCCESS (Policy 1 only)")
    print("  3 - Send NAV_COMPLETE")
    print("  4 - Send ABORT")
    print("  s - Show server status")
    print("  q - Quit server")
    print("\nNotes:")
    print("  • Policy 1 retries automatically on timeout (no manual signal needed)")
    print("  • Policy 2 runs for timeout duration only (ignores success signals)")
    print("="*60 + "\n")
    
    while True:
        try:
            # Use asyncio to read input without blocking
            await asyncio.sleep(0.1)
            
            # Check if input is available (non-blocking)
            import sys
            import select
            
            if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline().strip()
                
                if line == "1":
                    await server.broadcast_signal("START_EXECUTION", "Manual start signal")
                    print("✅ Sent START_EXECUTION\n")
                    
                elif line == "2":
                    await server.broadcast_signal("POLICY_SUCCESS", "Manual success signal (Policy 1)")
                    print("✅ Sent POLICY_SUCCESS (for Policy 1)\n")
                    
                elif line == "3":
                    await server.broadcast_signal("NAV_COMPLETE", "Manual navigation complete signal")
                    print("🏁 Sent NAV_COMPLETE\n")
                    
                elif line == "4":
                    await server.broadcast_signal("ABORT", "Manual abort signal")
                    print("🛑 Sent ABORT\n")
                    
                elif line == "s":
                    print(f"\n📊 Server Status:")
                    print(f"   Host: {server.host}:{server.port}")
                    print(f"   Connected clients: {len(server.clients)}")
                    if server.clients:
                        for i, client in enumerate(server.clients, 1):
                            print(f"     {i}. {client.remote_address}")
                    print()
                    
                elif line == "q":
                    print("\n👋 Shutting down server...")
                    break
                    
                elif line:
                    print(f"❓ Unknown command: {line}")
                    print("   Use 1-4, s, or q\n")
                    
        except KeyboardInterrupt:
            print("\n\n👋 Shutting down server...")
            break
        except Exception as e:
            logger.error(f"Error in CLI: {e}")


async def main(host: str, port: int):
    """Main function to run the server."""
    server = SignalServer(host=host, port=port)
    
    # Start server
    await server.start_server()
    
    # Run interactive CLI
    try:
        await interactive_cli(server)
    finally:
        await server.stop_server()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Dummy WebSocket signal server for autonomous execution testing")
    parser.add_argument("--host", type=str, default="localhost", help="Server host (default: localhost)")
    parser.add_argument("--port", type=int, default=8765, help="Server port (default: 8765)")
    
    args = parser.parse_args()
    
    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
