password = r""
port = 25575
logfile = r"logs/latest.log"

"""
Opens a console session using RCON while constantly checking for file updates
ONLY works on bukkit
CONFIG is DIRECTLY rewritten to this file 
"""

version = 2.4
versionUpdates = """
V.2 features:
- Fixes linux terminal error (still doesn't work on some)
- Adds "exit", ".exit" external command
- Adds partial KMCL scripting (no ;player; or ;msg;)
- Changes title even if AutoConfig does not run (2.1)
- Adds ".delay <value>" command, adjusting log refresh rate (2.1)
- Adds ".log <amount>", showing the last x lines of the log file (2.2)
- Adds ".clear", using the "cls" or "clear" OS command (2.2)
- Adds ".help", showing all external commands (2.2)
- Checks if AutoConfig and Config have conflicts (2.2)
- Adds .autodelay command and fixes 2 CMDs being ran at once (2.3)
- Every . will use the last CMD ran (e.g. .. = 2nd last cmd ran, V.2.3)
"""

import os, sys, threading # required
import re, traceback # KMCL
from mcrcon import MCRcon # required
print(f"""
{"":=>{os.get_terminal_size()[0]}}
MCRcon CMD
from KMCE tools
Version: {version}

A basic interface to run commands as RCON as well as displaying updating log
{versionUpdates}
{"":=>{os.get_terminal_size()[0]}}""")

delay = 0.1

# New Last CMD to run the last CMD
lastCMDs = []

CMDHELP = {
    ".exit": "Exits MCRcon CMD safely",
    ".delay <value>": "Changes the delay of fetching the log file",
    ".log <amount>": "Prints the last <amount> lines of the log file. If <amount> is invaild (e.g. not specified), then amount is set to -1 (entire log file)",
    ".clear": "Clears the terminal screen",
    ".autodelay": "EXPERIMENTAL: Automatically adjusts the delay of log refresh rate based on the amount of CPU% the current program is using. Once enabled, you cannot go back and .delay stops working",
    ".help": "Shows this command"
}

# EXPERIMENTAL: Auto adjust delay depending on the CPU usage of the process
def adjustDelay():
    threading.Timer(1, adjustDelay).start()

    global delay 

    currentCpu = process.cpu_percent(1)

    if currentCpu < 0.1:
        delay = round(delay/2, 2)
    elif currentCpu > 0.1:
        delay = round(delay*2, 2)




def findLogFile():
    global logfile
    logfile = "logs/latest.log"
def autoConfig():
    # AutoConfig by KMCE allows instant setup if the server is running bukkit
    try:
        # get logfile
        logfile = "logs/latest.log"

        with open(logfile, "r") as f: f.read() # verify the file is there

        # get port and password
        prop = {}
        with open("server.properties", "r") as f:
            for line in f.readlines():
                
                l = line.replace("\n", '').split("=")
                if len(l) > 1:
                    prop[l[0]] = l[1]
        port = prop["rcon.port"]
        password = prop["rcon.password"]

        return [True, logfile, port, password]
    except Exception as e:
        print(f"Unable to use AutoConfig by KMCE: {e}")
        return [False]
    
try:
    prop = {}
    with open("server.properties", "r") as f:
        for line in f.readlines():
            
            l = line.replace("\n", '').split("=")
            if len(l) > 1:
                prop[l[0]] = l[1]

    # change title
    if sys.platform.startswith('win'):      os.system(f'title MCR CMD: {prop["level-name"]}')
    elif sys.platform.startswith('linux'):  os.system(f'echo -en "\033]0;MCR CMD: {prop["level-name"]}\a"')
except: pass


try:
    c = autoConfig()
    if c[0]:
        p = c[2].rstrip()
        pw = c[3].rstrip()

        # Check if the user already chose to use the current config
        try:
            with open("useCurrentConfig.mcr", "r") as f: f
        except FileNotFoundError:
            if str(p) != str(port) or pw != password:
                if "y" in input(f"""{"":=>{os.get_terminal_size()[0]}}
WARNING: The current config of the file does not match the config found by AutoConfig.
AutoConfig:     Port: {p} | Password: {pw}
Current:        Port: {port} | Password: {password}
If you include (type) "y" and press enter, you will be redirected to config setup
If you do not include "y", the current config will be used
{"":=>{os.get_terminal_size()[0]}}"""):
                    # with open("useCurrentConfig.mcr", "w") as f:
                    #     f.write("This file is here to make the MCRcon CMD program remember that the user has chose to use the current config, so the warning of the current and AutoConfig's config conflict will not be shown")
                    raise Exception("User requested to reconfig")


    print("Connecting to RCON...")

    mcr = MCRcon("127.0.0.1", password, int(port))
    mcr.connect()
