import os
import hashlib
import base64
import getpass
import json
import time
import random
from datetime import datetime, timezone
from cryptography.fernet import Fernet, InvalidToken
import urllib.request
import traceback
import nano_crypto

BASEDIR = os.path.dirname(os.path.abspath(__file__))
VERSION = '0.9'

# Known Nano RPC endpoint pool
NANO_ENDPOINT_POOL = [
    "https://rainstorm.city/api",
    "https://rpc.nano.to",
    "https://node.somenano.com/proxy",
    "https://app.natrium.io/api",
    "https://nodes.nanswap.com/XNO",
]
# Active endpoints (set at startup)
NANO_ENDPOINTS = list(NANO_ENDPOINT_POOL)
testmode = False

if testmode:
    NANO_ENDPOINTS = ["https://rainstorm.city/api"]

RPC_HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': f'NanoPurr/{VERSION}'
}

def discover_endpoints(quiet=False):
    """Ping all known endpoints, sort by speed."""
    global NANO_ENDPOINTS
    import concurrent.futures
    results = []

    def ping(url):
        t0 = time.time()
        try:
            data = json.dumps({"action": "version"}).encode()
            req = urllib.request.Request(url, data=data, headers=RPC_HEADERS)
            resp = urllib.request.urlopen(req, timeout=3)
            json.loads(resp.read())
            return (url, time.time() - t0, True)
        except Exception:
            return (url, time.time() - t0, False)

    # Ping all endpoints in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(NANO_ENDPOINT_POOL)) as ex:
        results = list(ex.map(ping, NANO_ENDPOINT_POOL))

    alive = [(url, ms) for url, ms, ok in results if ok]
    alive.sort(key=lambda x: x[1])

    if alive:
        NANO_ENDPOINTS = [url for url, ms in alive]
        if not quiet:
            print(f"Found {len(alive)} working node(s). Primary: {NANO_ENDPOINTS[0]}")
    else:
        NANO_ENDPOINTS = list(NANO_ENDPOINT_POOL)
        if not quiet:
            print("Warning: No nodes responded. Using defaults.")

    return NANO_ENDPOINTS

def try_all_clients(func, *args, **kwargs):
    """Try all Nano endpoints in order."""
    last_exception = None
    for idx, url in enumerate(NANO_ENDPOINTS):
        try:
            response = func(url, *args, **kwargs)
            if response is not None:
                if idx > 0:
                    print(f"Notice: Fallback endpoint used: {url}")
                return response
        except Exception as e:
            last_exception = e
            print(f"Warning: Endpoint {url} failed: {e}")
    if last_exception:
        raise last_exception
    return None

def nano_rpc_call(url, method, params=None, timeout=15):
    """Make RPC call to Nano node."""
    if params is None:
        params = {}
    data = {
        "action": method,
        **params
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers=RPC_HEADERS
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))

def is_valid_nano_address(address):
    """Validate Nano address format."""
    if not address or not isinstance(address, str):
        return False
    return nano_crypto.is_valid_address(address)

# Wallets directory and file management
wallets_dir = os.path.join(BASEDIR, "wallets")
os.makedirs(wallets_dir, exist_ok=True)
SETTINGS_FILE = os.path.join(BASEDIR, "src", "nanopurr_settings.json")
TX_LOG_FILE = os.path.join(BASEDIR, "src", "nanopurr_txlog.json")

# Default settings structure
DEFAULT_SETTINGS = {
    "frequent_addresses": [],
    "tx_log_enabled": True,
    "debug": False,
    "nano_usd_conversion": False
}

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def pause(msg="Press any key to continue..."):
    input(msg)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
            for k, v in DEFAULT_SETTINGS.items():
                if k not in settings:
                    settings[k] = v
            return settings
        except Exception as e:
            print(f"Warning: Could not load settings: {e}")
            time.sleep(3.5)
            return DEFAULT_SETTINGS.copy()
    else:
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save settings: {e}")
        time.sleep(3.5)

def get_next_wallet_file():
    base_wallet_file = os.path.join(wallets_dir, "nanopurr_wallet.dat")
    if not os.path.exists(base_wallet_file):
        return base_wallet_file
    i = 1
    while True:
        candidate = os.path.join(wallets_dir, f"nanopurr_wallet_{i}.dat")
        if not os.path.exists(candidate):
            return candidate
        i += 1

