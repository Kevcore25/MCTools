#!/usr/bin/env python3
VERSION = '3.4'

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
3.3:
- Added the optional "limbo" join method for 1.20.5+
- Transferred connections (handshake intent 3) are now accepted and passed to the server as normal logins
- Backup options are expanded

3.2:
- Prioritizes whitelist/blacklist now (e.g. fix geoblock when whitelisted)
- Allow local IPs to be passed (unless it is in the whitelist/blacklist) 

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
import datetime
import fcntl
import fnmatch
import gzip
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
import socket
import uuid as uuidlib
import zlib
from array import array
from collections import Counter

log = logging.getLogger("ServerStarter")

CONFIG_FILENAME = "mass-config.yaml"
VERIFIED_IPS_FILE = "verified_ips.json"

STARTUP_TIMES_FILE = "startup_times.json"
MAX_STORED_TIMES = 5

LOCAL_IPS = ["0.0.0.0", "127.0.0.1"] + [socket.gethostbyname_ex(socket.gethostname())[2]]

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
# Join Method
# What happens to a player who joins while the server is asleep / waking up.
# -------------------------------------------------------------------------

# kick:  the player is kicked with kick_message
# limbo: for 1.20.5+, the player is placed into a fake server and is transferred when the server starts
join_method: kick

# Text shown in the fake server. Updated every second.
# Placeholders available: {{ESTIMATED_TIME_REMAINING}} and {{ESTIMATED_TIME}}.
limbo_title: "§eThis server is waking up..."
limbo_subtitle: "§bEstimated time remaining: {{ESTIMATED_TIME_REMAINING}}"
limbo_actionbar: "§7You will join automatically once it is ready"

# Boss bar that fills up as the server starts, based on the average startup time.
# Same placeholders as above. Set limbo_bossbar to null to hide it.
# Colors: pink, blue, red, green, yellow, purple, white.
limbo_bossbar: "§eEstimated time remaining: {{ESTIMATED_TIME_REMAINING}}"
limbo_bossbar_color: yellow

# Message when the server did not manage to start while players were waiting.
limbo_failed_kick_message: "§4The server failed to start.§r\\n\\nPlease try again later."

# Address players are transferred to once the server is ready.
# Leave both as null to use the address the player joined with.
# Set them if players join through an SRV record or a raw IP and the transfer does not bring them back.
limbo_transfer_host: null
limbo_transfer_port: null

# A small world for players to explore while they wait (e.g. a parkour course).
# Path to a Sponge schematic (.schem) file, relative to server_dir. Set to null for an empty void.
# Create one with WorldEdit or FAWE: select the build, //copy, then //schem save <name>.
# The schematic's lowest corner is placed at 0, 0, 0. Players who fall off are returned to the spawn.
# Requires the limbo-data.json.gz file next to this script (downloaded automatically if missing).
# Not imported: sign text, container contents and entities. Doors and buttons do not work.
limbo_world: null

# Where players appear in the limbo world: [x, y, z] or [x, y, z, yaw, pitch].
# Set to null to spawn on top of the middle of the schematic.
limbo_spawn: null

# Game mode in the limbo: survival, creative, adventure or spectator.
# Adventure is recommended with a limbo_world. Without one, players cannot move in any game mode.
limbo_gamemode: spectator

# Time of day in the limbo: day, noon, night, midnight, or a number of ticks (0 - 24000).
limbo_time: day

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

# Enable backups. The world folder (found in server.properties) is backed up upon a server sleep under certain conditions.
# If a player attempts to start the server while the server is backing up the world, the player is refused.
# However, a player who already joined the server before can join back again, causing the backup to be stopped.
backups: false

# Filename (location) of the Google Drive API Credentials file.
# You need to create one if this does not exist.
credentials_file: null

# Google Drive Folder ID for the world to be backed up to
drive_folder_id: null

# Backups are kept in three subfolders of drive_folder_id (created automatically):
#   restart/ - the newest backups, one per server stop (or live backup)
#   daily/   - the last backup of each day
#   weekly/  - the last backup of each week
# A backup is uploaded once and moved between folders as it ages. 0 disables a tier.
backup_keep_restart: 3
backup_keep_daily: 3
backup_keep_weekly: 4

# Also back up while the server keeps running (e.g. it has not stopped for days).
# A live backup is taken when the newest backup is older than backup_live_interval_hours.
# It uses save-off / save-all flush / save-on (via RCON if enabled, otherwise the console).
# Players can keep playing and joining during a live backup.
backup_while_running: true
backup_live_interval_hours: 24

# Backup timeout. When the timeout is reached, and a player tries to join the server, the server will allow the player to join the server.
# Note that a force server start will NOT stop the backup - the backup will continue and the server will start.
backup_timeout: 600

# Backup kick message, when the server is being backed up.
backup_kick_message: "\u00A77The server is being backed up.\\n\\nPlease wait a moment before reconnecting.\\n\\nCurrently taking {{BACKUP_TIME}}s | Stage: {{BACKUP_STAGE}}"

# Naming scheme. Placeholder {{ID}} generates a random number, {{DATE}} the date and time (YYYY-MM-DD_HHMM).
# Do not put file extensions (e.g. .zip) as they will automatically be added.
backup_naming_scheme: backup_{{DATE}}

# Compression method. Available options: zstandard, zip
# Zstandard allows for efficient compression as Minecraft region files already use it.
# Zstandard requires the zstandard package from PyPi (pip install zstandard) IF your Python version is 3.13 or lower.
compression_method: zstandard

# Level of compression. Higher numbers decrease file size but greatly increases the time required to compress.
# It is recommended to keep it somewhat low (2-3) unless you really need the compression (5-9)
compression_level: 4
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
                    self.credentials, ['https://www.googleapis.com/auth/drive'])
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

    def ensure_folder(self, name: str, parent_id: str | None) -> str:
        """Return the ID of the folder with this name under parent_id, creating it if needed."""
        mime = 'application/vnd.google-apps.folder'
        safe_name = name.replace("\\", "\\\\").replace("'", "\\'")
        query = f"name = '{safe_name}' and mimeType = '{mime}' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        found = self.service.files().list(q=query, fields='files(id)', pageSize=1).execute().get('files', [])
        if found:
            return found[0]['id']
        metadata = {'name': name, 'mimeType': mime}
        if parent_id:
            metadata['parents'] = [parent_id]
        return self.service.files().create(body=metadata, fields='id').execute()['id']

    def move_file(self, fileID: str, new_parent: str) -> bool:
        """Move a file into a folder. Returns False if the file no longer exists."""
        from googleapiclient.errors import HttpError
        try:
            parents = self.service.files().get(fileId=fileID, fields='parents').execute().get('parents', [])
            if parents == [new_parent]:
                return True
            old_parents = ",".join(p for p in parents if p != new_parent)
            self.service.files().update(
                fileId=fileID, addParents=new_parent, removeParents=old_parents or None, fields='id'
            ).execute()
            return True
        except HttpError as error:
            if error.resp.status == 404:
                log.error(f"Error: File ID '{fileID}' not found.")
                return False
            raise

    def get_file_info(self, fileID: str) -> dict | None:
        """Name and creation time (epoch seconds) of a file, or None if it does not exist."""
        from googleapiclient.errors import HttpError
        try:
            info = self.service.files().get(fileId=fileID, fields='name,createdTime,trashed').execute()
        except HttpError as error:
            if error.resp.status == 404:
                return None
            raise
        if info.get('trashed'):
            return None
        created = datetime.datetime.fromisoformat(info['createdTime'].replace('Z', '+00:00')).timestamp()
        return {'name': info.get('name', ''), 'time': created}



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

async def rcon_send(host: str, port: int, password: str, command: str, timeout: float = 5) -> str | None:
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
        _, _, body = await asyncio.wait_for(_read_response(), timeout=timeout)
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
        # Older configs only have max_backups: use it as the restart tier size
        if user_config.get("max_backups") is not None and "backup_keep_restart" not in user_config:
            config["backup_keep_restart"] = user_config["max_backups"]
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

BACKUP_DATA_FILE = 'mass_backup_data.json'
BACKUP_TIERS = ('restart', 'daily', 'weekly')

# Only one backup (stop or live) may compress/upload at a time.
backup_lock = threading.Lock()
backup_stage: str = "None"


def plan_retention(backups: list[dict], keep_restart: int, keep_daily: int, keep_weekly: int) -> dict[str, str | None]:
    """Decide which folder each backup belongs in, or None if it should be deleted.

    restart: the newest keep_restart backups.
    daily:   the newest backup of each of the newest keep_daily days.
    weekly:  the newest backup of each of the newest keep_weekly ISO weeks.
    A backup in several sets goes to the first of restart, daily, weekly.
    """
    ordered = sorted(backups, key=lambda b: b['time'], reverse=True)

    def newest_per(key_fn, count: int) -> set[str]:
        keep: set[str] = set()
        seen: set = set()
        for b in ordered:
            key = key_fn(datetime.date.fromtimestamp(b['time']))
            if key in seen:
                continue
            seen.add(key)
            if len(seen) > count:
                break
            keep.add(b['id'])
        return keep

    restart = {b['id'] for b in ordered[:max(0, keep_restart)]}
    daily = newest_per(lambda d: d, max(0, keep_daily))
    weekly = newest_per(lambda d: d.isocalendar()[:2], max(0, keep_weekly))

    plan: dict[str, str | None] = {}
    for b in ordered:
        if b['id'] in restart:
            plan[b['id']] = 'restart'
        elif b['id'] in daily:
            plan[b['id']] = 'daily'
        elif b['id'] in weekly:
            plan[b['id']] = 'weekly'
        else:
            plan[b['id']] = None
    return plan


