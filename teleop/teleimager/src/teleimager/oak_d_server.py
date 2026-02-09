
import os
import argparse
import time
import threading
import signal
import functools
import cv2
import numpy as np
import zmq
import yaml
import platform
import queue
import asyncio
import json
import ssl
import fractions
from typing import Dict, Optional, Tuple, Any
from pathlib import Path

# depthai import
import depthai as dai

# webrtc dependencies
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.rtcrtpsender import RTCRtpSender
from aiortc.contrib.media import MediaRelay
from aiortc.codecs import h264
import av

import logging_mp
logging_mp.basic_config(level=logging_mp.INFO)
logger_mp = logging_mp.get_logger(__name__)

# ========================================================
# libx264 for Jetson (Patch h264 Encoder) - Copied from image_server.py
# ========================================================
def jetson_software_encode_frame(self, frame: av.VideoFrame, force_keyframe: bool):
    if self.codec and (frame.width != self.codec.width or frame.height != self.codec.height):
        self.codec = None

    if self.codec is None:
        try:
            self.codec = av.CodecContext.create("libx264", "w")
            self.codec.width = frame.width
            self.codec.height = frame.height
            self.codec.bit_rate = self.target_bitrate
            self.codec.pix_fmt = "yuv420p"
            self.codec.framerate = fractions.Fraction(30, 1)
            self.codec.time_base = fractions.Fraction(1, 30)
        
            self.codec.options = {
                "preset": "ultrafast",
                "tune": "zerolatency",
                "threads": "1",
                "g": "60",
            }
            self.frame_count = 0
            force_keyframe = True
        except Exception as e:
            logger_mp.error(f"[H264 Patch] Initialization failed: {e}")
            return

    if not force_keyframe and hasattr(self, "frame_count") and self.frame_count % 60 == 0:
        force_keyframe = True
    
    self.frame_count = self.frame_count + 1 if hasattr(self, "frame_count") else 1
    frame.pict_type = av.video.frame.PictureType.I if force_keyframe else av.video.frame.PictureType.NONE

    try:
        for packet in self.codec.encode(frame):
            data = bytes(packet)
            if data:
                yield from self._split_bitstream(data)
    except Exception as e:
        logger_mp.warning(f"[H264 Patch] Encode error: {e}")

h264.H264Encoder._encode_frame = jetson_software_encode_frame

# ========================================================
# Configuration and Constants
# ========================================================
# We define a hardcoded config that matches what image_client expects for a "head_camera"
# This mimics the structure served by ZMQ_Responser
DEFAULT_CAM_CONFIG = {
    'head_camera': {
        'enable_zmq': True,
        'zmq_port': 55555,
        'enable_webrtc': True,
        'webrtc_port': 60001,
        'image_shape': [720, 1280], # Height, Width for 720P
        'fps': 30,
        'binocular': False, # OAK-D has stereo but we are sending single RGB for now as requested
        'type': 'oak-d'
    },
    'left_wrist_camera': {'enable_zmq': False},
    'right_wrist_camera': {'enable_zmq': False}
}

# Certificate paths (Found in televuer directory)
module_dir = Path(__file__).resolve().parent.parent.parent # teleimager
televuer_dir = module_dir.parent

default_cert = televuer_dir / "cert.pem"
default_key = televuer_dir / "key.pem"
env_cert = os.getenv("XR_TELEOP_CERT")
env_key = os.getenv("XR_TELEOP_KEY")
user_config_dir = Path.home() / ".config" / "xr_teleoperate"
user_cert = user_config_dir / "cert.pem"
user_key = user_config_dir / "key.pem"
CERT_PEM_PATH = Path(env_cert or (user_cert if user_cert.exists() else default_cert))
KEY_PEM_PATH = Path(env_key or (user_key if user_key.exists() else default_key))
CERT_PEM_PATH = CERT_PEM_PATH.resolve()
KEY_PEM_PATH = KEY_PEM_PATH.resolve()


