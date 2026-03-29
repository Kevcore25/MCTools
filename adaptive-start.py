#!/usr/bin/env python3

VERSION = '2.0.0'

"""
Minecraft Adaptive Server Starter (MASS)!

This is a script/program that will start a Minecraft server if a player tries to join,
or stops a Minecraft server if no players are online within a set period.

Now has RAM/SWAP requirements to start!

HOW TO USE:
Just put this file in an already started Minecraft server directory and it'll 
automatically adjust its config values!
Run the program and then ensure the config is accurate and suited for your needs.
Then, simply run this program forever and it'll automatically start the server!
"""

"""
Version updates:

2.0:
- Improved killing process: now has RCON and PID killing systems and better auto stop stability
- AutoConfig (automatically configs the file based on server.properties and start.sh files)
- Memory requirements (needs X amount of memory to start)
- Config reloader detection 
- Startup timeout
- Auto-updater

1.0:
- Created this script
"""


import asyncio
import base64
import os
import json
import logging
import requests
import struct
import time
from pathlib import Path
import psutil


log = logging.getLogger("ServerStarter")

CONFIG_FILENAME = "mass-config.json"

STARTUP_TIMES_FILE = "startup_times.json"
MAX_STORED_TIMES = 10

"""
DEFAULT CONFIG

Note that below is the default config. 
When the program starts, a config.json will be made and you can change things from there.

TL;DR Don't change the default config below!!
"""
DEFAULT_CONFIG = {
    # Proxy ports
    "listen_host": "0.0.0.0",
    "listen_port": 25565,
    "server_port": None, # should be None like 99% of the time - it auto detects based on server.properties
    "server_dir": ".",

    # Start command (e.g. sh start.sh). You probably shouldn't use nohup here and rather nohup this python script instead
    "start_command": "java -Xmx4G -server -jar server.jar nogui",

    # Amount of RAM/SWAP required (in GB) to start the program - if it is too low then the server won't start
    # If set to None/null/0 then this is ignored
    "ram_required": 4.5,
    "swap_required": None,
    # Message to kick if no memory
    "kick_message_no_memory": "\u00A74The physical server does not have enough memory to wake the Minecraft server!\n\n\u00A74This issue should be reported to the administrators.",

    # Messages for starting/offline
    # {{ESTIMATED_TIME_REMAINING}} and {{ESTIMATED_TIME}} are available placeholders
    "kick_message": "\u00A7eThis server is waking up...\u00A7r\n\n\u00A7bEstimated time remaining: {{ESTIMATED_TIME_REMAINING}}",
    "offline_motd": "\u00A74This server is sleeping.\u00A7r\n\u00A7aJoin it to wake it! ({{ESTIMATED_TIME}})",
    "starting_motd": "\u00A7eThis server is waking up...\u00A7r\n\u00A7bEstimated time remaining: {{ESTIMATED_TIME_REMAINING}}",
    "offline_version_text": "\u00a74Sleeping",
    "starting_version_text": "\u00a7eWaking...",

    # Duration of empty players (in min) before the stop cmd is ran
    "auto_stop_empty_minutes": 2,

    # Max time (in seconds) to wait for the server to start before killing it. None = no timeout
    "startup_timeout": 300,

    # Polling intervals - default should be fine
    "poll_interval": 0.5,
    "auto_stop_poll_interval": 3,

    # Default icons made with basic shapes in Google Drawings
    "offline_icon": None,
    "starting_icon": None,

    # Whether the starter should check for updates and download them automatically
    # For security/stabiliy this should be disabled but this is enabled by default as the project is pretty small and in development
    "auto_update": True,
    "auto_update_urls": [
        'https://raw.githubusercontent.com/Kevcore25/MCTools/refs/heads/main/adaptive-start.py', # Official GitHub server
        'https://kaf.kcservers.ca/releases/mass.py' # Private server which may receive more frequent updates - can be removed 
    ]
}



