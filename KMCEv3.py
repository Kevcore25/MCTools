VERSION = '1.0'

import os, time, re, requests, json, yaml
from mcrcon import MCRcon

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

def updater(silent = False):
    def log(text: str):
        if not silent:
            print(text)

    log("Checking for updates...")

    # Sites that host, in order
    CDN_SITES = {
        'GitHub': 'https://raw.githubusercontent.com/Kevcore25/MCTools/refs/heads/main/KMCEv3.py',
        'KAF #1': 'https://kaf.kcservers.ca/releases/KMCEv3.py',
        'KAF #2': 'http://vm.kcservers.ca:2585/releases/KMCEv3.py'
    }

    for name, url in CDN_SITES.items():
        try:
            r = requests.get(url, timeout=1)

            # Check status
            if r.status_code != 200:
                raise Exception(f"Returned status code {r.status_code}")
            
            # Get version
            version = r.text.splitlines()[0].split('=', 1)[1].strip().strip("'").strip('"')
            log(f"Found {name} server with version {version} (Current version {VERSION})")

            if compareVersion(version, VERSION):
                with open(os.path.abspath(__file__), 'wb') as f:
                    f.write(r.content)

                log("Current KMCEv3.py is updated!")
                break
        except IndexError:
            log(f"Unable to fetch {name} server due to invalid format")
        except (ConnectionError, requests.ConnectTimeout):
            log(f"Unable to fetch {name} server due to a connection error")
        except Exception as e:
            log(f"Unable to fetch {name} server: {e}")
    else:
        log("The updater did not update the file")

def getBetween(text: str, left: str, right: str):
    return text.split(left, 1)[1].split(right)[0]

def compact_JSON(data: dict | list):
    if isinstance(data, dict):
        data = [data]

    def getv(value) -> str:
        if isinstance(value, str):
            return f'"{value}"'
        elif isinstance(value, bool):
            return str(value).lower()
        elif isinstance(value, dict):
            return compact_JSON(value)
        else:
            return str(value)
    
    result = []
    for part in data:
        text = []
        for k, v in part.items():
            text.append(f'{k}:{getv(v)}')
        result.append('{' + ','.join(text) + '}')
    
    if len(result) == 1:
        final = result[0]
    else:
        final = '[' + ','.join(result) + ']'

    return final.replace('\n', '\\n')