def load_backup_data() -> dict:
    """Read the backup records. The old format (a list of file IDs) is kept under 'legacy' for migration."""
    data = {'version': 2, 'folders': {}, 'backups': []}
    if not os.path.exists(BACKUP_DATA_FILE):
        return data
    try:
        with open(BACKUP_DATA_FILE, 'r') as f:
            stored = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        log.warning(f"Could not read {BACKUP_DATA_FILE} ({e}); starting with no backup records")
        return data
    if isinstance(stored, list):
        data['legacy'] = [i for i in stored if isinstance(i, str)]
    elif isinstance(stored, dict):
        data['folders'] = stored.get('folders') or {}
        data['backups'] = stored.get('backups') or []
    return data


def save_backup_data(data: dict):
    out = {'version': 2, 'folders': data.get('folders', {}), 'backups': data.get('backups', [])}
    if data.get('legacy'):
        out['legacy'] = data['legacy']
    with open(BACKUP_DATA_FILE, 'w') as f:
        json.dump(out, f, indent=2)


def last_backup_time() -> float | None:
    """Time of the newest recorded backup, if any."""
    times = [b['time'] for b in load_backup_data()['backups']]
    return max(times) if times else None


def apply_retention(drive: "DriveAPI", data: dict, config: dict):
    """Move backups between the tier folders and delete the ones no tier keeps."""
    plan = plan_retention(
        data['backups'],
        int(config.get('backup_keep_restart') or 0),
        int(config.get('backup_keep_daily') or 0),
        int(config.get('backup_keep_weekly') or 0),
    )
    kept = []
    for b in data['backups']:
        target = plan[b['id']]
        if target is None:
            log.info(f"Deleting old backup {b.get('name') or b['id']}")
            drive.delete_file(b['id'])
            continue
        if target != b.get('folder'):
            log.info(f"Moving backup {b.get('name') or b['id']} to {target}/")
            if not drive.move_file(b['id'], data['folders'][target]):
                continue  # Deleted on Drive by hand
            b['folder'] = target
        kept.append(b)
    data['backups'] = kept


def compress_world(config: dict) -> tuple[str, int]:
    """Compress the world folder into a local archive. Returns (filename, size)."""
    method = str(config.get('compression_method') or 'zstandard')
    level = int(config.get('compression_level') or 3)
    scheme = str(config.get('backup_naming_scheme') or 'backup_{{DATE}}_{{ID}}')
    name = (scheme.replace('{{ID}}', str(random.randint(1000000, 9999999)))
                  .replace('{{DATE}}', datetime.datetime.now().strftime('%Y-%m-%d_%H%M')))
    world = config['_world_folder']

    try:
        filename, size = Compressor(method, level).compress(world, name)
    except ImportError:
        log.warning("Zstandard is not available (pip install zstandard); falling back to zip for this backup")
        filename, size = Compressor('zip', level).compress(world, name)
    if filename is None:
        raise ValueError(f"Invalid compression_method '{method}'")
    log.info(f"Compressed world folder '{world}' with a size of {(size / (1024**2)):.1f} MB")
    return filename, size


def upload_backup(config: dict, filename: str, filesize: int) -> bool:
    """Upload a compressed world to the restart/ folder, then reorganize older backups."""
    global backup_stage
    try:
        backup_stage = "Getting credentials"
        credfile = config.get('credentials_file', None)
        if credfile is None or not os.path.exists(credfile):
            log.warning(f"Credentials file '{credfile}' does not exist! Backup will not continue")
            return False
        drive = DriveAPI(credfile)
        data = load_backup_data()

        backup_stage = "Preparing folders"
        root = config.get('drive_folder_id')
        data['folders'] = {tier: drive.ensure_folder(tier, root) for tier in BACKUP_TIERS}

        # Backups made by MASS 3.3 and older: give them a record and move them into restart/
        legacy = data.pop('legacy', [])
        if legacy:
            log.info(f"Moving {len(legacy)} backup(s) from the old format into restart/")
        for file_id in legacy:
            info = drive.get_file_info(file_id)
            if info is None or not drive.move_file(file_id, data['folders']['restart']):
                continue
            data['backups'].append({'id': file_id, 'name': info['name'], 'time': info['time'], 'folder': 'restart'})

        backup_stage = f"Uploading ({round(filesize/(1024**2))} MB)"
        created = time.time()
        file_id = drive.upload_file(filename, data['folders']['restart'])
        if file_id:
            data['backups'].append({'id': file_id, 'name': os.path.basename(filename), 'time': created, 'folder': 'restart'})

        backup_stage = "Organizing old backups"
        apply_retention(drive, data, config)
        save_backup_data(data)
        return bool(file_id)
    finally:
        backup_stage = "Deleting temporary backup file"
        try:
            os.remove(filename)
        except OSError:
            pass


def start_backup(config: dict[str, str|int]):
    """Back up the stopped server to Google Drive (runs in a thread)."""
    global backup_stage, backup_time
    started = backup_time or time.time()
    try:
        backup_stage = "Waiting for another backup"
        with backup_lock:
            backup_stage = "Compressing"
            filename, filesize = compress_world(config)
            if not upload_backup(config, filename, filesize):
                backup_stage = "Failed"
                return False
        backup_stage = "Done"
        log.info(f"Backup successful! Took {round(time.time() - started, 1)}s to complete.")
        return True
    except Exception as e:
        log.error(f"An error occurred while backing up: {e}")
        backup_stage = "Failed"
        return False
    finally:
        backup_time = None


def upload_live_backup(config: dict, filename: str, filesize: int):
    """Thread body for a live backup: upload, then release the backup lock taken by the caller."""
    started = time.time()
    try:
        if upload_backup(config, filename, filesize):
            log.info(f"Live backup uploaded! Took {round(time.time() - started, 1)}s.")
    except Exception as e:
        log.error(f"An error occurred while uploading the live backup: {e}")
    finally:
        backup_lock.release()


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
        self._live_backup_task: asyncio.Task | None = None
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

    def _current_playtime(self) -> float:
        """Player time since the last backup, including a session still in progress."""
        playtime = self._playtime
        if self._player_join_at is not None:
            playtime += max(0.0, time.time() - self._player_join_at)
        return playtime

    async def _world_command(self, command: str, wait: float = 0) -> bool:
        """Run a command on the server (RCON if enabled, otherwise the console).

        With a console-only server there is no reply, so `wait` seconds are waited instead.
        """
        if self.config.get("_rcon_enabled"):
            result = await rcon_send(
                "127.0.0.1", self.config["_rcon_port"], self.config["_rcon_password"], command,
                timeout=max(5, wait * 20),
            )
            if result is not None:
                return True
        if self._process and self._process.stdin and self._process.returncode is None:
            await self.send_command(command)
            if wait:
                await asyncio.sleep(wait)
            return True
        return False

    async def live_backup_monitor(self):
        """Back up the world while the server keeps running, once per backup_live_interval_hours."""
        poll_interval = self.config.get("auto_stop_poll_interval", 30)
        reference = time.time()  # Used if the server was never started or backed up by MASS
        while True:
            await asyncio.sleep(poll_interval)
            if not (self.config.get("backups") and self.config.get("backup_while_running")):
                continue
            try:
                interval = float(self.config.get("backup_live_interval_hours") or 0) * 3600
            except (TypeError, ValueError):
                continue
            if interval <= 0 or not self._ready_event.is_set() or not await self.is_running():
                continue

            since = max(t for t in (last_backup_time(), self._started_at, reference) if t is not None)
            if time.time() - since < interval:
                continue
            if self.config.get("auto_stop_empty_minutes") is not None and self._current_playtime() <= 120:
                # Nothing was played since the last backup; check again in one interval
                reference = time.time()
                continue
            if await self.live_backup():
                reference = time.time()

    async def live_backup(self) -> bool:
        """save-off, save-all flush, compress, save-on, then upload in the background."""
        if not backup_lock.acquire(blocking=False):
            log.info("Live backup skipped: another backup is still running")
            return False
        handed_off = False
        try:
            log.info("Starting a live backup of the running server")
            if not await self._world_command("save-off"):
                log.warning("Live backup skipped: cannot send commands to the server (enable RCON or let MASS start the server)")
                return False
            try:
                await self._world_command("save-all flush", wait=15)
                # Reset now: play after this point belongs to the next backup
                self._playtime = 0
                if self._player_join_at is not None:
                    self._player_join_at = time.time()
                filename, filesize = await asyncio.to_thread(compress_world, self.config)
            finally:
                await self._world_command("save-on")
            threading.Thread(target=upload_live_backup, args=(self.config, filename, filesize), daemon=True).start()
            handed_off = True
            return True
        except Exception as e:
            log.error(f"An error occurred during the live backup: {e}")
            return False
        finally:
            if not handed_off:
                backup_lock.release()

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
                # Start live backup monitor
                if self._live_backup_task is None or self._live_backup_task.done():
                    self._live_backup_task = asyncio.create_task(self.live_backup_monitor())
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


