# MCTools
This is a collection of scripts that I made intended for myself to run my Minecraft servers.

However, other than `KMCEv3.py`, these scripts may prove useful for others besides me.

Some scripts (such as adaptive-start.py) are highly configurable and can be used by anyone.

## How to use
Typically, I do these steps in order:
1. Clone the repository
2. Rename the directory to the server directory name
3. Run the setup script
4. Run the adaptive starter, and then editing its config file
5. Restart the adaptive starter and keep it running constantly

I have a custom script that integrates all of my Minecraft servers together (`KMCEv3.py`) which I also leave runninmcr.py: A very basic script that uses mcrcon to connect to the server and run commands and see its real-time logs, essentially emulating the server's console when it does not exist.g; however, to make my scripts also accessible to others who may be interested, I left `KMCEv3.py` as a separate file on purpose instead of integrating it with the adaptive starter.
KMCEv3 itself has two classes (`KMCE` and `KCKMCE`) where `KCKMCE` is a superclass of `KMCE` that contains the integrations to my servers. For others, `KCKMCE` should not be used unless you plan to setup your own KMCE global server.

## What each script does
- `adaptive-start.py`: A script that spins a proxy server to allow various interactions when the server is offline. The main intention is to allow players to automatically start the server when needed, and automatically stop the server when inactive after a while.
- `mcr.py`: A very basic script that uses mcrcon to connect to the server and run commands and see its real-time logs, essentially emulating the server's console when it does not exist.
- `ServerSetupScript.py`: A script that allows for a basic server setup with just a few prompts.
- `OptimizationsDownloader.py`: A script that uses a portion of the server setup script to only download server optimization mods.
- `KMCEv3.py`: A custom monitoring script that integrates Python to a vanilla server using logs and RCON.