def compareVersion(version1: str, version2: str) -> int:
    v1 = list(map(int, version1.split('.')))
    v2 = list(map(int, version2.split('.')))
    n = max(len(v1), len(v2))
    
    for i in range(n):
        num1 = v1[i] if i < len(v1) else 0
        num2 = v2[i] if i < len(v2) else 0
        if num1 < num2:
            return False
        if num1 > num2:
            return True
    return False

def updater(config: dict[str, list[str]]):

    log.info("Checking for updates...")

    for i, url in enumerate(config["auto_update_urls"], start=1):
        try:
            r = requests.get(url, timeout=1)

            # Check status
            if r.status_code != 200:
                raise Exception(f"Returned status code {r.status_code}")
            
            # Get version
            version = r.text.splitlines()[0].split('=', 1)[1].strip().strip("'").strip('"')
            log.info(f"Found server #{i} with version {version} (Current version {VERSION})")

            if compareVersion(version, VERSION):
                with open(os.path.abspath(__file__), 'wb') as f:
                    f.write(r.content)

                log.info("Current Minecraft Adaptive Server Starter is updated!")
                break
        except IndexError:
            log.error(f"Unable to fetch server #{i} due to invalid format")
        except (ConnectionError, requests.ConnectTimeout):
            log.error(f"Unable to fetch server #{i} due to a connection error")
        except Exception as e:
            log.error(f"Unable to fetch server #{i}: {e}")
    else:
        log.info("The updater did not update the file")

def create_config(config_path: str = CONFIG_FILENAME):
    config = DEFAULT_CONFIG.copy()

    # Server.properties
    if Path("server.properties").exists():
        with open("server.properties", 'r') as f:
            props = f.readlines()

        # Change server-port to +1 if it exists and set the proxy port to it instead
        for i, ln in enumerate(props):
            if ln.startswith('#') or ln.isspace() or ln == '': 
                continue
            
            k, v = ln.rstrip('\n').split('=')

            if k == "server-port":
                v = int(v)
                config["listen_port"] = v
                props[i] = f"server-port={v+1}\n"
                with open("server.properties", 'w') as f:
                    f.writelines(props)
                log.info(f"The server port is switched from {v} to {v+1} and the proxy server's port is set to {v}")
                break

    # bash start.sh
    if Path("start.sh").exists():
        config["start_command"] = "bash start.sh"


    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    log.info(f"Created default config at {config_path}")
    return config
    
# =============================================================================
# Protocol Primitives
# =============================================================================

def encode_varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 32
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            break
    return bytes(result)


async def read_varint(reader: asyncio.StreamReader) -> int:
    result = 0
    for i in range(5):
        byte = await reader.readexactly(1)
        b = byte[0]
        result |= (b & 0x7F) << (7 * i)
        if not (b & 0x80):
            break
    if result > 0x7FFFFFFF:
        result -= 1 << 32
    return result


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    result = 0
    for i in range(5):
        b = data[offset]
        result |= (b & 0x7F) << (7 * i)
        offset += 1
        if not (b & 0x80):
            break
    if result > 0x7FFFFFFF:
        result -= 1 << 32
    return result, offset


def encode_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return encode_varint(len(encoded)) + encoded


def decode_string(data: bytes, offset: int = 0) -> tuple[str, int]:
    length, offset = decode_varint(data, offset)
    s = data[offset : offset + length].decode("utf-8")
    return s, offset + length


def encode_ushort(value: int) -> bytes:
    return struct.pack(">H", value)


def make_packet(packet_id: int, payload: bytes = b"") -> bytes:
    id_bytes = encode_varint(packet_id)
    length = len(id_bytes) + len(payload)
    return encode_varint(length) + id_bytes + payload


async def read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    length = await read_varint(reader)
    if length <= 0 or length > 2**21:
        raise ValueError(f"Invalid packet length: {length}")
    data = await reader.readexactly(length)
    packet_id, offset = decode_varint(data)
    return packet_id, data[offset:]