# ========================================================
# Embed HTML and JS directly (Copied from image_server.py)
# ========================================================
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>WebRTC Stream (OAK-D)</title>
    <style>
    body { 
        font-family: sans-serif; 
        background: #fff; 
        color: #000; 
        text-align: center; 
    }
    button { padding: 10px 20px; font-size: 16px; cursor: pointer; }
    video { width: 100%; max-width: 1280px; background: #000; margin-top: 10px; }
    
    h1 a {
        text-decoration: none;
        color: #000;
    }
    h1 a:hover {
        color: #555;
    }
    </style>
</head>
<body>
    <h1>
        <a href="#" target="_blank">
            XR Teleoperation OAK-D Stream
        </a>
    </h1>

    <button id="start" onclick="start()">Start</button>
    <button id="stop" style="display: none" onclick="stop()">Stop</button>
    
    <div id="media">
        <video id="video" autoplay playsinline muted></video>
        <audio id="audio" autoplay></audio>
    </div>
    
    <script src="client.js"></script>
</body>
</html>
"""

CLIENT_JS = """
var pc = null;

function negotiate() {
    pc.addTransceiver('video', { direction: 'recvonly' });
    return pc.createOffer().then((offer) => {
        return pc.setLocalDescription(offer);
    }).then(() => {
        return new Promise((resolve) => {
            if (pc.iceGatheringState === 'complete') {
                resolve();
            } else {
                const checkState = () => {
                    if (pc.iceGatheringState === 'complete') {
                        pc.removeEventListener('icegatheringstatechange', checkState);
                        resolve();
                    }
                };
                pc.addEventListener('icegatheringstatechange', checkState);
            }
        });
    }).then(() => {
        var offer = pc.localDescription;
        return fetch('/offer', {
            body: JSON.stringify({
                sdp: offer.sdp,
                type: offer.type,
            }),
            headers: {
                'Content-Type': 'application/json'
            },
            method: 'POST'
        });
    }).then((response) => {
        return response.json();
    }).then((answer) => {
        return pc.setRemoteDescription(answer);
    }).catch((e) => {
        alert(e);
    });
}

function start() {
    var config = {
        sdpSemantics: 'unified-plan'
    };

    pc = new RTCPeerConnection(config);

    pc.addEventListener('track', (evt) => {
        if (evt.track.kind == 'video') {
            document.getElementById('video').srcObject = evt.streams[0];
        } else {
            document.getElementById('audio').srcObject = evt.streams[0];
        }
    });

    document.getElementById('start').style.display = 'none';
    negotiate();
    document.getElementById('stop').style.display = 'inline-block';
}

function stop() {
    document.getElementById('stop').style.display = 'none';
    document.getElementById('start').style.display = 'inline-block';
    if (pc) {
        pc.close();
        pc = null;
    }
}
"""

# ========================================================
# Utility tools
# ========================================================
class TripleRingBuffer:
    def __init__(self):
        self.buffer = [None, None, None]
        self.write_index = 0
        self.latest_index = -1
        self.read_index = -1
        self.lock = threading.Lock()

    def write(self, data):
        with self.lock:
            self.buffer[self.write_index] = data
            self.latest_index = self.write_index
            self.write_index = (self.write_index + 1) % 3
            if self.write_index == self.read_index:
                self.write_index = (self.write_index + 1) % 3

    def read(self):
        with self.lock:
            if self.latest_index == -1:
                return None
            self.read_index = self.latest_index
        return self.buffer[self.read_index]

# ========================================================
# ZMQ Publish
# ========================================================
class ZMQ_PublisherThread(threading.Thread):
    def __init__(self, port: int, host: str = "0.0.0.0", context: Optional[zmq.Context] = None):
        super().__init__(daemon=True)
        self._port = port
        self._host = host
        self._context = context
        self._socket = None
        self._running = True
        self._queue = queue.Queue(maxsize=10)
        self._started = threading.Event()

    def send(self, data: Any) -> None:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            pass

    def stop(self) -> None:
        self._running = False
        self.join(timeout=1)

    def run(self) -> None:
        try:
            self._socket = self._context.socket(zmq.PUB)
            self._socket.setsockopt(zmq.SNDHWM, 1)
            self._socket.setsockopt(zmq.LINGER, 0)
            self._socket.bind(f"tcp://{self._host}:{self._port}")
            self._started.set()
            while self._running:
                try:
                    data = self._queue.get(timeout=0.1)
                    if data is None: break
                    self._socket.send(data, zmq.NOBLOCK)
                except queue.Empty:
                    continue
                except Exception:
                    pass
        except Exception as e:
            logger_mp.error(f"ZMQ Publisher Error: {e}")
        finally:
            if self._socket:
                self._socket.close()

    def wait_for_start(self, timeout: float = 1.0) -> bool:
        return self._started.wait(timeout=timeout)

class ZMQ_PublisherManager:
    _instance: Optional["ZMQ_PublisherManager"] = None
    _publisher_threads: Dict[Tuple[str, int], ZMQ_PublisherThread] = {}
    _lock = threading.Lock()
    _running = True

    def __init__(self):
        self._context = zmq.Context()

    @classmethod
    def get_instance(cls) -> "ZMQ_PublisherManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def publish(self, data: Any, port: int, host: str = "0.0.0.0") -> None:
        if not self._running: return
        key = (host, port)
        with self._lock:
            if key not in self._publisher_threads:
                t = ZMQ_PublisherThread(port, host, self._context)
                t.start()
                if not t.wait_for_start():
                    logger_mp.error("Failed to start ZMQ Publisher")
                    return
                self._publisher_threads[key] = t
            self._publisher_threads[key].send(data)

    def close(self) -> None:
        self._running = False
        with self._lock:
            for t in self._publisher_threads.values():
                t.stop()
            self._publisher_threads.clear()

# ========================================================
# WebRTC Publish (Copied/Adapted from image_server.py)
# ========================================================
class BGRArrayVideoStreamTrack(MediaStreamTrack):
    kind = "video"
    def __init__(self):
        super().__init__()
        self._queue = asyncio.Queue(maxsize=1)
        self._start_time = None
        self._pts = 0

    async def recv(self) -> av.VideoFrame:
        frame = await self._queue.get()
        return frame

    def push_frame(self, bgr_numpy: np.ndarray, loop: Optional[asyncio.AbstractEventLoop] = None):
        if bgr_numpy is None: return
        try:
            video_frame = av.VideoFrame.from_ndarray(bgr_numpy, format="bgr24")
            if self._start_time is None:
                self._start_time = time.time()
                self._pts = 0
            else:
                self._pts = int((time.time() - self._start_time) * 90000)
            video_frame.pts = self._pts
            video_frame.time_base = fractions.Fraction(1, 90000)
        except Exception:
            return

        target_loop = loop or asyncio.get_event_loop()
        if target_loop.is_closed(): return
        
        def _put():
            try:
                if self._queue.full():
                    self._queue.get_nowait()
                self._queue.put_nowait(video_frame)
            except Exception: pass
        
        target_loop.call_soon_threadsafe(_put)

class WebRTC_PublisherThread(threading.Thread):
    def __init__(self, port: int, host: str = "0.0.0.0", codec_pref: str = None):
        super().__init__(daemon=True)
        self._host = host
        self._port = port
        self._codec_pref = codec_pref
        self._app = web.Application()
        self._pcs = set()
        self._start_event = threading.Event()
        self._stop_event = threading.Event()
        self._frame_queue = queue.Queue(maxsize=1)
        self._bgr_track = None
        self._relay = None
        self._loop = None

        self._app.router.add_get("/", self._index)
        self._app.router.add_get("/client.js", self._javascript)
        self._app.router.add_post("/offer", self._offer)
        
        self._app.router.add_options("/", self._options)
        self._app.router.add_options("/client.js", self._options)
        self._app.router.add_options("/offer", self._options)

    async def _index(self, request):
        return web.Response(content_type="text/html", text=INDEX_HTML)

    async def _javascript(self, request):
        return web.Response(content_type="application/javascript", text=CLIENT_JS)

    async def _options(self, request):
        return web.Response(
            status=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }
        )

    async def _offer(self, request):
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        pc = RTCPeerConnection()
        self._pcs.add(pc)

        if self._bgr_track and self._relay:
            relayed_track = self._relay.subscribe(self._bgr_track)
            transceiver = pc.addTransceiver(relayed_track, direction="sendonly")
            
            # Codec Handling
            capabilities = RTCRtpSender.getCapabilities("video")
            pref = (self._codec_pref or "h264").lower()
            
            if pref == "h264":
                h264_codecs = [c for c in capabilities.codecs if c.mimeType == "video/H264"]
                if h264_codecs:
                    transceiver.setCodecPreferences(h264_codecs)
                    logger_mp.info(f"[WebRTC] Preferred H264 for port:{self._port}")
                else:
                    logger_mp.warning(f"[WebRTC] H264 preferred but not found.")
            elif pref == "vp8":
                vp8_codecs = [c for c in capabilities.codecs if c.mimeType == "video/VP8"]
                if vp8_codecs:
                    transceiver.setCodecPreferences(vp8_codecs)
                    logger_mp.info(f"[WebRTC] Preferred VP8 for port:{self._port}")
                else:
                    logger_mp.warning(f"[WebRTC] VP8 preferred but not found.")
        
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if pc.connectionState in ["failed", "closed"]:
                await self._cleanup_pc(pc)

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}),
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }
        )

    async def _cleanup_pc(self, pc):
        self._pcs.discard(pc)
        try: await pc.close()
        except: pass

    def wait_for_start(self, timeout=1.0):
        return self._start_event.wait(timeout=timeout)

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        async def _main():
            runner = web.AppRunner(self._app)
            await runner.setup()
            self._bgr_track = BGRArrayVideoStreamTrack()
            self._relay = MediaRelay()
            
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(CERT_PEM_PATH, KEY_PEM_PATH)
            site = web.TCPSite(runner, self._host, self._port, ssl_context=ssl_context)
            await site.start()
            self._start_event.set()

            while not self._stop_event.is_set():
                if not self._frame_queue.empty():
                    frame = self._frame_queue.get_nowait()
                    self._bgr_track.push_frame(frame, loop=self._loop)
                await asyncio.sleep(0.005)

        try:
            self._loop.run_until_complete(_main())
        finally:
            self._loop.close()

    def send(self, data: np.ndarray):
        if not self._frame_queue.full():
            self._frame_queue.put(data)
        else:
            try:
                self._frame_queue.get_nowait()
                self._frame_queue.put(data)
            except: pass

    def stop(self):
        self._stop_event.set()
        self.join(timeout=1.0)


class WebRTC_PublisherManager:
    _instance: Optional["WebRTC_PublisherManager"] = None
    _publisher_threads: Dict[Tuple[str, int], WebRTC_PublisherThread] = {}
    _lock = threading.Lock()
    _running = True

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def publish(self, data, port, host="0.0.0.0", codec_pref=None):
        if not self._running: return
        key = (host, port)
        with self._lock:
            if key not in self._publisher_threads:
                t = WebRTC_PublisherThread(port, host, codec_pref)
                t.start()
                if not t.wait_for_start(5.0):
                    return
                self._publisher_threads[key] = t
            self._publisher_threads[key].send(data)

    def close(self):
        self._running = False
        with self._lock:
            for t in self._publisher_threads.values():
                t.stop()
            self._publisher_threads.clear()

# ========================================================
# ZMQ Responser (Config Server)
# ========================================================
class ZMQ_Responser:
    def __init__(self, cam_config, host="0.0.0.0", port=60000):
        self._cam_config = cam_config
        self._host = host
        self._port = port
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REP)
        self._socket.bind(f"tcp://{self._host}:{self._port}")
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        poller = zmq.Poller()
        poller.register(self._socket, zmq.POLLIN)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=200))
                if self._socket in socks:
                    self._socket.recv()
                    self._socket.send_json(self._cam_config)
            except Exception:
                pass

    def stop(self):
        self._running = False
        self._thread.join(timeout=1)
        self._socket.close()
        self._context.term()

# ========================================================
# OAK-D Camera Class
# ========================================================
class OakDCamera:
    def __init__(self, fps=30):
        self._fps = fps
        self._pipeline = dai.Pipeline()
        
        # Color Camera Setup
        cam_rgb = self._pipeline.create(dai.node.ColorCamera)
        cam_rgb.setBoardSocket(dai.CameraBoardSocket.CAM_A)
        cam_rgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_720_P) # 1280x720
        cam_rgb.setFps(self._fps)
        cam_rgb.setInterleaved(False)
        cam_rgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        
        # Create output
        xout_rgb = self._pipeline.create(dai.node.XLinkOut)
        xout_rgb.setStreamName("rgb")
        cam_rgb.video.link(xout_rgb.input)
        
        self._device = None
        self._output_queue = None
        self._ready = threading.Event()
        self._running = False

    def start(self):
        try:
            self._device = dai.Device(self._pipeline)
            
            # Log USB Speed
            usb_speed = self._device.getUsbSpeed()
            logger_mp.info(f"[OakDCamera] Connected via {usb_speed}")
            if usb_speed == dai.UsbSpeed.HIGH or usb_speed == dai.UsbSpeed.FULL:
                logger_mp.warning("[OakDCamera] USB2 detected! 800P@30FPS (Uncompressed) exceeds USB2 bandwidth. Crash likely.")
                logger_mp.warning("Recommendation: Use a USB3 cable/port or lower FPS.")

            self._output_queue = self._device.getOutputQueue(name="rgb", maxSize=4, blocking=False)
            self._running = True
            logger_mp.info("[OakDCamera] Pipeline started. Resolution: 1280x800 @ 30FPS")
        except Exception as e:
            logger_mp.error(f"[OakDCamera] Failed to start device: {e}")
            raise

    def get_frame(self):
        if not self._running or self._output_queue is None:
            return None
        
        try:
            # Try to get frame, non-blocking if possible or short time
            # Since we want 30ps, we can block a bit
            frame_packet = self._output_queue.tryGet()
            if frame_packet is not None:
                return frame_packet.getCvFrame()
            return None
        except Exception as e:
            return None

    def release(self):
        self._running = False
        if self._device:
            self._device.close()
            self._device = None
        logger_mp.info("[OakDCamera] Released.")

# ========================================================
# OAK-D Server
# ========================================================
class OakDServer:
    def __init__(self):
        self._cam_config = DEFAULT_CAM_CONFIG
        self._stop_event = threading.Event()
        
        # Setup Server Managers
        self._zmq_pub = ZMQ_PublisherManager.get_instance()
        self._webrtc_pub = WebRTC_PublisherManager.get_instance()
        self._responser = ZMQ_Responser(self._cam_config)
        
        # Camera
        self._camera = None

    def start(self):
        try:
            self._camera = OakDCamera()
            self._camera.start()
        except Exception:
            logger_mp.error("Failed to initialize OAK-D camera.")
            return

        # Start Publisher Thread
        self._pub_thread = threading.Thread(target=self._run_publish_loop, daemon=True)
        self._pub_thread.start()
        logger_mp.info("OAK-D Server Started.")

    def _run_publish_loop(self):
        cam_cfg = self._cam_config['head_camera']
        zmq_port = cam_cfg['zmq_port']
        webrtc_port = cam_cfg['webrtc_port']
        
        while not self._stop_event.is_set():
            frame = self._camera.get_frame()
            if frame is not None:
                # WebRTC
                self._webrtc_pub.publish(frame, webrtc_port)
                
                # ZMQ (JPEG encoded)
                ret, jpg = cv2.imencode(".jpg", frame)
                if ret:
                    self._zmq_pub.publish(jpg.tobytes(), zmq_port)
            else:
                time.sleep(0.001)

    def wait(self):
        try:
            while not self._stop_event.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self._stop_event.set()
        self._responser.stop()
        self._zmq_pub.close()
        self._webrtc_pub.close()
        if self._camera:
            self._camera.release()
        logger_mp.info("OAK-D Server Stopped.")

def main():
    parser = argparse.ArgumentParser(description="OAK-D Image Server")
    args = parser.parse_args()

    server = OakDServer()
    server.start()
    server.wait()

if __name__ == "__main__":
    main()