# =============================================================================
# Limbo (fake waiting server)
#
# Used when join_method is "limbo". MASS completes an offline-style login itself,
# puts the player in an empty world (or the limbo_world schematic), shows the time
# remaining in the title and action bar, and transfers the player to the real
# server once it is ready.
# Only Minecraft 1.20.5+ is supported, since older clients have no Transfer packet;
# every other version gets the classic kick.
# =============================================================================

# Protocol numbers where behaviour changes
PROTO_1_20_5 = 766   # Transfer packet, known packs (first supported version)
PROTO_1_21 = 767
PROTO_1_21_2 = 768
PROTO_1_21_5 = 770
PROTO_1_21_9 = 773
PROTO_1_21_11 = 774
PROTO_26_1 = 775
PROTO_26_2 = 776
PROTO_26_3 = 777

# Clientbound Play packet IDs for every supported protocol version.
LIMBO_PLAY_IDS: dict[int, dict[str, int]] = {}


def _limbo_ids(protocols, join, pos, keepalive, abilities, spawn, event, disconnect,
               title, subtitle, actionbar, times, transfer, chunk, center, time_):
    for p in protocols:
        LIMBO_PLAY_IDS[p] = {
            "join": join, "pos": pos, "keepalive": keepalive, "abilities": abilities,
            "spawn": spawn, "event": event, "disconnect": disconnect, "title": title,
            "subtitle": subtitle, "actionbar": actionbar, "times": times, "transfer": transfer,
            "chunk": chunk, "center": center, "time": time_,
        }


#           protocols        join  pos   keep  abil  spawn event disc  title sub   abar  times trans chunk centr time
_limbo_ids((766, 767),       0x2B, 0x40, 0x26, 0x38, 0x56, 0x22, 0x1D, 0x65, 0x63, 0x4C, 0x66, 0x73, 0x27, 0x54, 0x64)  # 1.20.5 - 1.21.1
_limbo_ids((768, 769),       0x2C, 0x42, 0x27, 0x3A, 0x5B, 0x23, 0x1D, 0x6C, 0x6A, 0x51, 0x6D, 0x7A, 0x28, 0x58, 0x6B)  # 1.21.2 - 1.21.4
_limbo_ids((770, 771, 772),  0x2B, 0x41, 0x26, 0x39, 0x5A, 0x22, 0x1C, 0x6B, 0x69, 0x50, 0x6C, 0x7A, 0x27, 0x57, 0x6A)  # 1.21.5 - 1.21.8
_limbo_ids((773, 774),       0x30, 0x46, 0x2B, 0x3E, 0x5F, 0x26, 0x20, 0x70, 0x6E, 0x55, 0x71, 0x7F, 0x2C, 0x5C, 0x6F)  # 1.21.9 - 1.21.11
_limbo_ids((775, 776),       0x31, 0x48, 0x2C, 0x40, 0x61, 0x26, 0x20, 0x72, 0x70, 0x57, 0x73, 0x81, 0x2D, 0x5E, 0x71)  # 26.1.x, 26.2
_limbo_ids((777,),           0x32, 0x49, 0x2D, 0x41, 0x63, 0x27, 0x20, 0x74, 0x72, 0x59, 0x75, 0x84, 0x2E, 0x60, 0x73)  # 26.3

# Serverbound Play packet IDs that start with the player's position (Set Player Position,
# and Set Player Position and Rotation). Used to notice players falling out of the limbo world.
for _p, _ids in LIMBO_PLAY_IDS.items():
    _ids["boss"] = 0x0A if _p < 770 else 0x09  # Boss Bar

# Serverbound position packets (see below)
LIMBO_MOVE_IDS: dict[int, tuple[int, ...]] = {
    766: (0x1A, 0x1B), 767: (0x1A, 0x1B),
    768: (0x1C, 0x1D), 769: (0x1C, 0x1D), 770: (0x1C, 0x1D),
    771: (0x1D, 0x1E), 772: (0x1D, 0x1E), 773: (0x1D, 0x1E),
    774: (0x1D, 0x1E, 0x1F),  # Not confirmed for 1.21.11; the packet length tells them apart
    775: (0x1E, 0x1F), 776: (0x1E, 0x1F), 777: (0x1E, 0x1F),
}

# Game versions sharing each protocol number. The client only uses its built-in
# registry data if the "minecraft:core" pack version matches its own version
# exactly, so every candidate is offered and the client picks its own.
LIMBO_CORE_PACKS: dict[int, tuple[str, ...]] = {
    766: ("1.20.5", "1.20.6"),
    767: ("1.21", "1.21.1"),
    768: ("1.21.2", "1.21.3"),
    769: ("1.21.4",),
    770: ("1.21.5",),
    771: ("1.21.6",),
    772: ("1.21.7", "1.21.8"),
    773: ("1.21.9", "1.21.10"),
    774: ("1.21.11",),
    775: ("26.1", "26.1.1", "26.1.2"),
    776: ("26.2",),
    777: ("26.3",),
}

LIMBO_WORLD = "minecraft:overworld"
LIMBO_SPAWN_Y = 400     # Without a limbo_world: above the build limit, so no chunks need to be sent
LIMBO_MIN_Y = -64       # Overworld height limits
LIMBO_HEIGHT = 384
LIMBO_VOID_Y = -100     # Players in a limbo_world who fall below this are returned to the spawn
LIMBO_MAX_SIZE = 512    # Largest schematic width and length, in blocks
LIMBO_DRAIN_TIMEOUT = 30  # Seconds a client may take to receive what was sent before it is dropped
LIMBO_COMPRESSION = 256  # Packet compression threshold, only used when a limbo_world is sent

LIMBO_GAMEMODES = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
LIMBO_TIMES = {"day": 1000, "noon": 6000, "night": 13000, "midnight": 18000}

# Block state IDs for every supported version, generated by tools/gen-limbo-data.py
LIMBO_DATA_FILE = "limbo-data.json.gz"
LIMBO_DATA_FORMAT = 1

_DAMAGE_TYPES_1_20_5 = (
    "arrow", "bad_respawn_point", "cactus", "cramming", "dragon_breath", "drown", "dry_out",
    "explosion", "fall", "falling_anvil", "falling_block", "falling_stalactite", "fireball",
    "fireworks", "fly_into_wall", "freeze", "generic", "generic_kill", "hot_floor", "in_fire",
    "in_wall", "indirect_magic", "lava", "lightning_bolt", "magic", "mob_attack",
    "mob_attack_no_aggro", "mob_projectile", "on_fire", "out_of_world", "outside_border",
    "player_attack", "player_explosion", "sonic_boom", "spit", "stalagmite", "starve", "sting",
    "sweet_berry_bush", "thorns", "thrown", "trident", "unattributed_fireball", "wither",
    "wither_skull",
)

_SULFUR_CUBE_ARCHETYPES = (
    "bouncy", "explosive", "fast_flat", "fast_sliding", "high_resistance", "hot", "light",
    "regular", "slow_bouncy", "slow_flat", "slow_sliding", "sticky",
)


def limbo_damage_types(protocol: int) -> list[str]:
    """Vanilla damage type names for a protocol version."""
    names = list(_DAMAGE_TYPES_1_20_5)
    if protocol >= PROTO_1_21:
        names += ["campfire", "wind_charge"]
    if protocol >= PROTO_1_21_2:
        names += ["ender_pearl", "mace_smash"]
    if protocol >= PROTO_1_21_11:
        names += ["spear"]
    if protocol >= PROTO_26_2:
        names += ["sulfur_cube_hot"]
    return names


# ----- Encoders --------------------------------------------------------------

def enc_bool(value: bool) -> bytes:
    return b"\x01" if value else b"\x00"


def enc_i8(value: int) -> bytes:
    return struct.pack(">b", value)


def enc_u8(value: int) -> bytes:
    return struct.pack(">B", value)


def enc_i32(value: int) -> bytes:
    return struct.pack(">i", value)


def enc_i64(value: int) -> bytes:
    return struct.pack(">q", value)


def enc_f32(value: float) -> bytes:
    return struct.pack(">f", value)


def enc_f64(value: float) -> bytes:
    return struct.pack(">d", value)


def enc_position(x: int, y: int, z: int) -> bytes:
    """Packed block position."""
    value = ((x & 0x3FFFFFF) << 38) | ((z & 0x3FFFFFF) << 12) | (y & 0xFFF)
    return struct.pack(">Q", value)


def _nbt_string(text: str) -> bytes:
    """NBT strings use Java's modified UTF-8 with an unsigned short length."""
    out = bytearray()
    raw = text.encode("utf-16-be", "surrogatepass")
    for i in range(0, len(raw), 2):
        unit = (raw[i] << 8) | raw[i + 1]
        if unit == 0:
            out += b"\xc0\x80"
        elif unit < 0x80:
            out.append(unit)
        elif unit < 0x800:
            out += bytes((0xC0 | (unit >> 6), 0x80 | (unit & 0x3F)))
        else:
            out += bytes((0xE0 | (unit >> 12), 0x80 | ((unit >> 6) & 0x3F), 0x80 | (unit & 0x3F)))
    return struct.pack(">H", len(out)) + bytes(out)


