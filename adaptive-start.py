#!/usr/bin/env python3
VERSION = '3.1.0'

"""
Minecraft Adaptive Server Starter (MASS)!

This is a script/program that will start a Minecraft server if a player tries to join,
or stops a Minecraft server if no players are online within a set period.

Currently only works and tested with Linux (more specifically, Debian/Ubuntu systems).

Now has RAM/SWAP requirements to start!

HOW TO USE:
Just put this file in an already started Minecraft server directory and it'll automatically adjust its config values!
Run the program and then ensure the config is accurate and suited for your needs.
Then, simply run this program forever and it'll automatically start the server!

PIP REQUIREMENTS:
pip install requests pyyaml cryptography google-auth google-auth-httplib2 google-auth-oauthlib google-api-python-client
"""

"""
Version updates:
3.1.1:
- For cloud backups, added a timeout to allow players to join while it is being backed up

3.1:
- Added cloud backup

3.0:
- Switched config format from JSON to YAML
- Optional startup lock file 
- Auto RAM detection
- MOTD server.properties copy

2.1:
- Adds IP listing - whitelist/blacklist options
- Fixed no response not working + default * blacklist (2.1.1)
- Fixed various bugs (2.1.2)

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
import fcntl
import fnmatch
import os
import json
import logging
import re
import requests
import struct
import time
from pathlib import Path
import psutil
import yaml
import random
import threading

log = logging.getLogger("ServerStarter")


CONFIG_FILENAME = "mass-config.yaml"
VERIFIED_IPS_FILE = "verified_ips.json"

STARTUP_TIMES_FILE = "startup_times.json"
MAX_STORED_TIMES = 5

"""
DEFAULT CONFIG

Below is the default YAML config that gets written on first run.
The comments inside the template are written verbatim into mass-config.yaml so users can edit and discover options directly from the file.

TL;DR Don't change the default below unless you want to change MASS's defaults.
"""
DEFAULT_CONFIG_YAML = """\
# =========================================================================
# Minecraft Adaptive Server Starter (MASS) configuration
# =========================================================================

# -------------------------------------------------------------------------
# Proxy & Server Ports
# -------------------------------------------------------------------------

# IP/host the proxy listens on
listen_host: 0.0.0.0
listen_port: 25565

# Server port. Typically this is null as it will be detected automatically.
server_port: null

# Server directory (where server.properties / start.sh live)
server_dir: .

# -------------------------------------------------------------------------
# Server Start Command
# -------------------------------------------------------------------------

# Command used to start the server (e.g. "bash start.sh")
start_command: "java -Xmx4G -server -jar server.jar nogui"

# -------------------------------------------------------------------------
# Memory Requirements
# -------------------------------------------------------------------------

# Required free RAM/SWAP (in GB) before the server is allowed to start.
#   null or 0: skip the check (disabled)
#   -1:        auto-detect
ram_required: -1
swap_required: null

# Kick message when there isn't enough memory available.
kick_message_no_memory: "\u00A74The physical server does not have enough memory to wake the Minecraft server!\\n\\n\u00A74This issue should be reported to the administrators."

# -------------------------------------------------------------------------
# Startup Coordination Lock
# -------------------------------------------------------------------------

# Optional path to a lock file. While the lock is held, other MASS instances
# pointed at the same file will not start their servers - useful when several
# servers share one machine and you want to stagger startups.
# The lock is acquired before launching the server and released once the
# server is ready, fails to start, or is stopped. Set to null to disable.
lock_file: null

# Kick message when another MASS instance currently holds the start lock.
kick_message_locked: "\u00A7eAnother server is currently starting up on this machine.\\n\u00A7bPlease try again in a moment."

# -------------------------------------------------------------------------
# Display Messages
# For when the server is being started / has not started yet.
# -------------------------------------------------------------------------