async def rcon_send(host: str, port: int, password: str, command: str) -> str | None:
    """Connect to RCON, authenticate, send a command, and return the response."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5
        )
    except (OSError, asyncio.TimeoutError):
        return None

    request_id = 1

    def _pack(req_id: int, ptype: int, payload: str) -> bytes:
        body = struct.pack("<ii", req_id, ptype) + payload.encode("utf-8") + b"\x00\x00"
        return struct.pack("<i", len(body)) + body

    async def _read_response() -> tuple[int, int, str]:
        raw_len = await reader.readexactly(4)
        length = struct.unpack("<i", raw_len)[0]
        data = await reader.readexactly(length)
        req_id, ptype = struct.unpack("<ii", data[:8])
        body = data[8:-2].decode("utf-8", errors="replace")  # strip two null bytes
        return req_id, ptype, body

    try:
        # Authenticate (type 3)
        writer.write(_pack(request_id, 3, password))
        await writer.drain()
        resp_id, _, _ = await asyncio.wait_for(_read_response(), timeout=5)
        if resp_id == -1:
            log.warning("RCON authentication failed (wrong password)")
            writer.close()
            return None

        # Send command (type 2)
        request_id += 1
        writer.write(_pack(request_id, 2, command))
        await writer.drain()
        _, _, body = await asyncio.wait_for(_read_response(), timeout=5)
        writer.close()
        await writer.wait_closed()
        return body
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
        log.warning(f"RCON error: {e}")
        try:
            writer.close()
        except Exception:
            pass
        return None


def load_config(path: str = CONFIG_FILENAME) -> dict:
    config = DEFAULT_CONFIG.copy()
    config_path = Path(path)

    if config_path.exists():
        with open(config_path) as f:
            user_config = json.load(f)
        config.update({k: v for k, v in user_config.items() if v is not None})
    else:
        config = create_config()

    # Read server port from server.properties if not overridden
    if config.get("server_port") is None:
        props_path = Path(config["server_dir"]) / "server.properties"
        config["server_port"] = 25565
        if props_path.exists():
            with open(props_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("server-port="):
                        config["server_port"] = int(line.split("=", 1)[1].strip())
                        break

    # Warn about port conflicts
    if config["server_port"] == config["listen_port"]:
        log.warning(
            f"Proxy listen_port ({config['listen_port']}) matches server_port "
            f"({config['server_port']}). They must be different! "
            f"Change one in {CONFIG_FILENAME} or server.properties."
        )

    # Read RCON settings from server.properties
    config["_rcon_enabled"] = False
    config["_rcon_port"] = 25575
    config["_rcon_password"] = ""
    props_path = Path(config["server_dir"]) / "server.properties"
    if props_path.exists():
        with open(props_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("enable-rcon=true"):
                    config["_rcon_enabled"] = True
                elif line.startswith("rcon.port="):
                    config["_rcon_port"] = int(line.split("=", 1)[1].strip())
                elif line.startswith("rcon.password="):
                    config["_rcon_password"] = line.split("=", 1)[1].strip()
    if config["_rcon_enabled"]:
        log.info(f"RCON detected on port {config['_rcon_port']} (will use as stop fallback)")

    # Load icons as base64 data URIs
    for key in ("offline_icon", "starting_icon"):
        icon_path = config.get(key)
        if icon_path:
            p = Path(config["server_dir"]) / icon_path
            if p.exists():
                data = base64.b64encode(p.read_bytes()).decode("ascii")
                config[f"_{key}_data"] = f"data:image/png;base64,{data}"
                log.info(f"Loaded {key}: {p}")
            else:
                log.warning(f"{key} file not found: {p}")
                config[f"_{key}_data"] = None
        else:
            config[f"_{key}_data"] = None

    return config


def load_startup_times(server_dir: str) -> list[float]:
    path = Path(server_dir) / STARTUP_TIMES_FILE
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return [float(t) for t in data]
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def save_startup_times(server_dir: str, times: list[float]):
    path = Path(server_dir) / STARTUP_TIMES_FILE
    with open(path, "w") as f:
        json.dump(times[-MAX_STORED_TIMES:], f)


def format_duration(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    secs = seconds % 60
    if secs == 0:
        return f"{minutes}m"
    return f"{minutes}m {secs}s"


def get_avg_startup(server_dir: str) -> float | None:
    times = load_startup_times(server_dir)
    if not times:
        return None
    else:
        # Give slightly more priority to last run
        times += ([times[-1]] * 3)
    return sum(times) / len(times)


def apply_placeholders(text: str, server_dir: str, start_time: float | None = None) -> str:
    """Replace {{ESTIMATED_TIME}} and {{ESTIMATED_TIME_REMAINING}} in text."""
    if "{{ESTIMATED_TIME}}" not in text and "{{ESTIMATED_TIME_REMAINING}}" not in text:
        return text
    avg = get_avg_startup(server_dir)
    if avg is None:
        text = text.replace("{{ESTIMATED_TIME}}", "unknown")
        text = text.replace("{{ESTIMATED_TIME_REMAINING}}", "unknown")
        return text
    text = text.replace("{{ESTIMATED_TIME}}", format_duration(avg))
    if start_time is not None:
        remaining = max(0, avg - (time.monotonic() - start_time))
    else:
        remaining = avg

    text = text.replace("{{ESTIMATED_TIME_REMAINING}}", format_duration(remaining))
    return text

def find_pid_by_port(port: int) -> int | None:
    """Find the PID of the process listening on the given port."""
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status == "LISTEN" and conn.laddr.port == port:
            return conn.pid
    return None

class ServerManager:
    def __init__(self, config: dict):
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._starting = False
        self._start_time: float | None = None
        self._ready_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._auto_stop_task: asyncio.Task | None = None

    async def status_ping(self) -> dict | None:
        """Ping the server and return the parsed status JSON, or None on failure."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", self.config["server_port"]),
                timeout=2,
            )
            handshake = (
                encode_varint(767)
                + encode_string("127.0.0.1")
                + encode_ushort(self.config["server_port"])
                + encode_varint(1)
            )
            writer.write(make_packet(0x00, handshake))
            writer.write(make_packet(0x00))  # Status Request
            await writer.drain()

            packet_id, data = await asyncio.wait_for(read_packet(reader), timeout=3)
            writer.close()
            await writer.wait_closed()
            if packet_id == 0x00:
                json_str, _ = decode_string(data)
                return json.loads(json_str)
            return None
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, Exception):
            return None

    async def is_running(self) -> bool:
        """Check if the real Minecraft server is accepting connections."""
        return (await self.status_ping()) is not None

    async def get_online_count(self) -> int | None:
        """Return the number of online players, or None if server is unreachable."""
        status = await self.status_ping()
        if status is None:
            return None
        try:
            return status["players"]["online"]
        except (KeyError, TypeError):
            return None

    async def trigger_start(self):
        """Start the server process if not already started. Non-blocking."""
        async with self._lock:
            if self._starting or await self.is_running():
                return
            self._starting = True
            self._start_time = time.monotonic()
            self._ready_event.clear()
            log.info(f"Starting server: {self.config['start_command']}")
            self._process = await asyncio.create_subprocess_shell(
                self.config["start_command"],
                cwd=self.config["server_dir"],
                stdin=asyncio.subprocess.PIPE,
                stdout=None,
                stderr=None,
            )
            asyncio.create_task(self.poll_until_ready())

    async def send_command(self, command: str):
        """Send a command to the server's stdin."""
        if self._process and self._process.stdin and self._process.returncode is None:
            try:
                self._process.stdin.write((command + "\n").encode())
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    async def _try_rcon_stop(self) -> bool:
        """Attempt to stop the server via RCON. Returns True if RCON command was sent."""
        if not self.config.get("_rcon_enabled"):
            return False
        log.info(f"Attempting RCON stop on port {self.config['_rcon_port']}...")
        result = await rcon_send(
            "127.0.0.1",
            self.config["_rcon_port"],
            self.config["_rcon_password"],
            "stop",
        )
        if result is None:
            log.warning("RCON stop failed (connection or auth error).")
            return False
        return True

    async def _wait_for_process(self, timeout: int = 30) -> bool:
        """Wait for the process to exit. Returns True if it exited."""
        if self._process is None or self._process.returncode is not None:
            return True
        try:
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def stop_server(self):
        """Stop the server: stdin -> RCON fallback -> kill."""
        has_process = self._process is not None and self._process.returncode is None

        # Attempt 1: stdin which is supported on vanilla servers
        if has_process:
            log.info("Sending 'stop' to server via stdin...")
            await self.send_command("stop")
            if await self._wait_for_process(30):
                log.info("Server stopped via stdin.")
                self._process = None
                self._ready_event.clear()
                return
            log.warning("Server did not stop via stdin within 30s.")

        # Attempt 2: RCON (works even without a process handle)
        # Typically this is used for modded servers but needs RCON enabled -> less secure
        if await self._try_rcon_stop():
            if has_process:
                if await self._wait_for_process(30):
                    log.info("Server stopped via RCON.")
                    self._process = None
                    self._ready_event.clear()
                    return
                log.warning("Server did not stop via RCON within 30s.")
            else:
                # No process handle. Wait a bit then check if server is gone
                log.info("No process handle, waiting for RCON stop to take effect...")
                await asyncio.sleep(10)
                if not await self.is_running():
                    log.info("Server stopped via RCON.")
                    self._process = None
                    self._ready_event.clear()
                    return
                log.warning("Server still running after RCON stop.")

        # Last resort: kill
        # Try the subprocess handle first, then find by port via psutil
        if has_process:
            log.warning("Killing server process via subprocess handle.")
            self._process.kill()
            await self._process.wait()
        else:
            pid = find_pid_by_port(self.config["server_port"])
            if pid:
                log.warning(f"Killing server process (PID {pid}) found on port {self.config['server_port']}.")
                try:
                    proc = psutil.Process(pid)
                    proc.terminate()
                    proc.wait(timeout=10)
                    log.info(f"Process {pid} terminated.")
                except psutil.TimeoutExpired:
                    log.warning(f"Process {pid} did not terminate, sending SIGKILL.")
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    log.error(f"Failed to kill PID {pid}: {e}")
            else:
                log.error("Cannot stop server: no process handle, RCON failed, and no PID found on port.")

        self._process = None
        self._ready_event.clear()

    async def poll_until_ready(self):
        timeout = self.config.get("startup_timeout")
        while not self._ready_event.is_set():
            await asyncio.sleep(self.config["poll_interval"])

            # Check startup timeout
            if timeout and self._start_time is not None:
                elapsed = time.monotonic() - self._start_time
                if elapsed >= timeout:
                    log.error(f"Server did not start within {format_duration(timeout)}, killing process.")
                    self._starting = False
                    self._start_time = None
                    await self.stop_server()
                    return

            if await self.is_running():
                # Record startup duration
                if self._start_time is not None:
                    duration = time.monotonic() - self._start_time
                    log.info(f"Server is ready! (took {format_duration(duration)})")
                    times = load_startup_times(self.config["server_dir"])
                    times.append(duration)
                    save_startup_times(self.config["server_dir"], times)
                    self._start_time = None
                else:
                    log.info("Server is ready!")
                self._starting = False
                self._ready_event.set()
                # Start auto-stop monitor
                if self._auto_stop_task is None or self._auto_stop_task.done():
                    self._auto_stop_task = asyncio.create_task(self.auto_stop_monitor())
                return

    async def auto_stop_monitor(self):
        empty_minutes = self.config.get("auto_stop_empty_minutes", 10)
        poll_interval = self.config.get("auto_stop_poll_interval", 30)
        empty_since: float | None = None

        log.info(f"Auto-stop monitor active: will stop after {empty_minutes}m")

        while True:
            await asyncio.sleep(poll_interval)

            # If server is no longer running (crashed or stopped externally), exit monitor
            count = await self.get_online_count()
            if count is None:
                log.info("Auto-stop monitor: server no longer reachable, retrying in 30s.")
                self._ready_event.clear()
                self._process = None
                
                await asyncio.sleep(30)
                continue

            if count == 0:
                if empty_since is None:
                    empty_since = time.monotonic()
                    log.info("Auto-stop monitor: server is empty, starting countdown.")
                elapsed = (time.monotonic() - empty_since) / 60.0
                if elapsed >= empty_minutes:
                    log.info(f"Server has been empty for {elapsed:.1f}m, stopping.")
                    await self.stop_server()
                    return
            else:
                if empty_since is not None:
                    log.info(f"Auto-stop monitor: {count} player(s) online, resetting countdown.")
                empty_since = None