def encode_text(text: str) -> bytes:
    """Text component for Play/Configuration packets: a nameless NBT string tag."""
    return b"\x08" + _nbt_string(text)


# ----- Limbo world -----------------------------------------------------------
#
# An optional small world (limbo_world) read from a Sponge schematic file. The
# schematic names its blocks; the numeric IDs chunk packets need come from
# limbo-data.json.gz, which holds a table for each supported protocol version.

_NBT_NUMBERS = {1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}
_LIMBO_AIR = ("minecraft:air", "minecraft:cave_air", "minecraft:void_air")


def read_nbt(data: bytes) -> dict:
    """Parse an uncompressed NBT file into plain Python values. Returns the root compound."""
    pos = 0

    def take(count: int) -> bytes:
        nonlocal pos
        if count < 0 or pos + count > len(data):
            raise ValueError("NBT data is truncated")
        chunk = data[pos : pos + count]
        pos += count
        return chunk

    def number(fmt: str):
        return struct.unpack(fmt, take(struct.calcsize(fmt)))[0]

    def string() -> str:
        return take(number(">H")).decode("utf-8", "replace")

    def payload(tag: int, depth: int):
        if depth > 64:
            raise ValueError("NBT data is nested too deeply")
        if tag in _NBT_NUMBERS:
            return number(_NBT_NUMBERS[tag])
        if tag == 7:  # Byte array
            return take(number(">i"))
        if tag == 8:
            return string()
        if tag == 9:  # List
            item_tag = number(">B")
            return [payload(item_tag, depth + 1) for _ in range(number(">i"))]
        if tag == 10:  # Compound
            out = {}
            while True:
                child = number(">B")
                if child == 0:
                    return out
                name = string()
                out[name] = payload(child, depth + 1)
        if tag in (11, 12):  # Int array, long array
            count = number(">i")
            size = 4 if tag == 11 else 8
            return list(struct.unpack(f">{count}{'i' if tag == 11 else 'q'}", take(count * size)))
        raise ValueError(f"Unknown NBT tag {tag}")

    if number(">B") != 10:
        raise ValueError("Not an NBT file")
    string()  # Root name
    return payload(10, 0)


def _pack_entries(values, bits: int) -> bytes:
    """Pack 4096 palette entries into the 64-bit longs of a paletted container.

    Entries fill each long from its lowest bits and never span two longs.
    """
    if bits == 4:
        values = bytes(values)
        low = int.from_bytes(values[0::2], "little")
        high = int.from_bytes(values[1::2], "little")
        values = (low | (high << 4)).to_bytes(2048, "little")
        bits = 8
    if bits == 8:
        values = bytes(values)
        return b"".join([values[i : i + 8][::-1] for i in range(0, len(values), 8)])
    per_long = 64 // bits
    longs = []
    for i in range(0, 4096, per_long):
        value = 0
        shift = 0
        for entry in values[i : i + per_long]:
            value |= entry << shift
            shift += bits
        longs.append(value)
    return struct.pack(f">{len(longs)}Q", *longs)