except Exception as e:
    print(f"Error: {e}. Using Config... CTRL + C to skip")
    
    # Attempt to use AutoConfig by KMCE
    c = autoConfig()
    if c[0]:
        logfile = c[1]
        port = c[2]
        password = c[3]
        with open(sys.argv[0], "r") as f:
            file = f.readlines()
            
        file[0] = f'password = r"{password}"\n'
        file[1] = "port = " + port + "\n"
        file[2] = f'logfile = r"{logfile}"\n'

        with open(sys.argv[0], "w") as f:
            f.write(
                "".join(file)
            )
        print("AutoConfig successful")
    else:
        print("Unable to use AutoConfig. Using built-in manual config")
        try:
            password = input("RCON Password: ")
            port = input("RCON Port: ")

            # AUTOMATICALLY FIND IF bukkit type server
            findLogFile()


            # save to file
            with open(sys.argv[0], "r") as f:
                file = f.readlines()
            
            file[0] = f'password = r"{password}"\n'
            file[1] = "port = " + port + "\n"
            file[2] = f'logfile = r"{logfile}"\n'

            with open(sys.argv[0], "w") as f:
                f.write(
                    "".join(file)
                )
                
        except KeyboardInterrupt:
            print("Skipping config...")

lastLine = ""

if logfile == "": findLogFile()

mcr = MCRcon("127.0.0.1", password, int(port))
mcr.connect()


def loop():
    global lastLine, thread
    thread = threading.Timer(delay, loop)
    thread.start()
    with open(logfile, 'r') as f:
        line = f.readlines()[-1]

    if line != lastLine:
        print("[LOG] "+line)

        lastLine = line

useLastCMD = 0

loop()
while True:

    if useLastCMD > 0:
        try:
            lastCMD = lastCMDs[-1*useLastCMD]
        except IndexError:
            print("WARNING: Index out of range. Using the first command ran")
            lastCMD = lastCMDs[0]
        cmd = lastCMD + input("> " + lastCMD)
        if cmd == (lastCMD + "."):
            cmd = ""
        useLastCMD = 0
    else:
        cmd = input("> ")

    if not set(cmd) <= set("."):
        lastCMDs.append(cmd)

    ## KMCL ##
    cmd = cmd.replace(';ln;', '\n')
    try:
        if "&" in cmd:
            anye = re.findall(r'&([^&]*)&', cmd)
            for ex in anye:
                loc = {}
                try:
                    exec(ex, globals(), loc)
                    try:
                        if loc['debug'] == True: print("Result: " + str(loc['result']))
                    except KeyError: pass
                except Exception as e:
                    print(traceback.format_exc())

                # if result isnt found, probably the user just wanted to run a python  cmd so
                try: loc['result']
                except KeyError: 
                    print("WARNING: Variable result not specified. Only python commands ran")
                    raise Exception("novar")

                cmd = cmd.replace("&"+ex+"&", str(loc['result']))
        
        cmd = cmd.replace("\n","\\n")


    except Exception as e:
        if str(e) != "novar":
            print(traceback.format_exc())
    ## EXIT KMCL function ##


    # Because up arrow doesnt exist, use the amount of . for last cmds
    if set(cmd) <= set("."):
        useLastCMD = len(cmd)

    if cmd.lower() in ["exit", ".exit"]:
        thread.cancel()
        sys.exit(), exit()

    elif cmd.lower() in [".help"]:
        for key in CMDHELP:
            print(f"{key}: {CMDHELP[key]}")

    elif cmd.lower() in [".autodelay"]:
        from psutil import Process
        process = Process()
        adjustDelay()
        print("Current delay: " + str(delay))

    elif cmd.lower() in [".clear"]:
        if sys.platform.startswith('win'):      os.system(f'cls')
        elif sys.platform.startswith('linux'):  os.system(f'clear')
        else: print("Your OS is not supported. Alternatively, you may use &os.system(\"<cmd>\")& and replace <cmd> with the OS cmd to clear terminal screens")
    elif cmd.lower().startswith(".log"):
        # Get log
        with open(logfile, 'r') as f:
            log = f.readlines()

        try:
            amount = int(cmd.lower().split(" ")[1])
        except Exception as e:
            amount = -1
        
        if amount == -1: amount = len(log)

        print("".join(
            log[(-1*amount):])
        )

    elif cmd.lower().startswith(".delay"):
        try:
            delay = float(cmd.lower().split(" ")[1])
        except Exception as e:
            print(traceback.format_exc())
    else:
        
        if ";new;" not in cmd:
            print(mcr.command(cmd))
        else:
            for c in cmd.split(';new;'):
                print(mcr.command(c))