# Placeholders available: {{ESTIMATED_TIME_REMAINING}} and {{ESTIMATED_TIME}}.
kick_message: "\u00A7eThis server is waking up...\u00A7r\\n\\n\u00A7bEstimated time remaining: {{ESTIMATED_TIME_REMAINING}}"
offline_motd: "\u00A74This server is sleeping.\u00A7r\\n\u00A7aJoin it to wake it! ({{ESTIMATED_TIME}})"
starting_motd: "\u00A7eThis server is waking up...\u00A7r\\n\u00A7bEstimated time remaining: {{ESTIMATED_TIME_REMAINING}}"

# Version text to be displayed
offline_version_text: "\u00A74Sleeping"
starting_version_text: "\u00A7eWaking..."

# If true, use the MOTD value from server.properties for both the offline and starting MOTD
# Otherwise it will use the MOTDs set in this config.
use_server_properties_motd: false

# -------------------------------------------------------------------------
# Auto-stop & Timing
# -------------------------------------------------------------------------

# After how many minutes should the server be stopped
# Set null to disable
auto_stop_empty_minutes: 2

# Amount of seconds to check the number of players online and determine the stop timeout
auto_stop_poll_interval: 3

# Max seconds to wait for the server to become reachable before MASS kills the process
# Set null to disable
startup_timeout: 300

# Amount of seconds to check if the server is online
poll_interval: 0.5


# -------------------------------------------------------------------------
# Icons
# -------------------------------------------------------------------------

# Paths to PNG icons (relative to server_dir).
# Set to null to disable.
offline_icon: null
starting_icon: null

# -------------------------------------------------------------------------
# Auto Update
# -------------------------------------------------------------------------

# Whether MASS checks for updates and self-replaces. Disable for stricter
# stability/security. Enabled by default since the project is small and in
# active development.
auto_update: true
auto_update_urls:
  - https://raw.githubusercontent.com/Kevcore25/MCTools/refs/heads/main/adaptive-start.py
  - https://kaf.kcservers.ca/releases/mass.py

# -------------------------------------------------------------------------
# IP Listing
# -------------------------------------------------------------------------

# Kick message for blocked IPs. {{IP}} and {{REASON}} are substituted.
ip_listing_kick_message: "\u00A74You have been denied access to the server.\\n\\nPlease contact an administrator if this is a mistake."

# Whitelist/Blacklist IPs.
# Whitelist always takes priority over blacklist; thus, for a
#   Whitelist-only mode -> whitelist: [ip, ip], blacklist: ["*"]
#   Blacklist-only mode -> whitelist: [],       blacklist: [ip, ip]
# (banned-ips.json is automatically merged with the blacklist.)
ip_listing_whitelist:
  - ""
ip_listing_blacklist:
  - ""

# Geolocation whitelist. If non-empty, becomes city/region whitelist mode.
# City entries should be lowercase, region entries uppercase.
# Note: this uses an external API.
ip_listing_whitelist_city: []

# If true, drop the connection silently rather than sending a kick reason.
# SmartMode has partial function if this is on.
ip_listing_no_response: false

# SmartMode blocks VPNs / proxies / TOR / malicious IPs via an external API.
# - IPs already in usercache.json are still allowed (users who joined before)
# - Any IP matching the whitelist always passes
ip_listing_smartmode: true

# -------------------------------------------------------------------------
# Automatic backups (Google Drive)
# -------------------------------------------------------------------------

# Backups are uploaded to Google Drive in the naming scheme: backup{id}.ext

# Enable backups. The world folder (found in server.properties) is backed up upon a server sleep under certain conditions.
# If a player attempts to start the server while the server is backing up the world, the player is refused.
# However, a player who already joined the server before can join back again, causing the backup to be stopped.
backups: false

# Filename (location) of the Google Drive API Credentials file.
# You need to create one if this does not exist.
credentials_file: null

# Google Drive Folder ID for the world to be backed up to
drive_folder_id: null

# Maximum backup amount (if this number is reached, the oldest backup is deleted)
max_backups: 3

# Backup timeout. When the timeout is reached, and a player tries to join the server, the server will allow the player to join the server.
# Note that a force server start will NOT stop the backup - the backup will continue and the server will start.
backup_timeout: 600

