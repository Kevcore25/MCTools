"""
Script to create a Minecraft fabric server with ease!

It automatically accepts the EULA, so you must agree to the EULA (https://www.minecraft.net/en-us/eula) before using it.
"""

import os
import requests
from threading import Thread
from hashlib import sha256

# Get all the minecraft versions and ask the user which Minecraft version to downloiad
versionsapi = requests.get(f"https://meta.fabricmc.net/v2/versions/game").json()

# Convert list into dictionary
versions = []
for version in versionsapi:
    versions.append(version['version'])

while True:
    version = input("Minecraft version: ")
    if version in versions: break
    else:
        print("Try again! Not a valid version!")


def downloadMod(projectID: str):
    versions = requests.get(f"https://api.modrinth.com/v2/project/{projectID}/version").json()
    for v in versions:
        if version in v["game_versions"] and "fabric" in v["loaders"]:
            downloadLink = v["files"][0]
            with requests.get(downloadLink["url"], stream=True) as r:
                with open(os.path.join("mods", downloadLink["filename"]), 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): 
                        f.write(chunk)
            return

def download():
    # Get the fabric loader 
    loaders = requests.get(f"https://meta.fabricmc.net//v2/versions/loader/{version}").json()
    loader = loaders[0]["loader"]["version"]

    # Get installer loader
    installerVer = requests.get("https://meta.fabricmc.net/v2/versions/installer").json()[0]["version"]

    with requests.get(f"https://meta.fabricmc.net/v2/versions/loader/{version}/{loader}/{installerVer}/server/jar", stream=True) as r:
        with open("fabric.jar", 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
                f.write(chunk)

    # Get mods 
    if "mods" not in os.listdir():
        os.mkdir("mods")

    # Download optimization mods
    MODS = [
        "lithium", # General-purpose optimization mod that minimally affects the vanilla experience 
        "fabric-api", # Library for mods
        "krypton", # Network optimizations
        "ferrite-core", # Memory optimizations
        "noisium", # World generation optimizations
        "c2me-fabric", # Chunk performance improvements
        "scalablelux", # Light optimizations
        "vmp-fabric", # Improvements for higher player counts
        "alternate-current", # Redstone optimizations
        "threadtweak", # Reworks scheduling, which COULD be invasive and can be disabled for a more vanilla experience.
        "servercore", # Some optimizations like PaperMC mainly for SMPs. Can be disabled for a more vanilla experience.
    ]

    for mod in MODS:
        downloadMod(mod)

    print("Files are downloaded!")

# Start the downloads in a new thread so the config can continue
Thread(target = download).start()
print("Server files are now being downloaded... Asking for configuration if required now.")

if "eula.txt" not in os.listdir():
    with open("eula.txt", "x") as f:
        f.write("eula=true")

if "server.properties" not in os.listdir():
    port = int(input("Server port: "))
    motd = input("MOTD: ")

    with open("server.properties", "x") as f:
        f.write(f"""#Minecraft server properties
allow-flight=true
motd={motd}
online-mode={input("Online mode? (true or false): ")}
rcon.password={sha256(bytes(str(id(port) * id(motd)), 'utf-8')).hexdigest()}
rcon.port={port + 1}
server-port={port}
enable-rcon=true""")

if "start.sh" not in os.listdir():
    ram = input("Amount of RAM (e.g. 1024M or 1G): ")
    with open("start.bat" if os.name == 'nt' else "start.sh", "x") as f:
        f.write(f"java -Xmx{ram} -Xms{ram} -server -jar fabric.jar nogui")
        
print("Configuration options are set! Run the start file to start the server!")