class KMCE:
    def __init__(self, directory: str = ''):
        """
        Creates a connection to KMCE with a base server directory.

        @param directory: The base directory of the server, where the logs folder is contained and the server.properties file
        """

        self.DIRECTORY = directory

        self.chatCommands = {}
        self.chatExpressions = {}
        self.advancementEvents = []
        self.lineEvents = []
        self.playerCmdTimes = {}

        self.entityDeaths = []
        self.serverCommands = {}

        self.store_config()
        
    def command(self, command: str): 
        """
        A decorator that runs when the player runs a command.
        This only works on bukkit servers and will not work on Fabric or the vanilla loader.

        @param command: The command the user runs (make sure to contain /)

        The function needs these parameters:
        
        player: The player executing the command
        args: A tuple of strings representing each argument
        """
        def wrapper(func): 
            self.serverCommands[command] = func 
        return wrapper



    def chat_command(self, command: str): 
        """
        A decorator that runs when the user inputs a chat command.

        @param command: The command the user runs

        The function needs these parameters:
        
        player: The player executing the command
        args: A tuple of strings representing each argument
        """
        def wrapper(func): 
            self.chatCommands[command] = func 
        return wrapper

    def expression(self, expression: str): 
        """
        A decorator that runs when the playe's chat matches a regex expression.

        The function needs these parameters:
        
        player: The player executing the command
        message: The full message the player sends
        """
        def wrapper(func): 
            self.chatExpressions[expression] = func 
        return wrapper

    def advancement(self): 
        """
        A decorator that runs when the player achieves an advancement.

        The function needs these parameters:
        
        player: The player executing the command
        advancement: The name of the advancement
        """
        def wrapper(func): 
            self.advancementEvents.append(func)
        return wrapper

    def line(self): 
        """
        A decorator that runs when the log is updated.

        The function needs these parameters:
        
        line: The text of the line
        """
        def wrapper(func): 
            self.lineEvents.append(func)
        return wrapper


    def chat(self, expression: str):
        return self.chat(expression)

    def entity_death(self):
        """
        A decorator that registers the function to be called when a named entity dies.
        It will give a dictionary as an argument.
        """
        def wrapper(func):
            self.entityDeaths.append(func)
        return wrapper



    def store_config(self):
        """
        Stores the configuration of the server based on the directory
        """

        # Get the RCON information
        try:
            with open(os.path.join(self.DIRECTORY, "server.properties"), 'r') as f:
                properties = f.readlines()

            for property in properties:
                if property.startswith('#'): continue

                key, value = property.split('=')

                match key:
                    case "rcon.port":
                        self.PORT = int(value)
                    case "rcon.password":
                        self.PASSWORD = value

            self.RCON = MCRcon('0.0.0.0', self.PASSWORD, self.PORT)
        except FileNotFoundError:
            print("Unable to fetch the server.properties file from the current directory")
        except AttributeError:
            print("Unable to initialize the RCON configuration as it cannot find the appropriate config values")

        # Get logs location
        self.LOGFILE = os.path.join(self.DIRECTORY, "logs", "latest.log")

    def cooldown(self, player: str, cooldown: float = 0.05) -> bool:
        """
        Returns a boolean value representing whether the player is on CD or not.
        """
        if player in self.playerCmdTimes:
            cmdTimeDiff = time.time() - self.playerCmdTimes[player]
        else:
            cmdTimeDiff = cooldown 
        
        if cmdTimeDiff >= cooldown:
            self.playerCmdTimes[player] = time.time()
            return True
        else:
            return False

    def run_line(self, line: str):
        """Does magic from a MC line"""
        
        """
        Examples on a PaperMC server:

        Running a command (Bukkit only):
        [12:00:00] [Server thread/INFO]: Player issued server command: /command example

        Saying a message:
        [12:00:00] [Async Chat Thread - #1/INFO]: [Not Secure] <Player> .command example

        Named entity died:
        [12:00:00] [Server thread/INFO]: Named entity EntityZombie['Named Zombie'/19208, uuid='798c0dec-db2c-403b-a83e-70e675f539d0', l='ServerLevel[world]', x=0.00, y=0.00, z=0.00, cpos=[0, -7], tl=385, v=true] died: Named Zombie was killed by magic while trying to escape Player
        """

        # First determine of which type
        # Then, parse the line
        
        # Saying a message
        if "<" in line and ">" in line:
            # Get user and the message.
            # User should be within < and >
            player = getBetween(line, "<", ">")

            # Message should be after >
            message = line.split("> ", 1)[1]

            if self.cooldown(player):
                # Get command
                cmd, *args = message.split(' ')

                if cmd in self.chatCommands:
                    func = self.chatCommands[cmd]
                    func(player, args)
                
                # Expressions
                for expression, func in self.chatExpressions.items():
                    if re.search(expression, message):
                        func(player, message)

        # Running a command.
        # This only works on BUKKIT/PaperMC servers
        # Notice for any below detections, player messages are expected not to work due to satisifying the if statement above
        elif "issued server command" in line:
            # Get user and the command.
            player, command = line.split(" issued server command: ")

            # User cannot contain spaces and will remove the [INFO] and stuff
            player = player.split(" ")[-1]

            cmd, *args = command.split(' ')

            if self.cooldown(player) and cmd in self.serverCommands:
                func = self.serverCommands[args[0]]
                func(player, args)

        # Named entity 
        elif "Named entity" in line:
            # Get XYZ, Entity, death reason, name of entity, UUID and what dimension

            # Get Entity. It is after Named entity and before [
            # Entity contains a Entity<entity> so remove it if it exists
            entity = getBetween(line, "Named entity", "[").replace("Entity", "")

            # Get the LIST object of the named entity
            # First get NAMED ENTITY - [
            # Then get ] before died
            # Afterwards, split by ,
            entityObj = line.split("Named entity", 1)[1].split("[", 1)[1] \
                        .split("died")[0][:2] # The :2 removes the space and ] character at the end
            
            entityObj = entityObj.split(',')

            # Get name. It should be in quotes
            # Get values
            for v in entityObj:
                if v.startswith("uuid="):
                    uuid = getBetween(v, "'", "'")
                elif v.startswith("l="):
                    level = getBetween(v, "'", "'")
                elif v.startswith("x="):
                    x = v.split("=")[1]
                elif v.startswith("y="):
                    y = v.split("=")[1]
                elif v.startswith("z="):
                    z = v.split("=")[1]

            try:
                coords = (float(x), float(y), float(z))
            except NameError:
                coords = None

            # Get death reason
            deathReason = line.split("died: ", 1)[1]

            # Turn into dict
            values = {
                "entity": entity,
                "coords": coords,
                "reason": deathReason,
                "uuid": uuid,
                "level": level
            }

            for func in self.entityDeaths:
                func(values)

        # Assuming vanilla mechanincs
        elif " has made the advancement [":
            text = line.split(': ', 1)[1]

            # Get the player and the advancement
            player, advancement = text.split(' has made the advancement [', 1)

            # Trim advancement (has a ] at the end)
            advancement = advancement[:-1].strip()

            for func in self.advancementEvents:
                func(player.strip(), advancement)

        # Run line for generic line events
        for func in self.lineEvents:
            func(line)

    def start(self):
        lastMod = 0
        seek = 0

        try:
            self.RCON.connect()
            print("RCON connected.")
        except ConnectionError:
            print("Unable to connect to RCON. Commands will be disabled.")
        except AttributeError:
            print("No RCON is set up, so commands will not work.")

        if not os.path.exists(self.LOGFILE):
            print(f"The log file ({self.LOGFILE}) cannot be found and this program cannot further continue.")
            exit()

        print("Starting watcher...")

        while True:
            mod = os.stat(self.LOGFILE).st_size

            # In case file is rewritten with less data
            if mod < lastMod:
                seek = mod

            if mod != lastMod:
                # Seek to last pos
                with open(self.LOGFILE, 'rb') as f:
                    f.seek(seek)
                    data = f.read()

                seek += len(data)
                lines = data.decode()

                for line in lines.splitlines():
                    self.run_line(line.rstrip('\n'))

                lastMod = mod

            time.sleep(0.1)

    def run(self, command: str) -> str:
        """
        Runs a command to the Minecraft server.
        Only works if RCON is enabled.

        @param command: The command to run
        """

        return self.RCON.command(command)

    def tellraw(self, player: str, components: dict) -> str:
        """
        Runs the tellraw command to the Minecraft server.
        Only works if RCON is enabled.

        @param command: The command to run
        """
        return self.run(f"tellraw {player} {compact_JSON(components)}")

    def get_scoreboard(self, player: str, objective: str) -> int:
        """Function to obtain a scoreboard value of a player"""

        result = self.run(f"scoreboard players get {player} {objective}")

        if "Can't get value of" in result: 
            return 0
        
        try:
            return int(re.search(r'\d+', result.replace(player,"")).group())
        except:
            return 0

