import zmq
import cv2
import numpy as np
import argparse
import time

def main():
    parser = argparse.ArgumentParser(description="Simple OAK-D Test Client")
    parser.add_argument("--host", default="127.0.0.1", help="Server IP address")
    parser.add_argument("--port", type=int, default=55555, help="ZMQ Port (default: 55555)")
    args = parser.parse_args()

    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.setsockopt(zmq.RCVHWM, 1)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt_string(zmq.SUBSCRIBE, "")
    
    # Connect
    connection_str = f"tcp://{args.host}:{args.port}"
    print(f"Connecting to {connection_str}...")
    socket.connect(connection_str)
    
    print("Waiting for frames... (Press 'q' to quit)")
    
    fps_start = time.time()
    frame_count = 0
    fps = 0

    while True:
        try:
            # Receive all parts if multipart, but here we expect single part
            # Use NOBLOCK to check for keyboard interrupt more easily if needed,
            # or just blocking recv is fine for a simple script.
            msg = socket.recv()
            
            # Decode
            np_arr = np.frombuffer(msg, dtype=np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            
            if img is not None:
                # Calculate FPS
                frame_count += 1
                now = time.time()
                if now - fps_start >= 1.0:
                    fps = frame_count / (now - fps_start)
                    frame_count = 0
                    fps_start = now
                
                # Draw FPS
                cv2.putText(img, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                
                cv2.imshow("OAK-D Stream", img)
            else:
                print("Received empty or invalid frame")

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            break
            
    cv2.destroyAllWindows()
    socket.close()
    context.term()

if __name__ == "__main__":
    main()