# Backup kick message, when the server is being backed up.
backup_kick_message: "\u00A77The server is being backed up.\\n\\nPlease wait a moment before reconnecting.\\n\\nCurrently taking {{BACKUP_TIME}}s | Stage: {{BACKUP_STAGE}}"

# Naming scheme. Placeholder {{ID}} generates a random number. 
# Do not put file extensions (e.g. .zip) as they will automatically be added. 
backup_naming_scheme: backup{{ID}}

# Compression method. Available options: zstandard, zip
# Zstandard allows for efficient compression as Minecraft region files already use it.
# Zstandard requires the zstandard package from PyPi (pip install zstandard) IF your Python version is 3.13 or lower.
compression_method: zstandard

# Level of compression. Higher numbers decrease file size but greatly increases the time required to compress.
# It is recommended to keep it somewhat low (2-3) unless you really need the compression (5-9)
compression_level: 3
"""

# Loaded once on import for fallback defaults (used by load_config + reload).
DEFAULT_CONFIG: dict[str, str|int|list[str]|bool|None|float] = yaml.safe_load(DEFAULT_CONFIG_YAML)

backup_time = None

class DriveAPI:
    def __init__(self, credentialsFile: str):
        self.credentials = credentialsFile
        self.__get_drive_service()

    def __get_drive_service(self):
        """Authenticates and returns the Google Drive API service instance"""
        creds = None
        tokenFile = 'driveAPIauth.token'
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        import googleapiclient.discovery
        import pickle

        if os.path.exists(tokenFile):
            with open(tokenFile, 'rb') as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', ['https://www.googleapis.com/auth/drive'])
                creds = flow.run_local_server(port=0)

            with open(tokenFile, 'wb') as token:
                pickle.dump(creds, token)

        self.service: googleapiclient.discovery.Resource = googleapiclient.discovery.build('drive', 'v3', credentials=creds)

    def upload_file(self, filename: str, folder_id: str = None) -> str:
        """Uploads a file to a specified Google Drive folder and returns its ID"""
        from googleapiclient.http import MediaFileUpload
        from googleapiclient.errors import HttpError

        try:
            file_name = os.path.basename(filename)
            
            file_metadata = {'name': file_name}
            if folder_id:
                file_metadata['parents'] = [folder_id]

            media = MediaFileUpload(filename, resumable=True)

            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            return file.get('id')

        except HttpError as error:
            log.error(f"An API error occurred during upload: {error}")
        except FileNotFoundError:
            log.error(f"Error: Local file not found at '{filename}'")

        return None


    def delete_file(self, fileID: str):
        from googleapiclient.errors import HttpError
        try:
            self.service.files().delete(fileId=fileID).execute()
            return True

        except HttpError as error:
            if error.resp.status == 404:
                log.error(f"Error: File ID '{fileID}' not found.")
            else:
                log.error(f"An API error occurred during deletion: {error}")
            return False
        

class Compressor:
    def __init__(self, method: str = 'zstandard', level: int = 3):
        self.method = method.lower()
        self.level = level

    def compress_world_zstd(self, folder: str, outputName: str, threads: int = -1) -> int:
        """Compresses a Minecraft world folder into a .tar.zst archive.

        Returns the size of the archive.
        """
        folderPath = Path(folder)
        outputPath = Path(outputName)
        actualThreads = os.cpu_count() or 4 if threads == -1 else threads

        import tarfile

        try:
            import compression.zstd as zstd
            options = {zstd.CompressionParameter.nb_workers: actualThreads, zstd.CompressionParameter.compression_level: self.level}
            
            with tarfile.open(outputPath, mode="w:zst", options=options) as tar:
                tar.add(folderPath)

        except (ImportError, AttributeError):
            import zstandard as zstd
            cctx = zstd.ZstdCompressor(level=self.level, threads=actualThreads)

            with open(outputPath, "wb") as f_out:
                with cctx.stream_writer(f_out) as compressor:
                    with tarfile.open(
                        fileobj=compressor, mode="w|", format=tarfile.PAX_FORMAT
                    ) as tar:
                        tar.add(folderPath, arcname=folderPath.name)
                        
        filesize = outputPath.stat().st_size
        return filesize
    
    def compress_world_zip(self, folder: str, outputName: str) -> int:
        """
        Compresses a Minecraft world using built-in zipfile with fast DEFLATE (Level 2).

        Returns the size of the archive.
        """
        import zipfile

        folderPath = Path(folder)
        outputPath = Path(outputName)

        with zipfile.ZipFile(outputPath, "w", zipfile.ZIP_DEFLATED, compresslevel=self.level) as f:
            for file in folderPath.rglob("*"):
                if file.is_file():
                    # Preserve folder structure inside the archive
                    relativePath = file.relative_to(folderPath.parent)
                    f.write(file, arcname=relativePath)

        filesize = outputPath.stat().st_size

        return filesize

    def compress(self, folder: str, outputNameNoExt: str = None) -> tuple[str, int]:
        if outputNameNoExt is None: 
            outputNameNoExt = folder

        if self.method == 'zstandard':
            return (outputNameNoExt + '.tar.zstd', self.compress_world_zstd(folder, outputNameNoExt + '.tar.zstd'))
        elif self.method == 'zip':
            return (outputNameNoExt + '.zip', self.compress_world_zip(folder, outputNameNoExt + '.zip'))
        else:
            log.error("Error: Compress method is invalid")
            return (None, -1)

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
    """Checks for updates and updates the file if needed"""
    log.info("Checking for updates...")

    for i, url in enumerate(config["auto_update_urls"], start=1):
        try:
            r = requests.get(url, timeout=1)

            # Check status
            if r.status_code != 200:
                raise Exception(f"Returned status code {r.status_code}")
            
            # Get version. The correct format is within 10 lines of code
            for j in range(10):
                try:
                    version = r.text.splitlines()[j].split('=', 1)[1].strip().strip("'").strip('"')
                    break
                except: pass
            else:
                raise IndexError
            
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

def get_xmx(text: str) -> float | None:
    """Return the -Xmx value (in GB) found in text, or None if not present"""
    match = re.search(r"-Xmx(\d+(?:\.\d+)?)([gGmMkK]?)", text)

    if match is None:
        return None
    
    value = float(match.group(1))
    unit = match.group(2).lower()

    match unit:
        # surely no one uses T right (does it even exist)
        case "g":
            return value
        case "m":
            return value / 1024
        case "k":
            return value / (1024 ** 2)
        case _:
            return value / (1024 ** 3)


def detect_ram_from_command(command: str, server_dir: str) -> float | None:
    """Parse the start command (recursing into any referenced .sh) for -Xmx"""
    direct = get_xmx(command)
    if direct is not None:
        return direct

    script_match = re.search(r"(\S+\.sh)\b", command)
    if script_match:
        script_path = Path(server_dir) / script_match.group(1)
        if script_path.exists():
            try:
                with open(script_path) as f:
                    return get_xmx(f.read())
            except OSError:
                pass
    return None


def read_server_properties_motd(server_dir: str) -> str | None:
    """Return the `motd=` value from server.properties, decoded from escape codes."""
    props_path = Path(server_dir) / "server.properties"
    if not props_path.exists():
        return None
    try:
        with open(props_path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("motd="):
                    raw = line.split("=", 1)[1]
                    # server.properties stores section signs as literal §
                    try:
                        return raw.encode("latin-1", "ignore").decode("unicode_escape")
                    except UnicodeDecodeError:
                        return raw
    except OSError:
        return None
    return None


def create_config(config_path: str = CONFIG_FILENAME):
    template = DEFAULT_CONFIG_YAML
    overrides: dict[str, str] = {}

    # Server.properties: shift backend port by +1 and let the proxy use the original.
    if Path("server.properties").exists():
        with open("server.properties", "r") as f:
            props = f.readlines()

        for i, ln in enumerate(props):
            if ln.startswith("#") or ln.isspace() or ln == "":
                continue
            k, v = ln.rstrip("\n").split("=", 1)
            if k == "server-port":
                v = int(v)
                overrides["listen_port"] = str(v)
                props[i] = f"server-port={v + 1}\n"
                with open("server.properties", "w") as f:
                    f.writelines(props)
                log.info(
                    f"The server port is switched from {v} to {v + 1} and the proxy "
                    f"server's port is set to {v}"
                )
                break

    # start.sh wrapper
    if Path("start.sh").exists():
        overrides["start_command"] = '"bash start.sh"'

    # Apply overrides by replacing the template's default value lines.
    for key, replacement in overrides.items():
        template = re.sub(
            rf"^({re.escape(key)}):.*$",
            lambda m, r=replacement: f"{m.group(1)}: {r}",
            template,
            count=1,
            flags=re.MULTILINE,
        )

    with open(config_path, "w") as f:
        f.write(template)

    log.info(f"Created default config at {config_path}")
    return yaml.safe_load(template)
    
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


def migrate_legacy_json(yaml_path: str, old_path: str = "mass-config.json") -> dict | None:
    """Convert mass-config.json -> mass-config.yaml (without comments). Returns merged config."""
    legacy = Path(old_path)
    if not legacy.exists():
        return None
    try:
        with open(legacy) as f:
            user_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning(f"Found {old_path} but couldn't parse it: {e}")
        return None

    merged = DEFAULT_CONFIG.copy()
    merged.update({k: v for k, v in user_data.items() if v is not None})

    with open(yaml_path, "w") as f:
        yaml.safe_dump(merged, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    try:
        os.rename(legacy, str(legacy) + ".bak")
    except OSError:
        pass
    log.info(
        f"Migrated legacy {old_path} to {yaml_path} (original saved as {old_path}.bak)."
    )
    return merged


def load_config(path: str = CONFIG_FILENAME) -> dict:
    config = DEFAULT_CONFIG.copy()
    config_path = Path(path)

    if config_path.exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        config.update({k: v for k, v in user_config.items() if v is not None})
    else:
        # Try migration of old to new config
        migrated = migrate_legacy_json(path)
        if migrated is not None:
            config = migrated
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
                elif line.startswith("level-name="):
                    config["_world_folder"] = line.split("=", 1)[1].strip()
    if config["_rcon_enabled"]:
        log.info(f"RCON detected on port {config['_rcon_port']} (will use as stop fallback)")

    # Auto-detect ram_required from -Xmx if set to -1
    if config.get("ram_required") == -1:
        detected = detect_ram_from_command(config["start_command"], config["server_dir"])
        if detected is not None:
            log.info(f"Auto-detected ram_required={detected:.2f} GB from start command (-Xmx).")
            config["ram_required"] = detected
        else:
            log.warning(
                "ram_required is -1 but no -Xmx flag was found in the start command "
                "or its referenced script. Disabling the RAM check."
            )
            config["ram_required"] = None

    # Cache server.properties MOTD if the option is enabled
    config["_server_properties_motd"] = None
    if config.get("use_server_properties_motd"):
        motd = read_server_properties_motd(config["server_dir"])
        if motd:
            config["_server_properties_motd"] = motd
            log.info(f"Using MOTD from server.properties: {motd!r}")
        else:
            log.warning("use_server_properties_motd is enabled but no MOTD was found in server.properties.")

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

backup_stage: str = "None"
def start_backup(config: dict[str, str|int]):
    """Starts backing up the server to Google Drive"""
    global backup_stage, backup_time
    try:
        backup_stage = "Starting"

        # Get previous compression data
        if not os.path.exists('mass_backup_data.json'):
            with open('mass_backup_data.json', 'x') as f:
                f.write('[]')

        with open('mass_backup_data.json', 'r') as f:
            backupIDs: list[str] = json.load(f)

        numOfBackups = len(backupIDs)
        
        # Compress world first before uploading
        backup_stage = "Compressing"
        compressor = Compressor(config.get('compression-method', 'zip'), config.get('compression-level', 3))
        worldFolder = config['_world_folder']

        filename, filesize = compressor.compress(worldFolder, config.get('backup-naming-scheme', 'backup{{ID}}').replace('{{ID}}', str(random.randint(1000000, 9999999))))

        log.info(f"Compressed world folder '{worldFolder}' with a size of {(filesize / (1024**2)):.1f} MB")

        # Upload to drive
        backup_stage = "Getting credentials"
        credfile = config.get('credentials_file', None)
        if credfile is None or not os.path.exists(credfile):
            log.warning(f"Credentials file '{credfile}' does not exist! Backup will not continue")
            return False
        
        drive = DriveAPI(credfile)

        # Delete previous backup if applicable
        backup_stage = "Deleting old backups"
        if numOfBackups >= config.get('max_backups', 1):
            drive.delete_file(backupIDs.pop(0))

        # Upload and save
        backup_stage = f"Uploading ({round(filesize/(1024**2))} MB)"
        fileID = drive.upload_file(filename, config['drive_folder_id'])
        backupIDs.append(fileID)

        with open('mass_backup_data.json', 'w') as f:
            json.dump(backupIDs, f)

        # Delete temp compressed folder
        backup_stage = "Deleting temporary backup file"
        os.remove(filename)
        backup_stage = "Done"
        log.info(f"Backup successful! Took {round(time.time() - backup_time, 1)}s to complete.")
        backup_time = None
        return True
    except Exception as e:
        log.error(f"An error occurred while backing up: {e}")
        backup_stage = "Failed"
        backup_time = None
        return False
        

class ServerManager:
    def __init__(self, config: dict):
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._starting = False
        self._start_time: float | None = None
        self._started_at: float | None = None
        self._ready_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._auto_stop_task: asyncio.Task | None = None
        # Cross-process startup lock (held while a server is in the startup phase).
        self._start_lock_fd: int | None = None
        self.backup_time = None
        self._playtime = 0
        self._player_join_at = None

    def _acquire_start_lock(self) -> bool:
        """Try to acquire the cross-process startup lock. Returns True if held (or disabled)."""
        lock_path = self.config.get("lock_file")
        if not lock_path:
            return True
        if self._start_lock_fd is not None:
            return True
        try:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as e:
            log.warning(f"Could not open lock file {lock_path}: {e}. Proceeding without lock.")
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            os.close(fd)
            return False
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
        except OSError:
            pass
        self._start_lock_fd = fd
        log.info(f"Acquired startup lock: {lock_path}")
        return True

    def _release_start_lock(self):
        if self._start_lock_fd is None:
            return
        try:
            fcntl.flock(self._start_lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self._start_lock_fd)
        except OSError:
            pass
        self._start_lock_fd = None
        log.info("Released startup lock.")

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

    async def trigger_start(self) -> str:
        """Start the server process if not already started. Non-blocking.

        Returns one of:
          - "started":  startup has been triggered
          - "starting": another caller already triggered startup
          - "running":  the server is already up
          - "locked":   another MASS instance holds the start lock
        """
        async with self._lock:
            if self._starting:
                return "starting"
            if await self.is_running():
                return "running"
            if not self._acquire_start_lock():
                log.info("Startup blocked: another MASS instance holds the lock.")
                return "locked"
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
            return "started"

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
        
    async def backup(self):
        global backup_time

        # Start backup
        if self.config['backups']:
            if ((self.config['auto_stop_empty_minutes'] is not None and self._playtime > 120) or self.config['auto_stop_empty_minutes'] is None):
                log.info("Starting to backup the server")
                backup_time = time.time()
                threading.Thread(target = start_backup, args=(self.config, ), daemon=True).start()

            else:
                log.info(f"The backup did not start as there was no significant player activity detected (playtime was about {(round(self._playtime))}s)")

        # Reset values
        self._player_join_at = None
        self._playtime = 0

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
                return await self.backup()
            log.warning("Server did not stop via stdin within 30s.")

        # Attempt 2: RCON (works even without a process handle)
        # Typically this is used for modded servers but needs RCON enabled -> less secure
        if await self._try_rcon_stop():
            if has_process:
                if await self._wait_for_process(30):
                    log.info("Server stopped via RCON.")
                    self._process = None
                    self._ready_event.clear()
                    return await self.backup()
                log.warning("Server did not stop via RCON within 30s.")
            else:
                # No process handle. Wait a bit then check if server is gone
                log.info("No process handle, waiting for RCON stop to take effect...")
                await asyncio.sleep(20)
                if not await self.is_running():
                    log.info("Server stopped via RCON.")
                    self._process = None
                    self._ready_event.clear()
                    return await self.backup()
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
        self._release_start_lock()
        await self.backup()
 


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
                    self._release_start_lock()
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
                    self._started_at = time.time()
                else:
                    log.info("Server is ready!")
                self._player_join_at = time.time() + 3 + self.config.get("auto_stop_poll_interval", 30)
                self._starting = False
                self._ready_event.set()
                self._release_start_lock()
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
                if self._player_join_at is not None:
                    self._playtime += time.time() - self._player_join_at
                    self._player_join_at = None


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
                    self._player_join_at = time.time()
                    log.info(f"Auto-stop monitor: {count} player(s) online, resetting countdown.")
                empty_since = None


async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    config: dict,
    server_mgr: ServerManager,
):
    addr = writer.get_extra_info("peername")

    # Return if IP in the blacklist
    smdata = None
    citydata = None

    if config["ip_listing_no_response"]:
        ip = addr[0]
        try:

            # Skip but warn if private
            if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("176.16."):
                raise UserWarning("allowing private IP exception")

            # Fast cache - skip all API checks if this IP already passed
            if ip in verified_ips:
                raise UserWarning("cached safe IP")

            # Geolocation
            if config["ip_listing_whitelist_city"]:
                citydata = requests.get(f"https://api.sefinek.net/api/v2/geoip/{ip}").json().get("data", {"city": "unknown", "region": "unknown"})

                if citydata["city"].lower() not in config["ip_listing_whitelist_city"] and citydata["region"].upper() not in config["ip_listing_whitelist_city"]: 
                    raise ConnectionRefusedError(f"not in whitelist city ({citydata['city']} | {citydata['region']})")
                
            # Whitelist/Blacklist check 
            whitelist = config["ip_listing_whitelist"]
            blacklist = config["ip_listing_blacklist"]

            if whitelist or blacklist:
                in_whitelist = any(fnmatch.fnmatch(ip, p) for p in whitelist)
                in_blacklist = any(fnmatch.fnmatch(ip, p) for p in blacklist)

                if not in_whitelist and in_blacklist:
                    raise ConnectionRefusedError(f"in blacklist")
                
            # SmartMode
            if config["ip_listing_smartmode"] and not in_whitelist:
                smdata = requests.get(f"https://api.sefinek.net/api/v2/ip-checker/{ip}").json()
                # Autoblock Malicious and TOR
                if smdata["malicious"] or smdata["tor"]:
                    raise ConnectionRefusedError(f"malicious")
        except UserWarning:
            pass
        except ConnectionRefusedError as e:
            log.warning(f"Blocked IP ({ip}) due to: {e}")
            return
        except Exception as e:
            log.error(f"Handle connection IP verify error: {e}")
            return

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
            await handle_login(reader, writer, handshake_packet, protocol_version, config, server_mgr, addr, smdata, citydata)
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

async def handle_status(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, handshake_packet, config, server_mgr):
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
        if config.get("use_server_properties_motd") and config.get("_server_properties_motd"):
            motd = config["_server_properties_motd"]
        else:
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

def load_verified_ips() -> list[str]:
    p = Path(VERIFIED_IPS_FILE)
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    else:
        with open(p, 'x') as f:
            f.write('[]')
    return []

def save_verified_ips(ips: list[str]):
    with open(VERIFIED_IPS_FILE, "w") as f:
        json.dump(ips, f)

verified_ips = load_verified_ips()

async def handle_login(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, handshake_packet, protocol_version, config, server_mgr: ServerManager, addr, smdata, citydata):
    global backup_time

    packet_id, login_data = await asyncio.wait_for(read_packet(reader), timeout=10)
    if packet_id != 0x00:
        return

    login_start_packet = make_packet(0x00, login_data)

    # Parse player name
    player_name, _ = decode_string(login_data)
    log.info(f"Player {player_name} connecting using {addr[0]}:{addr[1]} (protocol {protocol_version})")

    ## IP LISTING
    try:
        ip: str = addr[0]

        # Skip but warn if private
        if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("176.16."):
            raise UserWarning("allowing private IP exception")

        # Fast cache — skip all API checks if this IP already passed
        if ip in verified_ips:
            raise UserWarning("cached safe IP")

        # Geolocation
        if config["ip_listing_whitelist_city"]:
            if citydata is None:
                citydata = requests.get(f"https://api.sefinek.net/api/v2/geoip/{ip}").json().get("data", {"city": "unknown", "region": "unknown"})

            if citydata["city"].lower() not in config["ip_listing_whitelist_city"] and citydata["region"].upper() not in config["ip_listing_whitelist_city"]: 
                raise ConnectionRefusedError(f"not in whitelist city ({citydata['city']} | {citydata['region']})")
            
        # Whitelist/Blacklist check 
        whitelist = config["ip_listing_whitelist"]
        blacklist = config["ip_listing_blacklist"]

        if whitelist or blacklist:
            in_whitelist = any(fnmatch.fnmatch(ip, p) for p in whitelist)
            in_blacklist = any(fnmatch.fnmatch(ip, p) for p in blacklist)

            if not in_whitelist and in_blacklist:
                raise ConnectionRefusedError(f"in blacklist")
            
        # SmartMode
        if config["ip_listing_smartmode"] and not in_whitelist:
            if smdata is None:
                smdata = requests.get(f"https://api.sefinek.net/api/v2/ip-checker/{ip}").json()
            # Autoblock Malicious and TOR
            if smdata["malicious"] or smdata["tor"]:
                raise ConnectionRefusedError(f"malicious")
            
            # VPN or Proxy but accept if in usercache.json
            # Intended for Online servers where a diff IP will just simply get blocked from invalid session
            if smdata["vpn"] or smdata["proxy"]:
                with open("usercache.json", 'r') as f:
                    usercache = json.load(f)
                for user in usercache:
                    if player_name == user["name"]: 
                        log.info(f"{player_name} has a proxy IP but has joined before")
                        break
                else:
                    raise ConnectionRefusedError("proxy")

        # All checks passed - cache this IP
        if ip not in verified_ips:
            verified_ips.append(ip)
            save_verified_ips(verified_ips)

    except UserWarning:
        pass
    except ConnectionRefusedError as e:
        return await send_disconnect_login(writer, config["ip_listing_kick_message"].replace("{{IP}}", ip).replace("{{REASON}}", str(e)))
    except Exception as e:
        log.error(f"IP listing exception: {e}")

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

    # Check if it is being backed up
    if backup_time is not None and (time.time() - backup_time) < config.get('backup_timeout', 3600):
        kick_msg = config.get("backup_kick_message", "The server is being backed up. Please wait a moment before reconnecting.\nIt has currently taken {{BACKUP_TIME}}s").replace("{{BACKUP_TIME}}", str(round(time.time() - backup_time))).replace("{{BACKUP_STAGE}}", backup_stage)
    else:
        status = await server_mgr.trigger_start()
        if status == "locked":
            kick_msg = apply_placeholders(
                config.get("kick_message_locked") or config["kick_message"],
                config["server_dir"], server_mgr._start_time,
            )
        else:
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
        format="[%(asctime)s] [MASS/%(levelname)s]: %(message)s",
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