class LimboWorld:
    """A schematic split into 16x16x16 sections, independent of the protocol version."""

    def __init__(self, path: Path):
        raw = path.read_bytes()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        root = read_nbt(raw)
        root = root.get("Schematic", root)  # Version 3 nests everything in "Schematic"
        if not isinstance(root, dict):
            raise ValueError("not a Sponge schematic")

        blocks = root.get("Blocks")
        if isinstance(blocks, dict):  # Version 3
            palette_map, data = blocks.get("Palette"), blocks.get("Data")
        else:  # Version 2
            palette_map, data = root.get("Palette"), root.get("BlockData")
        try:
            width, height, length = (int(root[k]) & 0xFFFF for k in ("Width", "Height", "Length"))
        except (KeyError, TypeError, ValueError):
            raise ValueError("not a Sponge schematic (no size)") from None
        if not isinstance(palette_map, dict) or not isinstance(data, (bytes, bytearray)) or not palette_map:
            raise ValueError("not a Sponge schematic version 2 or 3 (no block palette)")
        if not width or not height or not length:
            raise ValueError("the schematic is empty")
        if width > LIMBO_MAX_SIZE or length > LIMBO_MAX_SIZE:
            raise ValueError(f"the schematic is {width}x{length} blocks; the limit is {LIMBO_MAX_SIZE}x{LIMBO_MAX_SIZE}")

        # Palette: block state name for each index, plus air for the space around the build
        size = max(palette_map.values()) + 1
        if min(palette_map.values()) < 0 or size > 60000:
            raise ValueError("the schematic's block palette is invalid")
        palette = ["minecraft:air"] * size
        for name, index in palette_map.items():
            palette[index] = str(name)
        if "minecraft:air" not in palette:
            palette.append("minecraft:air")
        self.palette = palette
        air = palette.index("minecraft:air")
        is_air = [name.split("[", 1)[0] in _LIMBO_AIR for name in palette]

        # Block data: one VarInt palette index per block, ordered x, then z, then y
        volume = width * height * length
        if max(data) < 0x80:
            indices = bytes(data)  # Every index fits in one byte
        else:
            values = array("H")
            value = shift = 0
            for byte in data:
                value |= (byte & 0x7F) << shift
                if byte & 0x80:
                    shift += 7
                    if shift > 14:
                        raise ValueError("the schematic's block data is invalid")
                else:
                    values.append(value)
                    value = shift = 0
            indices = bytes(values) if len(palette) <= 256 and max(values) < 256 else values
        if len(indices) != volume or max(indices) >= len(palette):
            raise ValueError("the schematic's block data does not match its size")

        max_height = LIMBO_MIN_Y + LIMBO_HEIGHT
        if height > max_height:
            log.warning(f"Limbo world: {path.name} is {height} blocks tall; everything above Y={max_height - 1} is cut off.")
            height = max_height
        self.width, self.height, self.length = width, height, length
        self.chunks_x = (width + 15) // 16
        self.chunks_z = (length + 15) // 16

        # Default spawn: on top of the column nearest to the middle that has a block in it
        layer = width * length
        self.spawn = None
        mid_x, mid_z = width // 2, length // 2
        columns = sorted(((x - mid_x) ** 2 + (z - mid_z) ** 2, x, z) for x in range(width) for z in range(length))
        for _distance, x, z in columns:
            column = indices[z * width + x : height * layer : layer]
            for y in range(height - 1, -1, -1):
                if not is_air[column[y]]:
                    self.spawn = (x + 0.5, float(y + 1), z + 0.5, 0.0, 0.0)
                    break
            if self.spawn:
                break
        if self.spawn is None:
            raise ValueError("the schematic contains no blocks")

        # Sections, keyed by (chunk x, section y, chunk z). Each is the list of palette
        # indices it uses, how many blocks use each, the bits per entry and the packed
        # entries (or, with over 256 different blocks, the unpacked entries).
        self.sections: dict[tuple[int, int, int], tuple] = {}
        wide = not isinstance(indices, bytes)
        pad = array("H", [air]) if wide else bytes([air])
        for sy in range((height + 15) // 16):
            for cz in range(self.chunks_z):
                for cx in range(self.chunks_x):
                    x0, x1 = cx * 16, min(cx * 16 + 16, width)
                    x_pad = pad * (16 - (x1 - x0))
                    parts = []
                    for y in range(sy * 16, sy * 16 + 16):
                        if y >= height:
                            parts.append(pad * 256)
                            continue
                        for z in range(cz * 16, cz * 16 + 16):
                            if z >= length:
                                parts.append(pad * 16)
                                continue
                            offset = (y * length + z) * width
                            parts.append(indices[offset + x0 : offset + x1])
                            if x_pad:
                                parts.append(x_pad)
                    if wide:
                        section = array("H")
                        for part in parts:
                            section.extend(part)
                    else:
                        section = b"".join(parts)

                    counts = Counter(section)
                    used = sorted(counts)
                    if all(is_air[i] for i in used):
                        continue
                    amounts = [counts[i] for i in used]
                    if len(used) == 1:
                        self.sections[cx, sy, cz] = (used, amounts, 0, b"")
                    elif len(used) <= 256:
                        bits = max(4, (len(used) - 1).bit_length())
                        if wide:
                            lookup = {index: n for n, index in enumerate(used)}
                            local = bytes([lookup[i] for i in section])
                        else:
                            table = bytearray(256)
                            for n, index in enumerate(used):
                                table[index] = n
                            local = section.translate(bytes(table))
                        self.sections[cx, sy, cz] = (used, amounts, bits, _pack_entries(local, bits))
                    else:
                        self.sections[cx, sy, cz] = (used, amounts, -1, section)

        self.packets: dict[int, bytes | None] = {}  # Encoded chunk packets per protocol

    def view_distance(self, spawn: tuple) -> int:
        """Chunks the client has to keep around the spawn chunk to hold the whole world."""
        cx, cz = int(spawn[0] // 16), int(spawn[2] // 16)
        distance = max(cx + 1, self.chunks_x - cx, cz + 1, self.chunks_z - cz)
        return max(2, min(32, distance))


def limbo_data_path() -> Path:
    return Path(os.path.abspath(__file__)).parent / LIMBO_DATA_FILE


_limbo_data_cache: dict = {"mtime": None, "data": None}


def limbo_block_data() -> dict | None:
    """The block state tables from limbo-data.json.gz, or None if it cannot be used."""
    path = limbo_data_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _limbo_data_cache["mtime"] != mtime:
        data = None
        try:
            data = json.loads(gzip.decompress(path.read_bytes()))
            if data.get("format") != LIMBO_DATA_FORMAT:
                log.warning(f"{path.name} is for a different version of MASS and cannot be used.")
                data = None
        except (OSError, ValueError, EOFError, AttributeError) as e:
            log.warning(f"Could not read {path.name}: {e}")
        _limbo_data_cache.update(mtime=mtime, data=data)
    return _limbo_data_cache["data"]


def limbo_data_complete() -> bool:
    """Whether limbo-data.json.gz exists and covers every supported protocol version."""
    data = limbo_block_data()
    return data is not None and all(str(p) in data.get("protocols", {}) for p in LIMBO_PLAY_IDS)


def fetch_limbo_data(config: dict) -> bool:
    """Download limbo-data.json.gz from next to the script on the update servers."""
    target = limbo_data_path()
    for url in config.get("auto_update_urls") or []:
        data_url = str(url).rsplit("/", 1)[0] + "/" + LIMBO_DATA_FILE
        try:
            r = requests.get(data_url, timeout=10)
            if r.status_code != 200:
                raise Exception(f"Returned status code {r.status_code}")
            if json.loads(gzip.decompress(r.content)).get("format") != LIMBO_DATA_FORMAT:
                raise Exception("It is for a different version of MASS")
            temp = target.with_name(target.name + ".tmp")
            temp.write_bytes(r.content)
            os.replace(temp, target)
            log.info(f"Downloaded {LIMBO_DATA_FILE}")
            return True
        except Exception as e:
            log.warning(f"Unable to download {data_url}: {e}")
    return False


def resolve_block_states(palette: list[str], blocks: dict, layouts: list) -> tuple[list[int], list[str]]:
    """Turn block state names into one version's numeric IDs.

    Returns the IDs and the names of blocks that version does not have (sent as air).
    Properties that are missing or not recognised keep the block's default value.
    """
    ids = []
    unknown = []
    for state in palette:
        name, _, props_text = state.partition("[")
        entry = blocks.get(name.removeprefix("minecraft:")) if name.startswith("minecraft:") or ":" not in name else None
        if entry is None:
            ids.append(0)
            if name not in unknown:
                unknown.append(name)
            continue
        props = dict(p.split("=", 1) for p in props_text.rstrip("]").split(",") if "=" in p)

        if isinstance(entry, dict):  # Block whose states are listed one by one
            key = ",".join(f"{k}={v}" for k, v in sorted(props.items()))
            ids.append(entry["states"].get(key, entry["default"]))
            continue

        base, layout_index, default = entry
        layout = layouts[layout_index]
        # A state's offset is its property values read as a mixed-radix number
        offset = 0
        remaining = default
        divisor = 1
        for _prop, values in layout:
            divisor *= len(values)
        for prop, values in layout:
            divisor //= len(values)
            choice, remaining = divmod(remaining, divisor)
            value = props.get(prop)
            if value in values:
                choice = values.index(value)
            offset = offset * len(values) + choice
        ids.append(base + offset)
    return ids, unknown


def limbo_frame(packet_id: int, payload: bytes = b"", compressed: bool = False) -> bytes:
    """Frame a packet, using the compressed packet format if compression was enabled."""
    if not compressed:
        return make_packet(packet_id, payload)
    data = encode_varint(packet_id) + payload
    if len(data) < LIMBO_COMPRESSION:
        body = b"\x00" + data
    else:
        body = encode_varint(len(data)) + zlib.compress(data)
    return encode_varint(len(body)) + body


async def limbo_read_packet(reader: asyncio.StreamReader, compressed: bool = False) -> tuple[int, bytes]:
    if not compressed:
        return await read_packet(reader)
    length = await read_varint(reader)
    if length <= 0 or length > 2**21:
        raise ValueError(f"Invalid packet length: {length}")
    body = await reader.readexactly(length)
    try:
        data_length, offset = decode_varint(body)
        if data_length == 0:
            data = body[offset:]
        elif 0 < data_length <= 2**23:
            data = zlib.decompressobj().decompress(body[offset:], data_length)
        else:
            raise ValueError(f"Invalid packet data length: {data_length}")
        packet_id, offset = decode_varint(data)
    except (IndexError, zlib.error) as e:
        raise ValueError(f"Invalid packet: {e}") from None
    return packet_id, data[offset:]


def build_chunk_packets(world: LimboWorld, protocol: int, data: dict) -> bytes:
    """Every Chunk Data and Update Light packet of the world, framed and compressed."""
    blocks = data["protocols"][str(protocol)]
    layouts = data["layouts"]
    ids, unknown = resolve_block_states(world.palette, blocks, layouts)
    if unknown:
        shown = ", ".join(unknown[:5]) + ("..." if len(unknown) > 5 else "")
        log.warning(f"Limbo world: {len(unknown)} block type(s) do not exist in protocol {protocol} "
                    f"and are shown as air: {shown}")

    # Bits per entry when a section does not use a palette: enough for every block state
    states = 0
    for entry in blocks.values():
        if isinstance(entry, dict):
            states = max(states, max(entry["states"].values()) + 1)
        else:
            count = 1
            for _prop, values in layouts[entry[1]]:
                count *= len(values)
            states = max(states, entry[0] + count)
    direct_bits = max(1, (states - 1).bit_length())

    has_length = protocol < PROTO_1_21_5  # Older versions prefix the entries with their length
    no_entries = encode_varint(0) if has_length else b""
    counts_fluids = protocol >= PROTO_26_1
    biomes = b"\x00" + encode_varint(0) + no_entries  # One biome everywhere: index 0 (plains)

    def section_header(block_count: int) -> bytes:
        return struct.pack(">h", block_count) + (b"\x00\x00" if counts_fluids else b"")

    def entries(packed: bytes) -> bytes:
        return (encode_varint(len(packed) // 8) if has_length else b"") + packed

    empty_section = section_header(0) + b"\x00" + encode_varint(0) + no_entries + biomes

    if protocol >= PROTO_1_21_5:
        heightmaps = encode_varint(1) + encode_varint(4) + encode_varint(37) + bytes(37 * 8)  # 4: MOTION_BLOCKING
    else:
        heightmaps = b"\x0a\x0c" + _nbt_string("MOTION_BLOCKING") + enc_i32(37) + bytes(37 * 8) + b"\x00"

    # Light: full sky light in every section (plus one below and one above the world), no block light
    light_sections = LIMBO_HEIGHT // 16 + 2
    bits = (1 << light_sections) - 1
    if protocol >= PROTO_26_3:  # Bit sets are sent as bytes (lowest bits first) instead of longs
        raw = bits.to_bytes((light_sections + 7) // 8, "little")
        mask = encode_varint(len(raw)) + raw
    else:
        mask = encode_varint(1) + enc_i64(bits)
    light = (mask + encode_varint(0) + encode_varint(0) + mask
             + encode_varint(light_sections) + (encode_varint(2048) + b"\xff" * 2048) * light_sections
             + encode_varint(0))

    below = -LIMBO_MIN_Y // 16  # Sections below Y=0, where the schematic starts
    total = LIMBO_HEIGHT // 16
    out = []
    for cz in range(-1, world.chunks_z + 1):
        for cx in range(-1, world.chunks_x + 1):  # Includes a border of empty chunks
            column = []
            for index in range(total):
                section = world.sections.get((cx, index - below, cz))
                if section is None:
                    column.append(empty_section)
                    continue
                used, amounts, bits, packed = section
                state_ids = [ids[i] for i in used]
                block_count = sum(n for n, state in zip(amounts, state_ids) if state != 0)
                if bits == 0:
                    states_data = b"\x00" + encode_varint(state_ids[0]) + no_entries
                elif bits > 0:
                    states_data = (enc_u8(bits) + encode_varint(len(state_ids))
                                   + b"".join(encode_varint(s) for s in state_ids) + entries(packed))
                else:
                    states_data = enc_u8(direct_bits) + entries(_pack_entries([ids[i] for i in packed], direct_bits))
                column.append(section_header(block_count) + states_data + biomes)
            sections = b"".join(column)
            payload = (enc_i32(cx) + enc_i32(cz) + heightmaps + encode_varint(len(sections)) + sections
                       + encode_varint(0) + light)  # No block entities
            out.append(limbo_frame(LIMBO_PLAY_IDS[protocol]["chunk"], payload, True))
    return b"".join(out)


_limbo_world_cache: dict = {"key": None, "world": None, "lock": None}
_limbo_warned: set[str] = set()


def _limbo_warn_once(message: str):
    if message not in _limbo_warned:
        _limbo_warned.add(message)
        log.warning(message)


async def limbo_world_get(config: dict, protocol: int | None = None) -> tuple["LimboWorld", bytes] | None:
    """The limbo world and its chunk packets for a protocol version.

    Returns None if no limbo_world is set or it cannot be used, in which case the
    player gets the empty limbo. The schematic is read again when the file changes.
    Called without a protocol, it only loads the schematic.
    """
    name = config.get("limbo_world")
    if not name:
        return None
    path = Path(config["server_dir"]) / str(name)
    try:
        stat = path.stat()
    except OSError:
        _limbo_warn_once(f"limbo_world file not found: {path}")
        return None
    key = (str(path), stat.st_mtime, stat.st_size)

    cache = _limbo_world_cache
    if cache["lock"] is None:
        cache["lock"] = asyncio.Lock()
    async with cache["lock"]:
        if cache["key"] != key:
            world = None
            try:
                world = await asyncio.to_thread(LimboWorld, path)
                log.info(f"Loaded limbo world {path.name}: {world.width}x{world.height}x{world.length} blocks")
            except Exception as e:
                log.warning(f"Could not load limbo_world {path}: {e}")
            cache.update(key=key, world=world)
        world = cache["world"]
        if world is None:
            return None
        if protocol is None:
            return world, b""

        if protocol not in world.packets:
            packets = None
            data = limbo_block_data()
            if data is None:
                _limbo_warn_once(f"limbo_world needs {LIMBO_DATA_FILE} next to this script. "
                                 "Download it from where you got this script. Using the empty limbo until then.")
                return None
            if str(protocol) not in data.get("protocols", {}):
                _limbo_warn_once(f"{LIMBO_DATA_FILE} has no block data for protocol {protocol}; "
                                 "those players get the empty limbo.")
            else:
                try:
                    packets = await asyncio.to_thread(build_chunk_packets, world, protocol, data)
                except Exception as e:
                    log.warning(f"Could not build the limbo world for protocol {protocol}: {e}")
            world.packets[protocol] = packets
        packets = world.packets[protocol]
        return (world, packets) if packets is not None else None


def limbo_gamemode(config: dict) -> int:
    value = config.get("limbo_gamemode")
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 3:
        return value
    mode = LIMBO_GAMEMODES.get(str(value).strip().lower())
    if mode is None:
        _limbo_warn_once(f"limbo_gamemode {value!r} is not survival, creative, adventure or spectator; using spectator.")
        return 3
    return mode


def limbo_time(config: dict) -> int:
    value = config.get("limbo_time")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 24000:
        return int(value)
    ticks = LIMBO_TIMES.get(str(value).strip().lower())
    if ticks is None:
        _limbo_warn_once(f"limbo_time {value!r} is not day, noon, night, midnight or 0 - 24000; using day.")
        return LIMBO_TIMES["day"]
    return ticks


def limbo_spawn_point(config: dict, world: "LimboWorld | None") -> tuple[float, float, float, float, float]:
    """Where the player appears: x, y, z, yaw, pitch."""
    if world is None:
        return 0.5, float(LIMBO_SPAWN_Y), 0.5, 0.0, 0.0
    value = config.get("limbo_spawn")
    if value is None:
        return world.spawn
    if (isinstance(value, (list, tuple)) and len(value) in (3, 5)
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        x, y, z, yaw, pitch = (list(map(float, value)) + [0.0, 0.0])[:5]
        return x, y, z, yaw, pitch
    _limbo_warn_once(f"limbo_spawn {value!r} is not [x, y, z] or [x, y, z, yaw, pitch]; using the middle of the world.")
    return world.spawn


# ----- Registries ------------------------------------------------------------

def limbo_registries(protocol: int) -> list[tuple[str, list[str]]]:
    """Registries and entry names.

    Only names are sent; the client fills in the data from its own "minecraft:core" pack.
    """
    climate = ["cold", "temperate", "warm"]
    reg: dict[str, list[str]] = {
        "dimension_type": ["overworld"],
        "worldgen/biome": ["plains"],
        "damage_type": limbo_damage_types(protocol),
        "wolf_variant": ["ashen", "black", "chestnut", "pale", "rusty", "snowy", "spotted", "striped", "woods"],
    }
    if protocol >= PROTO_1_21:
        reg["painting_variant"] = ["kebab"]
    if protocol >= PROTO_1_21_5:
        reg["cat_variant"] = ["all_black", "black", "british_shorthair", "calico", "jellie", "persian",
                              "ragdoll", "red", "siamese", "tabby", "white"]
        reg["chicken_variant"] = climate
        reg["cow_variant"] = climate
        reg["frog_variant"] = climate
        reg["pig_variant"] = climate
        reg["wolf_sound_variant"] = ["angry", "big", "classic", "cute", "grumpy", "puglin", "sad"]
    if protocol >= PROTO_1_21_11:
        reg["zombie_nautilus_variant"] = ["temperate", "warm"]
        reg["timeline"] = ["day", "early_game", "moon", "villager_schedule"]
    if protocol >= PROTO_26_1:
        reg["cat_sound_variant"] = ["classic", "royal"]
        reg["chicken_sound_variant"] = ["classic", "picky"]
        reg["cow_sound_variant"] = ["classic", "moody"]
        reg["pig_sound_variant"] = ["big", "classic", "mini"]
        reg["world_clock"] = ["overworld", "the_end"]
        reg["instrument"] = ["ponder_goat_horn"]
        reg["jukebox_song"] = ["11", "13", "5", "blocks", "cat", "chirp", "creator", "creator_music_box",
                               "far", "lava_chicken", "mall", "mellohi", "otherside", "pigstep", "precipice",
                               "relic", "stal", "strad", "tears", "wait", "ward"]
        reg["trim_material"] = ["amethyst", "copper", "diamond", "emerald", "gold", "iron", "lapis",
                                "netherite", "quartz", "redstone", "resin"]
        reg["banner_pattern"] = ["base"]
    if protocol >= PROTO_26_2:
        reg["jukebox_song"] = reg["jukebox_song"] + ["bounce"]
        reg["sulfur_cube_archetype"] = list(_SULFUR_CUBE_ARCHETYPES)
    if protocol >= PROTO_26_3:
        reg["block_transformer"] = ["axe", "hoe", "shovel"]
        reg["decorated_pot_pattern"] = ["angler", "archer", "arms_up", "blade", "brewer", "burn", "danger",
                                        "explorer", "flow", "friend", "guster", "heart", "heartbreak", "howl",
                                        "miner", "mourner", "plenty", "prize", "scrape", "sheaf", "shelter",
                                        "skull", "snort"]
    return [("minecraft:" + name, ["minecraft:" + e for e in entries]) for name, entries in reg.items()]


def limbo_tags(protocol: int) -> list[tuple[str, list[str]]]:
    """Tags newer clients expect to exist (1.21.11+). They are sent empty."""
    tags: dict[str, list[str]] = {}
    if protocol >= PROTO_1_21_11:
        tags["timeline"] = ["in_overworld", "in_nether", "in_end", "universal"]
    if protocol >= PROTO_26_1:
        tags["banner_pattern"] = ["no_item_required"] + [
            "pattern_item/" + n for n in ("bordure_indented", "creeper", "field_masoned", "flow", "flower",
                                          "globe", "guster", "mojang", "piglin", "skull")
        ]
        tags["damage_type"] = ["bypasses_shield", "is_explosion", "is_fire"]
    if protocol >= PROTO_26_2:
        tags["block"] = ["infiniburn_overworld", "infiniburn_nether", "infiniburn_end"]
        # Each sulfur cube archetype refers to an item tag of the same name; tags are
        # never taken from the client's built-in pack, so they have to be sent.
        tags["item"] = ["sulfur_cube_archetype/" + n for n in _SULFUR_CUBE_ARCHETYPES]
    return [("minecraft:" + name, ["minecraft:" + t for t in names]) for name, names in tags.items()]


# ----- Packet builders -------------------------------------------------------

def parse_login_start_uuid(data: bytes) -> uuidlib.UUID | None:
    """Return the UUID the client sent in Login Start (name, then UUID)."""
    try:
        _name, offset = decode_string(data)
        raw = data[offset : offset + 16]
        return uuidlib.UUID(bytes=raw) if len(raw) == 16 else None
    except (IndexError, ValueError):
        return None


def build_login_success(protocol: int, player_uuid: uuidlib.UUID, name: str) -> bytes:
    out = player_uuid.bytes + encode_string(name) + encode_varint(0)  # No profile properties
    if protocol <= PROTO_1_21:
        out += enc_bool(False)  # Strict error handling
    if protocol >= PROTO_26_2:
        out += uuidlib.uuid4().bytes  # Session ID
    return out


def build_join_game(protocol: int, gamemode: int, view_distance: int) -> bytes:
    entity_id = enc_i32(1)  # 26.2+ rejects entity ID 0
    world = encode_string(LIMBO_WORLD)
    no, yes = enc_bool(False), enc_bool(True)

    out = (entity_id + no + encode_varint(1) + world + encode_varint(1)
           + encode_varint(view_distance) + encode_varint(view_distance)
           + no + yes + no)  # reducedDebugInfo, enableRespawnScreen, doLimitedCrafting
    out += encode_varint(0)  # Dimension type: index into the registry
    out += world + enc_i64(0)
    if protocol >= PROTO_26_3:
        out += encode_varint(gamemode) + encode_varint(0)  # 0 = no previous game mode
    else:
        out += enc_u8(gamemode) + enc_i8(-1)
    out += no + yes + no + encode_varint(0)  # isDebug, isFlat, no death location, portal cooldown
    if protocol >= PROTO_1_21_2:
        out += encode_varint(63)  # Sea level
    if protocol >= PROTO_26_2:
        out += no  # Online mode
    out += no  # Enforces secure chat
    return out


def build_abilities(gamemode: int, frozen: bool) -> bytes:
    """Player abilities. Always invulnerable; frozen players hover in place."""
    if frozen:
        return enc_i8(0x07) + enc_f32(0.0) + enc_f32(0.1)  # Invulnerable, flying, at no speed
    flags = 0x01
    if gamemode == 1:
        flags |= 0x04 | 0x08  # May fly, creative mode
    elif gamemode == 3:
        flags |= 0x02 | 0x04  # Flying, may fly
    return enc_i8(flags) + enc_f32(0.05) + enc_f32(0.1)


def build_position(protocol: int, spawn: tuple, teleport_id: int = 1) -> bytes:
    x, y, z, yaw, pitch = spawn
    if protocol >= PROTO_1_21_2:
        return (encode_varint(teleport_id) + enc_f64(x) + enc_f64(y) + enc_f64(z)
                + enc_f64(0) + enc_f64(0) + enc_f64(0) + enc_f32(yaw) + enc_f32(pitch) + enc_i32(0))
    return (enc_f64(x) + enc_f64(y) + enc_f64(z) + enc_f32(yaw) + enc_f32(pitch) + enc_i8(0)
            + encode_varint(teleport_id))


def build_spawn_position(protocol: int, spawn: tuple) -> bytes:
    x, y, z, yaw, pitch = spawn
    pos = enc_position(int(x // 1), int(y // 1), int(z // 1))
    if protocol >= PROTO_1_21_9:
        return encode_string(LIMBO_WORLD) + pos + enc_f32(yaw) + enc_f32(pitch)
    return pos + enc_f32(yaw)


def build_time(protocol: int, ticks: int) -> bytes:
    """Set the time of day, with the clock stopped."""
    if protocol >= PROTO_26_1:
        # One clock update: the overworld clock (index 0 of the world_clock registry),
        # total ticks (VarLong), partial tick, rate (0 = stopped)
        return (enc_i64(ticks) + encode_varint(1) + encode_varint(0)
                + encode_varint(ticks) + enc_f32(0.0) + enc_f32(0.0))
    if protocol >= PROTO_1_21_2:
        return enc_i64(ticks) + enc_i64(ticks) + enc_bool(False)  # False: time does not advance
    return enc_i64(ticks) + enc_i64(-(ticks % 24000 or 24000))  # Negative: time does not advance


LIMBO_BOSSBAR_COLORS = ("pink", "blue", "red", "green", "yellow", "purple", "white")


def build_bossbar_add(bar_id: uuidlib.UUID, title: str, progress: float, color: str) -> bytes:
    """Boss Bar packet, action 0 (add): title, progress, color, style 0 (solid), no flags."""
    color_id = LIMBO_BOSSBAR_COLORS.index(color) if color in LIMBO_BOSSBAR_COLORS else 4
    return (bar_id.bytes + encode_varint(0) + encode_text(title) + enc_f32(progress)
            + encode_varint(color_id) + encode_varint(0) + enc_u8(0))


def build_bossbar_title(bar_id: uuidlib.UUID, title: str) -> bytes:
    """Boss Bar packet, action 3 (update title)."""
    return bar_id.bytes + encode_varint(3) + encode_text(title)


def build_bossbar_progress(bar_id: uuidlib.UUID, progress: float) -> bytes:
    """Boss Bar packet, action 2 (update progress)."""
    return bar_id.bytes + encode_varint(2) + enc_f32(progress)


def limbo_startup_progress(server_dir: str, start_time: float | None) -> float:
    """How far through the expected startup time the server is, from 0 to 1."""
    avg = get_avg_startup(server_dir)
    if not avg or start_time is None:
        return 0.0
    return min(1.0, (time.monotonic() - start_time) / avg)


def build_title_packets(ids: dict, title: str, subtitle: str, actionbar: str, frame=make_packet) -> bytes:
    """Title timing, subtitle, title and action bar packets."""
    times = enc_i32(0) + enc_i32(60) + enc_i32(20)  # Fade in, stay, fade out (ticks)
    return (frame(ids["times"], times)
            + frame(ids["subtitle"], encode_text(subtitle))
            + frame(ids["title"], encode_text(title))
            + frame(ids["actionbar"], encode_text(actionbar)))


def build_known_packs(protocol: int) -> bytes:
    versions = LIMBO_CORE_PACKS[protocol]
    out = encode_varint(len(versions))
    for version in versions:
        out += encode_string("minecraft") + encode_string("core") + encode_string(version)
    return out


def build_registry_data(registry: str, entries: list[str]) -> bytes:
    out = encode_string(registry) + encode_varint(len(entries))
    for entry in entries:
        out += encode_string(entry) + enc_bool(False)  # No data: use the client's built-in pack
    return out


def build_update_tags(tags: list[tuple[str, list[str]]]) -> bytes:
    out = encode_varint(len(tags))
    for registry, names in tags:
        out += encode_string(registry) + encode_varint(len(names))
        for name in names:
            out += encode_string(name) + encode_varint(0)  # Empty tag
    return out


# ----- Session ---------------------------------------------------------------

def limbo_supported(config: dict, protocol: int) -> bool:
    """Whether a connecting client should be put in the limbo instead of being kicked."""
    if str(config.get("join_method", "kick")).lower() != "limbo":
        return False
    return protocol in LIMBO_PLAY_IDS


def limbo_transfer_target(config: dict, client_host: str | None, client_port: int | None) -> tuple[str, int] | None:
    """Address to transfer a player to: the configured one, else the one they joined with."""
    host = config.get("limbo_transfer_host")
    if not host:
        # Forge and proxies append extra data after a NUL; SRV targets end with a dot
        host = (client_host or "").split("\0", 1)[0].rstrip(".")
    host = str(host).strip()
    port = config.get("limbo_transfer_port") or client_port

    if not host or len(host) > 255 or not re.fullmatch(r"[A-Za-z0-9._:\-\[\]]+", host):
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    if not 0 < port < 65536:
        return None
    return host, port


async def _limbo_expect(reader: asyncio.StreamReader, packet_id: int, compressed: bool = False,
                        timeout: float = 20) -> bytes:
    """Read packets until one with the given ID arrives, ignoring the others."""
    async def _read() -> bytes:
        while True:
            pid, data = await limbo_read_packet(reader, compressed)
            if pid == packet_id:
                return data
    return await asyncio.wait_for(_read(), timeout=timeout)


async def _limbo_watch(reader: asyncio.StreamReader, compressed: bool = False,
                       move_ids: tuple[int, ...] = (), fell: asyncio.Event | None = None):
    """Read and drop everything the client sends, until it disconnects.

    Sets `fell` when the player's position drops below LIMBO_VOID_Y.
    """
    below = False
    try:
        while True:
            pid, data = await limbo_read_packet(reader, compressed)
            # Position packets start with x, y, z; the two kinds are 25 and 33 bytes long
            if pid in move_ids and len(data) in (25, 33):
                y = struct.unpack_from(">d", data, 8)[0]
                if y < LIMBO_VOID_Y:
                    if not below:
                        fell.set()
                    below = True
                else:
                    below = False
    except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
        pass


async def run_limbo(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    protocol: int,
    player_name: str,
    player_uuid: uuidlib.UUID,
    target: tuple[str, int],
    config: dict,
    server_mgr: "ServerManager",
):
    """Hold a player in the fake server until the real one is ready, then transfer them."""
    ids = LIMBO_PLAY_IDS[protocol]

    loaded = await limbo_world_get(config, protocol)
    world, chunk_packets = loaded if loaded else (None, b"")
    # Chunks are large, so packets are compressed when a world is sent
    compressed = world is not None
    gamemode = limbo_gamemode(config)
    spawn = limbo_spawn_point(config, world)

    def frame(packet_id: int, payload: bytes = b"") -> bytes:
        return limbo_frame(packet_id, payload, compressed)

    def send(packet_id: int, payload: bytes = b""):
        writer.write(frame(packet_id, payload))

    async def drain():
        """Wait for the client to receive what was sent; drop clients that stop reading."""
        try:
            await asyncio.wait_for(writer.drain(), timeout=LIMBO_DRAIN_TIMEOUT)
        except asyncio.TimeoutError:
            log.info(f"Disconnecting {player_name} from the limbo: not receiving data")
            writer.transport.abort()  # close() would wait for the unsent data to go out
            raise ConnectionError("client stopped reading") from None

    # --- Login ---
    if compressed:
        writer.write(make_packet(0x03, encode_varint(LIMBO_COMPRESSION)))  # Set Compression
    send(0x02, build_login_success(protocol, player_uuid, player_name))
    await drain()

    # --- Configuration ---
    known_packs_id, tags_id = (0x0F, 0x0E) if protocol >= PROTO_26_3 else (0x0E, 0x0D)
    await _limbo_expect(reader, 0x03, compressed)  # Login Acknowledged
    send(known_packs_id, build_known_packs(protocol))
    await drain()
    reply = await _limbo_expect(reader, 0x07, compressed)  # Client's known packs
    if decode_varint(reply)[0] < 1:
        log.warning(f"{player_name}'s client does not have the vanilla data pack for protocol {protocol}; cannot enter limbo.")
        send(0x02, encode_text(apply_placeholders(config["kick_message"], config["server_dir"], server_mgr._start_time)))
        await drain()
        return
    for registry, entries in limbo_registries(protocol):
        send(0x07, build_registry_data(registry, entries))
    tags = limbo_tags(protocol)
    if tags:
        send(tags_id, build_update_tags(tags))
    send(0x03)  # Finish Configuration
    await drain()
    await _limbo_expect(reader, 0x03, compressed)  # Acknowledge Finish Configuration

    # --- Play ---
    view_distance = world.view_distance(spawn) if world else 2
    send(ids["join"], build_join_game(protocol, gamemode, view_distance))
    send(ids["abilities"], build_abilities(gamemode, frozen=world is None))
    send(ids["pos"], build_position(protocol, spawn))
    send(ids["spawn"], build_spawn_position(protocol, spawn))
    send(ids["time"], build_time(protocol, limbo_time(config)))
    send(ids["event"], enc_u8(13) + enc_f32(0.0))  # Start waiting for chunks (closes the loading screen)
    if world:
        send(ids["center"], encode_varint(int(spawn[0] // 16)) + encode_varint(int(spawn[2] // 16)))
        writer.write(chunk_packets)
    await drain()
    log.info(f"{player_name} is waiting in the limbo (protocol {protocol})")

    loop = asyncio.get_running_loop()
    fell = asyncio.Event()
    watch_task = asyncio.create_task(
        _limbo_watch(reader, compressed, LIMBO_MOVE_IDS.get(protocol, ()) if world else (), fell))
    ready_task = asyncio.create_task(server_mgr._ready_event.wait())
    fell_task = None
    try:
        tick = 0
        teleports = 1
        next_tick = loop.time()
        bossbar_id = uuidlib.uuid4()
        bossbar_shown = False
        next_bar = next_tick  # The boss bar's progress is updated every game tick (1/20 s)
        fell_task = asyncio.create_task(fell.wait())
        while not server_mgr._ready_event.is_set():
            if watch_task.done():
                log.info(f"{player_name} left the limbo")
                return
            if not server_mgr._starting:
                # Startup was abandoned (e.g. startup_timeout reached)
                log.info(f"Removing {player_name} from the limbo: the server failed to start")
                send(ids["disconnect"], encode_text(config["limbo_failed_kick_message"]))
                await drain()
                return

            if fell.is_set():
                # Fell out of the world: back to the spawn
                fell.clear()
                fell_task = asyncio.create_task(fell.wait())
                teleports += 1
                send(ids["pos"], build_position(protocol, limbo_spawn_point(config, world), teleports))

            if loop.time() >= next_tick:
                def text(key: str) -> str:
                    return apply_placeholders(str(config.get(key) or ""), config["server_dir"], server_mgr._start_time)

                writer.write(build_title_packets(ids, text("limbo_title"), text("limbo_subtitle"),
                                                 text("limbo_actionbar"), frame))

                # Boss bar: added on the first tick, or when it is turned on by a config reload
                bossbar = text("limbo_bossbar") if config.get("limbo_bossbar") else None
                progress = limbo_startup_progress(config["server_dir"], server_mgr._start_time)
                if bossbar is not None and not bossbar_shown:
                    color = str(config.get("limbo_bossbar_color") or "yellow").strip().lower()
                    if color not in LIMBO_BOSSBAR_COLORS:
                        _limbo_warn_once(f"limbo_bossbar_color {color!r} is not one of {', '.join(LIMBO_BOSSBAR_COLORS)}; using yellow.")
                    send(ids["boss"], build_bossbar_add(bossbar_id, bossbar, progress, color))
                    bossbar_shown = True
                elif bossbar is not None:
                    send(ids["boss"], build_bossbar_title(bossbar_id, bossbar))
                elif bossbar_shown:
                    send(ids["boss"], bossbar_id.bytes + encode_varint(1))  # Remove
                    bossbar_shown = False
                if tick % 5 == 0:
                    send(ids["keepalive"], enc_i64(tick))
                tick += 1
                next_tick += 1

            if bossbar_shown and loop.time() >= next_bar:
                send(ids["boss"], build_bossbar_progress(
                    bossbar_id, limbo_startup_progress(config["server_dir"], server_mgr._start_time)))
                next_bar += 0.05
                if next_bar < loop.time():  # Skip ticks that were missed rather than catching up on them
                    next_bar = loop.time() + 0.05
            await drain()

            # Sleep until the next update, or until the server is ready, the player falls or leaves
            wake = min(next_tick, next_bar) if bossbar_shown else next_tick
            await asyncio.wait({ready_task, watch_task, fell_task},
                               timeout=max(0.0, wake - loop.time()),
                               return_when=asyncio.FIRST_COMPLETED)

        # --- Hand over ---
        if watch_task.done():
            return
        log.info(f"Transferring {player_name} from the limbo to {target[0]}:{target[1]}")
        send(ids["transfer"], encode_string(target[0]) + encode_varint(target[1]))
        await drain()

        # Give the client a moment to act on it before the connection is closed
        try:
            await asyncio.wait_for(asyncio.shield(watch_task), timeout=3)
        except asyncio.TimeoutError:
            pass
    finally:
        watch_task.cancel()
        ready_task.cancel()
        if fell_task is not None:
            fell_task.cancel()


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
            # Whitelist/Blacklist check 
            whitelist = config["ip_listing_whitelist"]
            blacklist = config["ip_listing_blacklist"]

            in_whitelist = in_blacklist = False

            if whitelist or blacklist:
                in_whitelist = any(fnmatch.fnmatch(ip, p) for p in whitelist)
                in_blacklist = any(fnmatch.fnmatch(ip, p) for p in blacklist)

            # Allow/Block whitelisted/blacklisted IPs
            if in_whitelist:
                raise UserWarning("in whitelist")
            if in_blacklist:
                raise ConnectionRefusedError(f"in blacklist")

            # Allow local IPs
            if ip in LOCAL_IPS:
                raise UserWarning("local IP")
            
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
          
            # SmartMode
            if config["ip_listing_smartmode"]:
                smdata = requests.get(f"https://api.sefinek.net/api/v2/ip-checker/{ip}").json()

                # Autoblock Malicious and TOR
                if smdata["malicious"]:
                    raise ConnectionRefusedError(f"malicious")
                if smdata["tor"]:
                    raise ConnectionRefusedError(f"tor connection")

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
        intent_offset = offset
        next_state, offset = decode_varint(handshake_data, offset)

        # Intent 3 is a client arriving through a Transfer packet (1.20.5+), e.g. from the limbo.
        # Servers reject it unless accepts-transfers is enabled, so it is passed on as a normal login.
        if next_state == 3:
            handshake_data = handshake_data[:intent_offset] + encode_varint(2)

        handshake_packet = make_packet(0x00, handshake_data)

        if next_state == 1:
            await handle_status(reader, writer, handshake_packet, config, server_mgr)
        elif next_state in (2, 3):
            await handle_login(reader, writer, handshake_packet, protocol_version, config, server_mgr, addr, smdata, citydata, _server_address, _server_port)
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

async def handle_login(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, handshake_packet, protocol_version, config, server_mgr: ServerManager, addr, smdata, citydata, client_host: str | None = None, client_port: int | None = None):
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
            # Limbo join method: wait in a fake server instead of being kicked
            if status in ("started", "starting") and limbo_supported(config, protocol_version):
                target = limbo_transfer_target(config, client_host, client_port)
                player_uuid = parse_login_start_uuid(login_data)
                if target is None:
                    log.warning(f"Cannot work out an address to transfer {player_name} to ({client_host!r}); set limbo_transfer_host. Kicking instead.")
                elif player_uuid is not None:
                    return await run_limbo(reader, writer, protocol_version, player_name, player_uuid, target, config, server_mgr)

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
                _limbo_warned.clear()
                asyncio.create_task(limbo_world_get(config))
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

    # The limbo world needs the block data file; fetch it if it is missing or outdated
    if config.get("limbo_world") and not limbo_data_complete():
        fetch_limbo_data(config)

    log.info(f"Proxy listening on {config['listen_host']}:{config['listen_port']}")
    log.info(f"Server (redirect) port: {config['server_port']}")
    log.info(f"Start command: {config['start_command']}")
    log.info(f"Auto-stop: after {config['auto_stop_empty_minutes']}m empty")

    asyncio.create_task(watch_config(config))
    asyncio.create_task(limbo_world_get(config))  # Read the limbo world now, not when the first player joins

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