def get_server():
    """Gets the server address of the KCash Account System"""
    import dns.resolver
    return dns.resolver.resolve("kcmcserver.kcservers.ca", "TXT")[0].to_text()[1:-1]

class KCKMCE(KMCE):
    """
    KMCE with preset starting tools for the KCash Account System.

    It includes a shop system, a basic balance viewer, and a KCash saver/loader.
    """

    def __init__(self, directory: str = ''):
        super().__init__(directory)
        self.setup_preset_cmds()

    def setup_preset_cmds(self):
        # Get KCMC server
        server = get_server()

        def request(arg: str) -> dict:
            return requests.get(f"http://{server}/cmd/{arg}").json()

        # Basic .help
        def func(player: str, args: tuple[str]):
            """Shows a list of commands available on this server"""
            for cmd, func in self.chatCommands.items():
                if cmd.startswith('.'):
                    self.tellraw(player, [
                        {"text": f"{cmd}: {func.__doc__}", "color": "light_purple"},
                    ])

        self.chatCommands['.help'] = func

        # Basic .kcash or .bal viewer
        def func(player: str, args: tuple[str]):
            """Shows the views"""
            bal = request(f"READ bal FOR {player}").get("output", 0)

            self.tellraw(player, [
                {"text": "\nYour KCash Balance:\nLocally (on this server): ", "color": "light_purple"}, {"score": {"name": player, "objective": "kcash"}, "color": "green"},
                {"text": f"\nGlobally (on your account): ", "color": "light_purple"}, {"text": f"{bal}\n", "color": "green"},
                {"text": "Make sure to regularly .save!\n", "color": "gray", "italic": True}
            ])

        self.chatCommands['.bal'] = self.chatCommands['.kcash'] = func

        # Basic .save 
        def func(player: str, args: tuple[str]):
            """Adds the current local KCash to the global KCash account"""
            bal = self.get_scoreboard(player, "kcash")
            r = request(f"ADD {bal} FOR {player}")
            if r.get('success'):
                self.run(f"scoreboard players set {player} kcash 0")
                self.tellraw(player, [
                    {"text": f"\nSuccessfully uploaded {bal} KCash to your global account!\n", "color": "green"}
                ])
            else:
                self.tellraw(player, [
                    {"text": f"\nThere was an error saving your account: {r.get('reason')}!\n", "color": "red"}
                ])
        
        self.chatCommands['.save'] = func

        # Basic .load 
        def func(player: str, args: tuple[str]):
            """Transfers the global KCash into local"""
            r = request(f"TRANSFER FOR {player}")
            if r.get('success'):
                self.run(f"scoreboard players add {player} kcash {r.get('output')}")
                self.tellraw(player, [
                    {"text": f"\nSuccessfully loaded {r.get('output')} KCash to your local account!\n", "color": "green"}
                ])
            else:
                self.tellraw(player, [
                    {"text": f"\nThere was an error saving your account: {r.get('reason')}!\n", "color": "red"}
                ])
        
        self.chatCommands['.load'] = func


        # Shop system 
        def func(player: str, args: tuple[str]):
            """Shows the list of items that can be purchased"""
            bal = request(f"READ bal FOR {player}").get("output", 0)

            # Get page number
            if len(args) > 0 and args[0].isdigit():
                page = int(args[0])
            else:
                page = 1

            # Setup for loop
            ITEMS_PER_PAGE = 5
            startI = (page - 1) * ITEMS_PER_PAGE
            endI = startI + ITEMS_PER_PAGE

            # Check if it exists. If it doesn't, tell the player
            if os.path.exists('shop.yml'):
                with open('shop.yml', 'r') as f:
                    items: dict = yaml.safe_load(f)
            else:
                self.tellraw(player, {"text": "\nThere is no shop set up on this server!\n", "color": "red"})

            # Send KCash shop heading
            self.tellraw(player, {"text": "========= KCash Shop =========", "color": "light_purple"})
            
            itemKeys = list(items)
            for i in range(startI, endI):
                # See if it exists. Otherwise, break the for loop
                try:
                    itemID = itemKeys[i]
                except IndexError:
                    break

                item = items[itemID]

                self.tellraw(player, [
                    {"text": item['Name'], "color": "aqua" if item['Stock'] > 0 else "red",
                        "click_event":{"action":"suggest_command","command":f".buy {itemID}"},
                        "hover_event":{"action":"show_text","value":[{"text": item['Description'], "color": "gray"},{"text":f"\nID: {itemID}\nCost: {item['Cost']} | Stock: {item['Stock']}", "color": "aqua"}]}
                    },
                    {"text": ": ", "color": "green"},
                    {"text": f"{item['Cost']} KCash", "color": "yellow", 
                        "click_event":{"action":"suggest_command","command":f".buy {itemID}"}, 
                        "hover_event":{"action":"show_text","value":[{"text": "Click here to buy!", "color": "yellow"}]}
                    }
                ])

            # Send ending message and page 
            self.tellraw(player, [
                {"text": f"You currently have {bal} KCash.\n", "color": "green"},
                {"text": "======", "color": "light_purple"},
                {"text": " << "} | ({"color": "yellow", "click_event":{"action":"suggest_command","command":f".shop {page - 1}"}} if page > 1 else {"color": "gray"}),
                {"text": f"Pg. {page} out of {len(items) // ITEMS_PER_PAGE + 1}", "color": "light_purple"},
                {"text": " >> "} | ({"color": "yellow", "click_event":{"action":"suggest_command","command":f".shop {page + 1}"}} if page < len(items) // ITEMS_PER_PAGE + 1 else {"color": "gray"}),
                {"text": "======", "color": "light_purple"}
            ])

        self.chatCommands['.shop'] = func

        # Buy item 
        def func(player: str, args: tuple[str]):
            """Purchase an item"""

            if len(args) == 0:
                self.tellraw(player, {"text": "\nNo Item ID specified!\n", "color": "red"})

            bal = int(request(f"READ bal FOR {player}").get("output", 0))
            itemID = args[0]

            # Check if it exists. If it doesn't, tell the player
            if os.path.exists('shop.yml'):
                with open('shop.yml', 'r') as f:
                    items: dict = yaml.safe_load(f)
            else:
                self.tellraw(player, {"text": "\nThere is no shop set up on this server!\n", "color": "red"})

            if itemID in items:
                item = items[itemID]
                # Check stock
                if item['Stock'] <= 0:
                    self.tellraw(player, {"text": f"\n{item['Name']} has ran out of stock!\n", "color": "red"})

                # Check cost
                elif bal < item['Cost']:
                    self.tellraw(player, {"text": f"\nYou do not have enough KCash to purchase this item!\nYou need {item['Cost'] - bal} more KCash to buy this item!\n", "color": "red"})

                else:
                    r = request(f"ADD -{item['Cost']} FOR {player}")
                    if r.get('success'):
                        # Run command
                        self.run(f"execute as {player} at @s run " + item['Command'])

                        # Remove 1 from stock, and save it
                        item['Stock'] -= 1
                        with open('shop.yml', 'w') as f:
                            yaml.safe_dump(items, f)

                        self.tellraw(player, {"text": f"\nSuccessfully bought {item['Name']} for {item['Cost']} KCash!\n", "color": "green"})

                    else:
                        self.tellraw(player, [
                            {"text": f"\nThere was an error when making the purchase: {r.get('reason')}!\n", "color": "red"}
                        ])
            else:
                self.tellraw(player, {"text": f"\n{itemID} does not exist!\n", "color": "red"})
        
        self.chatCommands['.buy'] = func



class BotKMCE(KCKMCE):
    def __init__(self, bot):
        super().__init__('')
        self.BOT = bot
        self.setup_preset_cmds()

        def func(player: str, args: tuple[str]):
            """Purchase an item"""
            bal = self.run("/scoreboard players get @s kcash")
            print("Balance", bal)

        self.chatCommands['.get'] = func




    def run(self, command: str) -> str:
        """
        Runs a command to the Minecraft server.

        @param command: The command to run
        """
        print(command)
        bot = self.BOT
        
        bot.chat(command)
        while True:
            with bot.lock:
                if bot.output is not None:
                    print("Command", bot.output)
                    return bot.output
            # small non-blocking sleep to yield CPU
            time.sleep(0.001)


updater()