async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    config: dict,
    server_mgr: ServerManager,
):
    addr = writer.get_extra_info("peername")
    try:
        packet_id, handshake_data = await asyncio.wait_for(read_packet(reader), timeout=10)
        if packet_id != 0x00:
            return

        protocol_version, offset = decode_varint(handshake_data)
        _server_address, offset = decode_string(handshake_data, offset)
        _server_port = struct.unpack(">H", handshake_data[offset : offset + 2])[0]
        offset += 2
        next_state, offset = decode_varint(handshake_data, offset)

        handshake_packet = make_packet(0x00, handshake_data)

        if next_state == 1:
            await handle_status(reader, writer, handshake_packet, config, server_mgr)
        elif next_state == 2:
            await handle_login(reader, writer, handshake_packet, protocol_version, config, server_mgr)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, OSError) as e:
        log.debug(f"Connection {addr} closed: {e}")
    except Exception as e:
        log.error(f"Error handling {addr}: {e}", exc_info=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def handle_status(reader, writer, handshake_packet, config, server_mgr):
    if await server_mgr.is_running():
        # Proxy the status request to the real server
        try:
            srv_reader, srv_writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", config["server_port"]), timeout=3
            )
        except (OSError, asyncio.TimeoutError):
            return

        srv_writer.write(handshake_packet)
        await srv_writer.drain()
        await proxy_relay(reader, writer, srv_reader, srv_writer)
    else:
        # Respond with our own status
        packet_id, _ = await asyncio.wait_for(read_packet(reader), timeout=5)
        if packet_id != 0x00:
            return

        is_starting = server_mgr._starting
        motd = apply_placeholders(
            config["starting_motd"] if is_starting else config["offline_motd"],
            config["server_dir"], server_mgr._start_time,
        )
        version_text = apply_placeholders(
            config["starting_version_text"] if is_starting else config["offline_version_text"],
            config["server_dir"], server_mgr._start_time,
        )
        favicon = config["_starting_icon_data"] if is_starting else config["_offline_icon_data"]
        status = {
            "version": {"name": version_text, "protocol": -1},
            "players": {"max": 0, "online": 0},
            "description": {"text": motd},
        }
        if favicon:
            status["favicon"] = favicon
        status_json = json.dumps(status)
        writer.write(make_packet(0x00, encode_string(status_json)))
        await writer.drain()

        # Ping/pong
        try:
            packet_id, ping_data = await asyncio.wait_for(read_packet(reader), timeout=5)
            if packet_id == 0x01:
                writer.write(make_packet(0x01, ping_data))
                await writer.drain()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass

