"""
Optimization mods downloader for Fabric MC

This is a file that takes a part of the serversetup.py file to only download optimization mods
"""

import requests, os

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
            return print(f"Downloaded {projectID}")
    else:
        return print(f"Failed to locate a version for {projectID}")


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
    "servercore", # Some optimizations like PaperMC mainly for SMPs
]

for mod in MODS:
    downloadMod(mod)

print("Files are downloaded!")