def get_latest_wallet_file():
    files = []
    for fname in os.listdir(wallets_dir):
        if fname.lower().startswith("nano") and fname.endswith(".dat"):
            files.append(os.path.join(wallets_dir, fname))
    if not files:
        return os.path.join(wallets_dir, "nanopurr_wallet.dat")
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return files[0]

def log_transaction(tx_data):
    settings = load_settings()
    if not settings.get("tx_log_enabled", True):
        return
    def serialize(obj):
        if isinstance(obj, (datetime)):
            return obj.isoformat()
        return obj
    def clean_dict(d):
        if isinstance(d, dict):
            return {k: clean_dict(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [clean_dict(v) for v in d]
        else:
            return serialize(d)
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **clean_dict(tx_data)
    }
    try:
        os.makedirs(os.path.dirname(TX_LOG_FILE), exist_ok=True)
        if os.path.exists(TX_LOG_FILE):
            try:
                with open(TX_LOG_FILE, "r") as f:
                    log = json.load(f)
            except Exception:
                print("Warning: Transaction log corrupted. Resetting log.")
                log = []
        else:
            log = []
        log.append(log_entry)
        with open(TX_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not log transaction: {e}")
        pause()

def archive_log():
    arch_dir = os.path.join(BASEDIR, "src", "archive")
    os.makedirs(arch_dir, exist_ok=True)
    if os.path.exists(TX_LOG_FILE):
        import shutil
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        arch_file = os.path.join(arch_dir, f"nanopurr_txlog_{ts}.json")
        shutil.move(TX_LOG_FILE, arch_file)
        print(f"Log archived to {arch_file}")

def print_tx_log():
    clear_screen()
    if not os.path.exists(TX_LOG_FILE):
        print("No transaction log found.")
        pause()
        return
    try:
        with open(TX_LOG_FILE, "r") as f:
            log = json.load(f)
        if not log:
            print("Transaction log is empty.")
            pause()
            return
        print("\nTransaction Log:")
        for entry in log[-20:]:
            print(f"- {entry['timestamp']}: Sent {entry.get('amount_nano','?')} NANO to {entry.get('destination','?')} "
                  f"Result: {entry.get('result','?')}")
        pause()
    except Exception as e:
        print(f"Could not read transaction log: {e}")
        time.sleep(3.5)
        pause()

def getGreeting():
    morningVariants = [
        "Good morning", "Buenos días", "Guten Morgen", "Bonjour", "Buongiorno",
        "おはようございます", "Доброе утро", "Bom dia", "صباح الخير", "God morgon"
    ]
    afternoonVariants = [
        "Good afternoon", "Buenas tardes", "Guten Tag", "Bon après-midi", "Buon pomeriggio",
        "こんにちは", "Добрый день", "Boa tarde", "مساء الخير", "God eftermiddag"
    ]
    eveningVariants = [
        "Good evening", "Buenas noches", "Guten Abend", "Bonsoir", "Buona sera",
        "こんばんは", "Добрый вечер", "Boa noite", "مساء النور", "God kväll"
    ]
    nightVariants = [
        "Hello", "Hola", "Hallo", "Salut", "Ciao", "やあ", "Привет", "Olá",
        "مرحبا", "Hej"
    ]
    genericVariants = [
        "N A N O", "NANO!", "feeless & fast", "The midnight hour!"
    ]
    now = datetime.now().hour
    if 5 <= now < 12:
        return random.choice(morningVariants)
    elif 12 <= now < 18:
        return random.choice(afternoonVariants)
    elif 18 <= now < 23:
        return random.choice(eveningVariants)
    elif 0 <= now < 5:
        return 'The midnight hour!'
    else:
        return random.choice(nightVariants)

def createWallet():
    clear_screen()
    seed = nano_crypto.generate_seed()
    wallet = nano_crypto.create_wallet_from_seed(seed, 0)
    
    print("\n")
    print(f"Address: {wallet['address']}")
    print(f"Seed: {seed}")
    print("\n")
    print("Nano wallets are feeless and instant! No reserves required.")
    print("Keep your seed safe - it's your only way to access this wallet.\n")
    
    save = input("Save this wallet encrypted to disk? (y/N): ").strip().lower()
    if save == "y":
        saveWalletSeed(seed)
    clear_screen()
    return wallet

def getFernetKeyFromPassword(password):
    key = hashlib.sha256(password.encode()).digest()
    return base64.urlsafe_b64encode(key)

def saveWalletSeed(seed):
    if Fernet is None:
        print("cryptography module not installed. Cannot encrypt wallet seed.")
        clear_screen()
        return
    print("Note: Nano wallets are named nano*.dat. XRP wallets use xrp*.dat.")
    password = getpass.getpass("Set a password to encrypt your wallet: ")
    password2 = getpass.getpass("Confirm password: ")
    if password != password2:
        print("Passwords do not match. Wallet not saved.")
        clear_screen()
        return
    key = getFernetKeyFromPassword(password)
    f = Fernet(key)
    enc = f.encrypt(seed.encode())
    wallet_file = get_next_wallet_file()
    with open(wallet_file, "wb") as fp:
        fp.write(enc)
    print(f"Wallet seed encrypted and saved to {wallet_file}.")
    clear_screen()

def loadWallet():
    clear_screen()
    wallet_files = [f for f in os.listdir(wallets_dir) if f.endswith(".dat") and f.lower().startswith("nano")]
    wallet_files.sort(key=lambda x: os.path.getmtime(os.path.join(wallets_dir, x)), reverse=True)
    default_file = os.path.join(wallets_dir, "nanopurr_wallet.dat")
    print("Nano wallet files (nano*.dat):")
    print("  (XRP wallets use xrp*.dat and won't appear here)")
    if wallet_files:
        for idx, fname in enumerate(wallet_files, 1):
            print(f"  {idx}. {fname}")
    else:
        print("  (none found)")
    print("m. Manual seed entry")
    print("b. Back/cancel")
    filename = None
    choice = input(f"Select wallet file to load (number, 'm' for manual, 'b' to cancel): ").strip().lower()
    if choice == "b":
        clear_screen()
        return None
    if choice == "m":
        filename = None
    elif choice.isdigit() and 1 <= int(choice) <= len(wallet_files):
        filename = os.path.join(wallets_dir, wallet_files[int(choice)-1])
    elif not choice and os.path.exists(default_file):
        filename = default_file
    else:
        print("Invalid selection.")
        time.sleep(2)
        clear_screen()
        return None

    if filename and Fernet is not None and os.path.exists(filename):
        for attempt in range(3):
            password = getpass.getpass("Enter password to decrypt wallet: ")
            key = getFernetKeyFromPassword(password)
            f = Fernet(key)
            try:
                with open(filename, "rb") as fp:
                    enc = fp.read()
                seed = f.decrypt(enc).decode()
                wallet = nano_crypto.create_wallet_from_seed(seed, 0)
                print(f"Loaded wallet address: {wallet['address']}")
                pause()
                clear_screen()
                return wallet
            except InvalidToken:
                print("Incorrect password.")
                pause()
            except Exception as e:
                print(f"Error loading wallet: {e}")
                pause()
                break
        print("Failed to load wallet from file.")
        pause()
        clear_screen()
        return None
    
    # Fallback: manual seed entry
    seed = input("Enter your wallet seed: ").strip()
    try:
        wallet = nano_crypto.create_wallet_from_seed(seed, 0)
        print(f"Loaded wallet address: {wallet['address']}")
        pause()
        if Fernet is not None:
            save = input("Save this wallet encrypted to disk for next time? (y/N): ").strip().lower()
            if save == "y":
                saveWalletSeed(seed)
        clear_screen()
        return wallet
    except Exception as e:
        print(f"Error loading wallet: {e}")
        pause()
        clear_screen()
        return None

def getNanoUsdRate():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=nano&vs_currencies=usd"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.load(response)
            return float(data["nano"]["usd"])
    except Exception:
        return None

def nanoToUsd(nanoAmt):
    rate = getNanoUsdRate()
    if rate is not None:
        usd = nanoAmt * rate
        return usd, rate
    return None, None

def getBalance(address):
    def _get_balance(url, address):
        return nano_rpc_call(url, "account_balance", {"account": address})
    
    try:
        response = try_all_clients(_get_balance, address)
        settings = load_settings()
        showUsd = settings.get("nano_usd_conversion", False)
        
        if response and not response.get("error"):
            balance_raw = response.get("balance", "0")
            pending_raw = response.get("pending", "0")
            balance_nano = int(balance_raw) / 10**30
            pending_nano = int(pending_raw) / 10**30
            
            if showUsd:
                usd, rate = nanoToUsd(balance_nano)
                if usd is not None:
                    print(f"Balance for {address}: {balance_nano:.6f} NANO (${usd:.2f}) [${rate:.4f}/NANO]")
                    if pending_nano > 0:
                        print(f"Pending: {pending_nano:.6f} NANO")
                else:
                    print(f"Balance for {address}: {balance_nano:.6f} NANO (USD unavailable)")
                    if pending_nano > 0:
                        print(f"Pending: {pending_nano:.6f} NANO")
            else:
                print(f"Balance for {address}: {balance_nano:.6f} NANO")
                if pending_nano > 0:
                    print(f"Pending: {pending_nano:.6f} NANO")
            return balance_nano
        else:
            err = response.get("error", "Unknown error") if response else "No response"
            if "not found" in str(err).lower() or "not opened" in str(err).lower():
                print(f"Account {address} has not been opened yet.")
                print("Send any amount of NANO to this address to activate it.")
                return 0
            print(f"Error getting balance: {err}")
            time.sleep(3.5)
            return 0
    except Exception as e:
        print(f"Error getting balance: {e}")
        time.sleep(3.5)
        return 0

def sendNano(wallet, destination, amountNano):
    try:
        settings = load_settings()
        debug = settings.get("debug", False)
        if debug:
            print("DEBUG: sendNano called with params:")
            print(f"  wallet.address: {wallet.get('address', None)}")
            print(f"  destination: {destination}")
            print(f"  amountNano: {amountNano}")
        
        # Step 1: Get account info
        print("Fetching account info...")
        account_info = try_all_clients(
            nano_rpc_call, "account_info", {
                "account": wallet["address"],
                "representative": "true"
            }
        )
        
        if not account_info or account_info.get("error"):
            err = account_info.get("error", "Unknown") if account_info else "No response"
            print(f"Cannot send: {err}")
            pause()
            clear_screen()
            return None
        
        previous = account_info.get("frontier", "0" * 64)
        balance_raw = account_info.get("balance", "0")
        representative = account_info.get("representative", wallet["address"])
        
        # Calculate new balance
        amount_raw = int(amountNano * 10**30)
        new_balance = int(balance_raw) - amount_raw
        
        if new_balance < 0:
            print("Insufficient balance.")
            pause()
            clear_screen()
            return None
        
        # Validate destination
        try:
            dest_pk = nano_crypto.address_to_public_key(destination)
        except Exception:
            print("Invalid destination address.")
            pause()
            clear_screen()
            return None
        
        # Step 2: Compute block hash and sign
        block_hash = nano_crypto.compute_block_hash(
            wallet["address"], previous,
            representative, new_balance, dest_pk
        )
        signature = nano_crypto.sign_block(
            block_hash, wallet["private_key"]
        )
        
        # Step 3: Generate work (longer timeout)
        print("Generating proof of work...")
        work_resp = try_all_clients(
            nano_rpc_call, "work_generate", {
                "hash": previous
            }, timeout=30
        )
        work = work_resp.get("work") if work_resp else None
        if not work:
            print("Failed to generate proof of work.")
            pause()
            clear_screen()
            return None
        
        # Step 4: Build and process block
        block = {
            "type": "state",
            "account": wallet["address"],
            "previous": previous,
            "representative": representative,
            "balance": str(new_balance),
            "link": dest_pk.upper(),
            "signature": signature,
            "work": work
        }
        
        print("Broadcasting transaction...")
        response = try_all_clients(
            nano_rpc_call, "process", {
                "json_block": "true",
                "subtype": "send",
                "block": block
            }
        )
        
        if response and not response.get("error"):
            print("Transaction successful!")
            if "hash" in response:
                print(f"Hash: {response['hash']}")
            log_transaction({
                "destination": destination,
                "amount_nano": amountNano,
                "hash": response.get("hash"),
                "result": "SUCCESS"
            })
            pause()
        else:
            err = response.get("error", "Unknown") if response else "No response"
            print(f"Transaction failed: {err}")
            log_transaction({
                "destination": destination,
                "amount_nano": amountNano,
                "result": "FAILED",
                "error": str(err)
            })
            pause()
        clear_screen()
        return response
        
    except Exception as e:
        settings = load_settings()
        debug = settings.get("debug", False)
        print(f"Error sending NANO: {e}")
        if debug:
            print("DEBUG: Exception traceback:")
            traceback.print_exc()
        log_transaction({
            "destination": destination,
            "amount_nano": amountNano,
            "result": "ERROR",
            "error": str(e)
        })
        pause()
        clear_screen()
        return None

def receiveNano(wallet):
    """Receive pending blocks."""
    try:
        # Step 1: Check receivable blocks
        print("Checking for receivable transactions...")
        pending = try_all_clients(
            nano_rpc_call, "receivable", {
                "account": wallet["address"],
                "count": "10",
                "source": "true"
            }
        )
        
        blocks = pending.get("blocks") if pending else None
        if not blocks or not isinstance(blocks, dict):
            print("No pending transactions to receive.")
            pause()
            clear_screen()
            return None
        
        print(f"Found {len(blocks)} receivable transaction(s).")
        
        # Step 2: Get account info
        account_info = try_all_clients(
            nano_rpc_call, "account_info", {
                "account": wallet["address"],
                "representative": "true"
            }
        )
        
        # Handle unopened accounts
        if not account_info or account_info.get("error"):
            previous = "0" * 64
            balance_raw = "0"
            representative = wallet["address"]
        else:
            previous = account_info.get("frontier", "0" * 64)
            balance_raw = account_info.get("balance", "0")
            representative = account_info.get("representative", wallet["address"])
        
        received_hashes = []
        for send_hash, block_info in blocks.items():
            # Parse amount from source response
            if isinstance(block_info, dict):
                amount = int(block_info.get("amount", "0"))
            else:
                amount = int(block_info)
            
            nano_amt = amount / 10**30
            print(f"Receiving {nano_amt:.6f} NANO from block {send_hash[:16]}...")
            new_balance = int(balance_raw) + amount
            
            # Compute block hash and sign
            bh = nano_crypto.compute_block_hash(
                wallet["address"], previous,
                representative, new_balance, send_hash
            )
            sig = nano_crypto.sign_block(
                bh, wallet["private_key"]
            )
            
            # Generate work
            work_hash = previous if previous != "0" * 64 else wallet["public_key"]
            print("Generating proof of work...")
            work_resp = try_all_clients(
                nano_rpc_call, "work_generate", {
                    "hash": work_hash
                }
            )
            work = work_resp.get("work", "0000000000000000") if work_resp else "0000000000000000"
            
            if work == "0000000000000000":
                print(f"Warning: Could not generate work for block. Skipping.")
                continue
            
            block = {
                "type": "state",
                "account": wallet["address"],
                "previous": previous,
                "representative": representative,
                "balance": str(new_balance),
                "link": send_hash.upper(),
                "signature": sig,
                "work": work
            }
            
            # Process the block
            process_result = try_all_clients(
                nano_rpc_call, "process", {
                    "json_block": "true",
                    "subtype": "receive",
                    "block": block
                }
            )
            
            if process_result and not process_result.get("error"):
                print(f"Received! Hash: {process_result.get('hash', '?')}")
                received_hashes.append(process_result.get("hash"))
                previous = process_result.get("hash", previous)
                balance_raw = str(new_balance)
            else:
                err = process_result.get("error", "Unknown") if process_result else "No response"
                print(f"Failed to receive block: {err}")
        
        if received_hashes:
            print(f"\nSuccessfully received {len(received_hashes)} transaction(s)!")
        else:
            print("\nNo transactions were received.")
        pause()
        clear_screen()
        return {"received": len(received_hashes), "hashes": received_hashes}
        
    except Exception as e:
        print(f"Error receiving NANO: {e}")
        settings = load_settings()
        if settings.get("debug", False):
            traceback.print_exc()
        pause()
        clear_screen()
        return None

def getUserChoice():
    try:
        choice = input("Select an option (or 'q' to quit): ").strip().lower()
        if choice == 'q' or choice == 'quit':
            print("Goodbye!")
            clear_screen()
            exit(0)
        return choice
    except KeyboardInterrupt:
        print("\nGoodbye!")
        pause()
        clear_screen()
        exit(0)

def settings_menu(wallet=None):
    while True:
        clear_screen()
        print("\nSettings Menu:")
        print("1. Manage frequent addresses")
        print("2. Transaction log settings")
        print("3. Currency conversion settings")
        print("4. Developer settings")
        print("5. Refresh RPC nodes")
        print("b. Back to main menu")
        choice = input("Select a settings section: ").strip().lower()
        if choice == "1":
            manage_frequent_addresses_menu()
        elif choice == "2":
            transaction_log_settings_menu()
        elif choice == "3":
            currency_conversion_settings_menu()
        elif choice == "4":
            developer_settings_menu()
        elif choice == "5":
            discover_endpoints()
            pause()
        elif choice == "b":
            clear_screen()
            break
        else:
            print("Invalid option.")
            time.sleep(2)

def manage_frequent_addresses_menu():
    settings = load_settings()
    while True:
        clear_screen()
        fa = settings.get("frequent_addresses", [])
        print("\nFrequent Addresses:")
        if not fa:
            print("  (none)")
        else:
            for idx, entry in enumerate(fa):
                print(f"  {idx+1}. {entry['nickname']} - {entry['address']}")
        print("a. Add new address")
        print("e. Edit address")
        print("d. Delete address")
        print("b. Back")
        choice = input("Select: ").strip().lower()
        if choice == "a":
            nickname = input("Enter nickname: ").strip()
            address = input("Enter address: ").strip()
            if not is_valid_nano_address(address):
                print("Invalid Nano address.")
                time.sleep(2)
                continue
            fa.append({"nickname": nickname, "address": address})
            settings["frequent_addresses"] = fa
            save_settings(settings)
            print("Address added.")
        elif choice == "e":
            idx = input("Enter number to edit: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(fa):
                idx = int(idx) - 1
                entry = fa[idx]
                print(f"Editing {entry['nickname']} - {entry['address']}")
                new_nick = input(f"New nickname (or Enter to keep '{entry['nickname']}'): ").strip()
                new_addr = input(f"New address (or Enter to keep '{entry['address']}'): ").strip()
                if new_nick:
                    entry['nickname'] = new_nick
                if new_addr:
                    if not is_valid_nano_address(new_addr):
                        print("Invalid Nano address.")
                        time.sleep(2)
                        continue
                    entry['address'] = new_addr
                fa[idx] = entry
                settings["frequent_addresses"] = fa
                save_settings(settings)
                print("Address updated.")
            else:
                print("Invalid selection.")
                time.sleep(2)
        elif choice == "d":
            idx = input("Enter number to delete: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(fa):
                idx = int(idx) - 1
                confirm = input(f"Delete {fa[idx]['nickname']} ({fa[idx]['address']})? (y/N): ").strip().lower()
                if confirm == "y":
                    del fa[idx]
                    settings["frequent_addresses"] = fa
                    save_settings(settings)
                    print("Deleted.")
            else:
                print("Invalid selection.")
                time.sleep(2)
        elif choice == "b":
            clear_screen()
            break
        else:
            print("Invalid option.")
            time.sleep(2)

def transaction_log_settings_menu():
    settings = load_settings()
    while True:
        clear_screen()
        print("\nTransaction Log Settings:")
        print("1. View transaction log")
        print("2. Reset & archive transaction log")
        print("3. Force clear transaction log")
        print("4. Enable/disable transaction logging (currently: {})".format("ON" if settings.get("tx_log_enabled") else "OFF"))
        print("b. Back")
        choice = input("Select: ").strip().lower()
        if choice == "1":
            print_tx_log()
        elif choice == "2":
            archive_log()
            print("Transaction log archived and reset.")
            with open(TX_LOG_FILE, "w") as f:
                json.dump([], f)
            pause()
        elif choice == "3":
            with open(TX_LOG_FILE, "w") as f:
                json.dump([], f)
            print("Transaction log force cleared.")
            pause()
        elif choice == "4":
            settings["tx_log_enabled"] = not settings.get("tx_log_enabled", True)
            print(f"Transaction log set to: {'ON' if settings['tx_log_enabled'] else 'OFF'}")
            save_settings(settings)
        elif choice == "b":
            clear_screen()
            break
        else:
            print("Invalid option.")
            time.sleep(2)

def currency_conversion_settings_menu():
    settings = load_settings()
    while True:
        clear_screen()
        print("\nCurrency Conversion Settings:")
        print("1. Toggle NANO-USD display (currently: {})".format("ON" if settings.get("nano_usd_conversion", False) else "OFF"))
        print("b. Back")
        choice = input("Select: ").strip().lower()
        if choice == "1":
            settings["nano_usd_conversion"] = not settings.get("nano_usd_conversion", False)
            print(f"NANO→USD conversion display set to: {'ON' if settings['nano_usd_conversion'] else 'OFF'}")
            save_settings(settings)
        elif choice == "b":
            clear_screen()
            break
        else:
            print("Invalid option.")
            time.sleep(2)

def developer_settings_menu():
    while True:
        clear_screen()
        print("\nDeveloper Settings:")
        print(f"1. Show developer info and version")
        print(f"2. Toggle debug output")
        print(f"3. Donate easter egg")
        print("b. Back")
        choice = input("Select: ").strip().lower()
        if choice == "1":
            show_dev_info()
        elif choice == "2":
            settings = load_settings()
            settings["debug"] = not settings.get("debug", False)
            print(f"Debug output set to: {'ON' if settings['debug'] else 'OFF'}")
            save_settings(settings)
        elif choice == "3":
            print("Type 'donate' in the main menu for developer address! :3")
            pause()
        elif choice == "b":
            clear_screen()
            break
        else:
            print("Invalid option.")
            time.sleep(2)

def show_dev_info():
    clear_screen()
    print("Dev Info:")
    print(f"NanoPurr Version: {VERSION}")
    print(f"Base directory: {BASEDIR}")
    print(f"Wallets directory: {wallets_dir}")
    print(f"Current Loaded Settings: {SETTINGS_FILE}")
    print(f"Tx log file: {TX_LOG_FILE}")
    print(f"Nano client URLs: {', '.join(NANO_ENDPOINTS)}")
    print(f"Python version: {os.sys.version}")
    print(f"Crypto: nano_crypto (pynacl + blake2b)")
    print("\nPress Enter to return to settings menu.")
    input()
    clear_screen()

def send_nano_manual(wallet, settings):
    while True:
        clear_screen()
        try:
            print("\nSend NANO to an address:")
            dest = input("Destination address (or 'q' to cancel): ").strip()
            if dest.lower() in ['q', 'quit']:
                clear_screen()
                return
            if not is_valid_nano_address(dest):
                print("Invalid Nano address. Please enter a valid Nano address.")
                time.sleep(2)
                clear_screen()
                return
            
            try:
                bal = getBalance(wallet["address"])
                print(f"Available balance: {bal:.6f} NANO")
            except Exception as e:
                print(f"Could not fetch balance: {e}")
                pause()
            
            amtInput = input("Amount in NANO: ").strip()
            if amtInput.lower() in ['q', 'quit']:
                clear_screen()
                return

            try:
                amt = float(amtInput)
            except Exception:
                print("Invalid amount.")
                time.sleep(3.5)
                clear_screen()
                return

            print(f"\nSending {amt} NANO to {dest}")
            confirm = input("Confirm transaction? (y/n): ").strip().lower()
            if confirm == 'y':
                settings = load_settings()
                debug = settings.get("debug", False)
                if debug:
                    print("DEBUG: About to call sendNano from send_nano_manual")
                sendNano(wallet, dest, amt)
            else:
                print("Transaction cancelled.")
                time.sleep(3.5)
                clear_screen()
            return

        except KeyboardInterrupt:
            print("\nTransaction cancelled.")
            time.sleep(3.5)
            clear_screen()
            return
        except Exception as e:
            settings = load_settings()
            debug = settings.get("debug", False)
            print(f"Error: {e}")
            if debug:
                print("DEBUG: Exception traceback:")
                traceback.print_exc()
            time.sleep(3.5)
            clear_screen()
            return

def send_nano_saved(wallet, settings):
    while True:
        clear_screen()
        try:
            print("\nSend NANO to a saved address:")
            fa = settings.get("frequent_addresses", [])
            if not fa:
                print("No saved addresses found.")
                time.sleep(3.5)
                clear_screen()
                return
            for idx, entry in enumerate(fa):
                print(f"  {idx+1}. {entry['nickname']} - {entry['address']}")
            print("b. Back")
            choice = input("Select address to use (number): ").strip().lower()
            if choice == "b":
                clear_screen()
                return
            if choice.isdigit() and 1 <= int(choice) <= len(fa):
                entry = fa[int(choice)-1]
                dest = entry["address"]
                if not is_valid_nano_address(dest):
                    print("Invalid Nano address.")
                    time.sleep(2)
                    clear_screen()
                    return
                
                try:
                    bal = getBalance(wallet["address"])
                    print(f"Available balance: {bal:.6f} NANO")
                except Exception as e:
                    print(f"Could not fetch balance: {e}")
                    pause()
                
                amtInput = input("Amount in NANO: ").strip()
                if amtInput.lower() in ['q', 'quit']:
                    clear_screen()
                    return

                try:
                    amt = float(amtInput)
                except Exception:
                    print("Invalid amount.")
                    time.sleep(3.5)
                    clear_screen()
                    return

                print(f"\nSending {amt} NANO to {dest}")
                confirm = input("Confirm transaction? (y/n): ").strip().lower()
                if confirm == 'y':
                    settings = load_settings()
                    debug = settings.get("debug", False)
                    if debug:
                        print("DEBUG: About to call sendNano from send_nano_saved")
                    sendNano(wallet, dest, amt)
                else:
                    print("Transaction cancelled.")
                    time.sleep(3.5)
                    clear_screen()
                return
            else:
                print("Invalid selection.")
                time.sleep(3.5)
                clear_screen()
                return

        except KeyboardInterrupt:
            print("\nTransaction cancelled.")
            time.sleep(3.5)
            clear_screen()
            return
        except Exception as e:
            settings = load_settings()
            debug = settings.get("debug", False)
            print(f"Error: {e}")
            if debug:
                print("DEBUG: Exception traceback:")
                traceback.print_exc()
            time.sleep(3.5)
            clear_screen()
            return

def main():
    clear_screen()
    print(f"/nanopurr/ CLI Wallet")
    print(f"{getGreeting()}!")
    print("Checking nodes...")
    discover_endpoints()
    wallet = None
    settings = load_settings()
    
    while True:
        print("\nMenu:")
        print("1. Load existing wallet") 
        print("2. Send NANO to an address")
        print("3. Send NANO to a saved address")
        print("4. Receive pending NANO")
        print("5. Show wallet balance and address")
        print("6. Create new wallet (random fresh address)")
        print("7. Settings")
        print("q. Exit")
        
        choice = getUserChoice()
        
        if choice == "1":
            wallet = loadWallet()
        elif choice == "2":
            if wallet:
                send_nano_manual(wallet, settings)
            else:
                print("No wallet loaded.")
                time.sleep(3.5)
        elif choice == "3":
            if wallet:
                send_nano_saved(wallet, settings)
            else:
                print("No wallet loaded.")
                time.sleep(3.5)
        elif choice == "4":
            if wallet:
                receiveNano(wallet)
            else:
                print("No wallet loaded.")
                time.sleep(3.5)
        elif choice == "5":
            clear_screen()
            if wallet:
                try: 
                    print("\n")
                    getBalance(wallet["address"])
                    print("\n")
                    print(f"Wallet address: {wallet['address']}")
                    print("\n")
                except Exception as e:
                    print(f"Error getting balance: {e}")
                    time.sleep(3.5)
            else:
                print("No wallet loaded.")
                time.sleep(3.5)
        elif choice == "6":
            wallet = createWallet()
        elif choice == "7":
            settings_menu(wallet)
            settings = load_settings()
        elif choice == "q":
            print("Goodbye!")
            clear_screen()
            break
        elif choice == "donate":
            clear_screen()
            print("\nThank you for considering a donation! :3")
            print("NANO donation address: nano_1nanopurr1donate1address1here1please1update1me1")
            print("Your support means a lot! 💖\n")
            time.sleep(5)
        else:
            print("Invalid option.")
            time.sleep(3.5)

if __name__ == "__main__":
    main()