async def handle_login(reader, writer, handshake_packet, protocol_version, config, server_mgr: ServerManager):
    packet_id, login_data = await asyncio.wait_for(read_packet(reader), timeout=10)
    if packet_id != 0x00:
        return

    login_start_packet = make_packet(0x00, login_data)

    # Parse player name
    player_name, _ = decode_string(login_data)
    log.info(f"Player {player_name} connecting (protocol {protocol_version})")

    # Proxy/redirect if it is already running
    if await server_mgr.is_running():
        return await proxy_to_server(reader, writer, handshake_packet, login_start_packet, config)
        
    # Check RAM
    ram = psutil.virtual_memory().available /  (1024 ** 3)
    swap = psutil.swap_memory().free /  (1024 ** 3)


    if (
        (config["ram_required"] is not None and config["ram_required"] > ram) or
        (config["swap_required"] is not None and config["swap_required"] > swap)
    ):
        log.error(f"Server does not have enough memory:\n\tRAM: {config['ram_required']} GB needed, {ram:.2f} GB available\n\tSWAP: {config['swap_required']} GB needed, {swap:.2f} GB free")
        await send_disconnect_login(writer, config["kick_message_no_memory"])
        return

    await server_mgr.trigger_start()
    kick_msg = apply_placeholders(config["kick_message"], config["server_dir"], server_mgr._start_time)
    await send_disconnect_login(writer, kick_msg)


async def send_disconnect_login(writer: asyncio.StreamWriter, message: str):
    """Send a disconnect packet in the Login state"""
    disconnect_json = json.dumps({"text": message})
    writer.write(make_packet(0x00, encode_string(disconnect_json)))
    await writer.drain()


async def proxy_to_server(client_reader, client_writer, handshake_packet, login_start_packet, config):
    try:
        srv_reader, srv_writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", config["server_port"]), timeout=5
        )
    except (OSError, asyncio.TimeoutError):
        await send_disconnect_login(client_writer, "\u00a7cServer is not available")
        return

    srv_writer.write(handshake_packet)
    srv_writer.write(login_start_packet)
    await srv_writer.drain()

    await proxy_relay(client_reader, client_writer, srv_reader, srv_writer)


async def proxy_relay(c_reader, c_writer, s_reader, s_writer):
    """Bidirectional byte relay between two connections."""

    async def relay(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
        try:
            while True:
                data = await src.read(8192)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                dst.close()
            except Exception:
                pass

    t1 = asyncio.create_task(relay(c_reader, s_writer))
    t2 = asyncio.create_task(relay(s_reader, c_writer))
    _done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()


async def watch_config(config: dict, path: str = CONFIG_FILENAME):
    """Reload config in-place when the file changes on disk."""
    config_path = Path(path)
    last_mtime = config_path.stat().st_mtime if config_path.exists() else 0

    while True:
        await asyncio.sleep(5)
        try:
            current_mtime = config_path.stat().st_mtime
        except OSError:
            continue
        if current_mtime != last_mtime:
            last_mtime = current_mtime
            try:
                new_config = load_config(path)
                # Preserve keys that shouldn't change at runtime
                new_config.pop("listen_host", None)
                new_config.pop("listen_port", None)
                config.update(new_config)
                log.info("Config reloaded.")
            except Exception as e:
                log.warning(f"Failed to reload config: {e}")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [Server starter/%(levelname)s]: %(message)s",
        datefmt="%H:%M:%S",
    )


    config = load_config()
    server_mgr = ServerManager(config)

    updater(config)

    log.info(f"Proxy listening on {config['listen_host']}:{config['listen_port']}")
    log.info(f"Server (redirect) port: {config['server_port']}")
    log.info(f"Start command: {config['start_command']}")
    log.info(f"Auto-stop: after {config['auto_stop_empty_minutes']}m empty")

    asyncio.create_task(watch_config(config))

    server = await asyncio.start_server(
        lambda r, w: handle_connection(r, w, config, server_mgr),
        config["listen_host"],
        config["listen_port"],
    )

    async with server:
        await server.serve_forever()



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")
