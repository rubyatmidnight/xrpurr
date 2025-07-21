import asyncio

from io import StringIO
import random
import csv
import os
import hashlib
import base64
import getpass
import json
import time 
from datetime import datetime
from xrpl.wallet import Wallet
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import Payment, AccountDelete
from xrpl.models.requests import AccountInfo
from xrpl.transaction import submit_and_wait
from xrpl.utils import xrp_to_drops, drops_to_xrp
from cryptography.fernet import Fernet, InvalidToken
import urllib.request
import traceback  

BASEDIR = os.path.dirname(os.path.abspath(__file__))
VERSION = '1.0'

# extra XRPL Mainnet endpoints for redundancy!
XRPL_ENDPOINTS = [
    "https://xrplcluster.com/",
    "https://s1.ripple.com:51234/",
    "https://xrpl.ws/"
]
testnetUrl = "https://s.altnet.rippletest.net:51234/"
client = JsonRpcClient(XRPL_ENDPOINTS[0])

def get_redundant_clients():
    """Return a list of JsonRpcClient objects for all endpoints."""
    return [JsonRpcClient(url) for url in XRPL_ENDPOINTS]

def try_all_clients(func, *args, **kwargs):
    # try all XRPL endpoints in order, may cause lag. Sometimes it sends before it even says it's done
    last_exception = None
    last_response = None
    for url in XRPL_ENDPOINTS:
        try:
            c = JsonRpcClient(url)
            response = func(c, *args, **kwargs)
            last_response = response
            if hasattr(response, "is_successful") and response.is_successful():
                if url != XRPL_ENDPOINTS[0]:
                    print(f"Notice: Fallback XRPL endpoint used: {url}")
                return response
        except Exception as e:
            last_exception = e
            print(f"Warning: XRPL endpoint {url} failed: {e}")
    if last_exception:
        raise last_exception
    return last_response

# Wallets directory and file management is not great 
wallets_dir = os.path.join(BASEDIR, "wallets")
os.makedirs(wallets_dir, exist_ok=True)
SETTINGS_FILE = os.path.join(BASEDIR, "src", "xrpurr_settings.json")
TX_LOG_FILE = os.path.join(BASEDIR, "src", "xrpurr_txlog.json")

# Cache for dtag_accounts_without_flag list
_DTAG_ACCOUNTS_CACHE = {
    "accounts": None,
    "last_fetch": 0
}

# Default settings structure
DEFAULT_SETTINGS = {
    "frequent_addresses": [],  # List of dicts: {nickname, address, tags: [int]}
    "never_require_dtag": False,
    "sanity_check_dtag": True,
    "tx_log_enabled": True,
    "debug": False
}

# if this ever changes it needs to be updated
BASE_RESERVE_XRP = 1.0
OWNER_RESERVE_XRP = 0.2

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def pause(msg="Press Enter to continue..."):
    input(msg)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
            # Fill in any missing keys with defaults
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
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save settings: {e}")
        time.sleep(3.5)

def get_next_wallet_file():
    base_wallet_file = os.path.join(wallets_dir, "xrpurr_wallet.dat")
    if not os.path.exists(base_wallet_file):
        return base_wallet_file
    i = 1
    while True:
        candidate = os.path.join(wallets_dir, f"xrpurr_wallet_{i}.dat")
        if not os.path.exists(candidate):
            return candidate
        i += 1

def get_latest_wallet_file():
    files = []
    for fname in os.listdir(wallets_dir):
        if fname.startswith("xrpurr_wallet") and fname.endswith(".dat"):
            files.append(os.path.join(wallets_dir, fname))
    if not files:
        return os.path.join(wallets_dir, "xrpurr_wallet.dat")
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return files[0]

def log_transaction(tx_data):
    settings = load_settings()
    if not settings.get("tx_log_enabled", True):
        return
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        **tx_data
    }
    try:
        if os.path.exists(TX_LOG_FILE):
            try:
                with open(TX_LOG_FILE, "r") as f:
                    log = json.load(f)
            except Exception:
                print("Warning: Transaction log corrupted, resetting log file.")
                log = []
        else:
            log = []
        log.append(log_entry)
        with open(TX_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not log transaction: {e}")
        pause()

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
        for entry in log[-20:]:  # Show last 20
            print(f"- {entry['timestamp']}: Sent {entry.get('amount_xrp','?')} XRP to {entry.get('destination','?')}"
                  f"{' (tag: '+str(entry['destination_tag'])+')' if entry.get('destination_tag') is not None else ''} "
                  f"Result: {entry.get('result','?')}")
        pause()
    except Exception as e:
        print(f"Could not read transaction log: {e}")
        time.sleep(3.5)
        pause()

# a merely cute ux cliché
def getGreeting():
    morningVariants = [
        "Good morning", "Buenos días", "Guten Morgen", "Bonjour", "Buongiorno",
        "おはようございます", "Доброе утро", "Bom dia", "صباح الخير", "God morgon",
        "سحار مو په ښیر", "Miremengjes", "Bongu", "Mwaramutse", "Ụtụtụ ọma",
        "Sawubona ekuseni", "Dobré ráno", "Hyvää huomenta", "Dzień dobry", "Günaydın"
    ]
    afternoonVariants = [
        "Good afternoon", "Buenas tardes", "Guten Tag", "Bon après-midi", "Buon pomeriggio",
        "こんにちは", "Добрый день", "Boa tarde", "مساء الخير", "God eftermiddag",
        "غرمه مو پخير", "Mirëmbrëma", "Wara nofsinhar it-tajjeb", "Mwiriwe", "Ehihie ọma",
        "Sawubona ntambama", "Dobré popoludnie", "Hyvää iltapäivää", "Dzień dobry", "Tünaydın"
    ]
    eveningVariants = [
        "Good evening", "Buenas noches", "Guten Abend", "Bonsoir", "Buona sera",
        "こんばんは", "Добрый вечер", "Boa noite", "مساء النور", "God kväll",
        "ماښام مو پخير", "Mirëmbrëma", "Il-lejl it-tajjeb", "Mwiriwe", "Mgbede ọma",
        "Sawubona kusihlwa", "Dobrý večer", "Hyvää iltaa", "Dobry wieczór", "İyi akşamlar"
    ]
    nightVariants = [
        "Hello", "Hola", "Hallo", "Salut", "Ciao", "やあ", "Привет", "Olá",
        "مرحبا", "Hej", "سلام", "Përshëndetje", "Bongu", "Bite", "Ndewo",
        "Sawubona", "Ahoj", "Moi", "Cześć", "Merhaba", "ښه شپه ولری"
    ]
    genericVariants = [
    "X R P", "XRP!", "$200 xrp moon", "im not coping"
    ]
    # get the time to send the right message
    now = datetime.now().hour
    if 5 <= now < 12:
        return random.choice(morningVariants)
    elif 12 <= now < 18:
        return random.choice(afternoonVariants)
    elif 18 <= now < 22:
        return random.choice(eveningVariants)
    else:
        return random.choice(nightVariants)

def createWallet():
    clear_screen()
    wallet = Wallet.create()
    print("\n")
    print(f"Address: {wallet.address}")
    print(f"Seed: {wallet.seed}")
    print("\n")
    print(f"Caution!:\nAll XRP non-custodial wallets require a 1 XRP 'owner reserve'. You need to send 1 XRP to this wallet before you can do anything else with it. That 1 XRP is locked until you close the wallet account, so be aware!\n")
    print(f"See XRPL documentation here: https://xrpl.org/docs/concepts/accounts/reserves")
    print(f"If this is your first non-custodial XRP wallet, remember that you can use destination tag '0' if you have never used an address without a dtag requirement before.\n")
    save = input("Save this wallet encrypted to disk? (y/N): ").strip().lower()
    if save == "y":
        saveWalletSeed(wallet.seed)
    clear_screen()
    return wallet

def findVanityAddr(prefix, maxAttempts=1_000_000):
    clear_screen()
    prefix = prefix.strip()
    if not prefix.startswith("r"):
        prefix = "r" + prefix
    
    print(f"Searching for address starting with: {prefix}")
    attempts = 0
    startTime = time.time()
    
    while attempts < maxAttempts:
        wallet = Wallet.create()
        if wallet.address.startswith(prefix):
            elapsed = time.time() - startTime
            print(f"Found vanity address after {attempts+1} attempts in {elapsed:.2f} seconds!")
            print(f"Address: {wallet.address}")
            print(f"Seed: {wallet.seed}")
            # Offer to save wallet
            save = input("Save this wallet encrypted to disk? (y/N): ").strip().lower()
            if save == "y":
                saveWalletSeed(wallet.seed)
            clear_screen()
            return wallet
        
        attempts += 1
        if attempts % 10000 == 0:
            print(f"Attempts: {attempts}... still searching.")
    
    print("Vanity address not found within max attempts.")
    clear_screen()
    return None

def getFernetKeyFromPassword(password):
    key = hashlib.sha256(password.encode()).digest()
    return base64.urlsafe_b64encode(key)

def saveWalletSeed(seed):
    if Fernet is None:
        print("cryptography module not installed. Cannot encrypt wallet seed.")
        clear_screen()
        return
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

def deleteWalletFile():
    clear_screen()
    # List wallet files
    wallet_files = [f for f in os.listdir(wallets_dir) if f.endswith(".dat")]
    if not wallet_files:
        print("No wallet file found to delete.")
        clear_screen()
        return
    print("Wallet files in your wallets directory:")
    for idx, fname in enumerate(wallet_files, 1):
        print(f"  {idx}. {fname}")
    print("a. All wallet files")
    print("b. Back")
    choice = input("Select wallet file to delete (number, 'a' for all, 'b' to cancel): ").strip().lower()
    if choice == "b":
        clear_screen()
        return
    if choice == "a":
        confirm = input("Are you sure you want to DELETE ALL wallet files? This cannot be undone! (type 'deleteall' to confirm): ").strip()
        if confirm == "deleteall":
            for fname in wallet_files:
                os.remove(os.path.join(wallets_dir, fname))
            print("All wallet files deleted.")
        else:
            print("Deletion cancelled.")
        clear_screen()
        return
    if choice.isdigit() and 1 <= int(choice) <= len(wallet_files):
        fname = wallet_files[int(choice)-1]
        fullpath = os.path.join(wallets_dir, fname)
        confirm = input(f"Are you sure you want to DELETE the wallet file '{fname}'? This cannot be undone! (type 'delete' to confirm): ").strip()
        if confirm == "delete":
            os.remove(fullpath)
            print("Wallet file deleted.")
        else:
            print("Deletion cancelled.")
    else:
        print("Invalid selection.")
    clear_screen()

def loadWallet():
    clear_screen()
    # List wallet files
    wallet_files = [f for f in os.listdir(wallets_dir) if f.endswith(".dat")]
    wallet_files.sort(key=lambda x: os.path.getmtime(os.path.join(wallets_dir, x)), reverse=True)
    default_file = os.path.join(wallets_dir, "xrpurr_wallet.dat")
    print("Wallet files in your wallets directory:")
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
        use_file = input(f"Found encrypted wallet file '{os.path.basename(filename)}'. Load it? (y/n): ").strip().lower()
        if use_file in ["", "y", "yes"]:
            for attempt in range(3):
                password = getpass.getpass("Enter password to decrypt wallet: ")
                key = getFernetKeyFromPassword(password)
                f = Fernet(key)
                try:
                    with open(filename, "rb") as fp:
                        enc = fp.read()
                    seed = f.decrypt(enc).decode()
                    wallet = Wallet.from_seed(seed)
                    print(f"Loaded wallet address: {wallet.address}")
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
        wallet = Wallet.from_seed(seed)
        print(f"Loaded wallet address: {wallet.address}")
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

def getBalance(address):
    def _get_balance(client_obj, address):
        acctInfo = AccountInfo(
            account=address,
            ledger_index="validated"
        )
        return client_obj.request(acctInfo)
    try:
        response = try_all_clients(_get_balance, address)
        if response and response.is_successful():
            balance = int(response.result["account_data"]["Balance"])
            balanceXrp = drops_to_xrp(str(balance))
            print(f"Balance for {address}: {balanceXrp} XRP")
            return balance
        else:
            print(f"Error getting balance: {getattr(response, 'result', response)}")
            time.sleep(3.5)
            return 0
    except Exception as e:
        print(f"Error getting balance: {e}")
        time.sleep(3.5)
        return 0

def fetch_dtag_accounts_without_flag():
    """
    Fetches the list of accounts without the RequireDest flag set from the API.
    Caches the result for 5 minutes to avoid excessive requests.
    Returns a set of addresses.
    """
    global _DTAG_ACCOUNTS_CACHE
    now = time.time()
    # Cache for 30 minutes
    if (_DTAG_ACCOUNTS_CACHE["accounts"] is not None and
        now - _DTAG_ACCOUNTS_CACHE["last_fetch"] < 3000):
        return _DTAG_ACCOUNTS_CACHE["accounts"]
    url = "https://xrpl.ws-stats.com/lists/f:dtag_accounts_without_flag"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = response.read().decode("utf-8-sig")
            reader = csv.reader(StringIO(data))
            header = next(reader, None)  # skip header
            accounts = [row[1] for row in reader if len(row) > 1]
            accounts_set = set(accounts)
            _DTAG_ACCOUNTS_CACHE["accounts"] = accounts_set
            _DTAG_ACCOUNTS_CACHE["last_fetch"] = now
            return accounts_set
    except Exception as e:
        print(f"Warning: Could not fetch destination tag account list: {e}")
        time.sleep(3.5)
        return set()

def sendXrp(wallet, destination, amountXrp, destinationTag=None):
    def _send_payment(client_obj, wallet, destination, amountXrp, destinationTag):
        paymentParams = {
            "account": wallet.address,
            "amount": xrp_to_drops(amountXrp),
            "destination": destination
        }
        if destinationTag is not None:
            paymentParams["destination_tag"] = int(destinationTag)
        payment = Payment(**paymentParams)
        return submit_and_wait(payment, client_obj, wallet)

    try:
        settings = load_settings()
        debug = settings.get("debug", False)
        if debug:
            print("DEBUG: sendXrp called with params:")
            print(f"  wallet.address: {getattr(wallet, 'address', None)}")
            print(f"  destination: {destination}")
            print(f"  amountXrp: {amountXrp}")
            print(f"  destinationTag: {destinationTag}")

        response = try_all_clients(_send_payment, wallet, destination, amountXrp, destinationTag)
        if debug:
            print("DEBUG: Response from submit_and_wait:", response)

        if response and response.is_successful():
            print("Transaction successful!")
            print(f"Hash: {response.result['hash']}")
            print(f"Result: {response.result['meta']['TransactionResult']}")
            if destinationTag:
                print(f"Destination tag: {destinationTag}")
            log_transaction({
                "destination": destination,
                "amount_xrp": amountXrp,
                "destination_tag": destinationTag,
                "hash": response.result.get('hash'),
                "result": response.result['meta'].get('TransactionResult')
            })
            pause()
        else:
            print(f"Transaction failed: {getattr(response, 'result', response)}")
            log_transaction({
                "destination": destination,
                "amount_xrp": amountXrp,
                "destination_tag": destinationTag,
                "result": "FAILED",
                "error": str(getattr(response, 'result', response))
            })
            pause()
        clear_screen()
        return response

    except Exception as e:
        settings = load_settings()
        debug = settings.get("debug", False)
        print(f"Error sending XRP: {e}")
        if debug:
            print("DEBUG: Exception traceback:")
            traceback.print_exc()
            print("DEBUG: wallet:", wallet)
            print("DEBUG: destination:", destination)
            print("DEBUG: amountXrp:", amountXrp)
            print("DEBUG: destinationTag:", destinationTag)
        log_transaction({
            "destination": destination,
            "amount_xrp": amountXrp,
            "destination_tag": destinationTag,
            "result": "ERROR",
            "error": str(e)
        })
        pause()
        clear_screen()
        return None

def sendAccountDelete(wallet, destination):
    """
    Sends an AccountDelete transaction to delete the loaded wallet's account and transfer the remaining XRP reserve to the destination.
    The amount sent will be the full balance minus the network fee (0.2 XRP).
    """
    def _get_account_info(client_obj, wallet):
        acctInfo = AccountInfo(
            account=wallet.address,
            ledger_index="validated"
        )
        return client_obj.request(acctInfo)

    def _submit_account_delete(client_obj, wallet, destination):
        tx = AccountDelete(
            account=wallet.address,
            destination=destination
        )
        return submit_and_wait(tx, client_obj, wallet)

    try:
        clear_screen()
        print(f"\nPreparing to delete account {wallet.address} and send the XRP reserve to {destination}...")

        # Try all endpoints for account info
        response = try_all_clients(_get_account_info, wallet)
        if not response or not response.is_successful():
            print(f"Error getting account info: {getattr(response, 'result', response)}")
            time.sleep(3.5)
            clear_screen()
            return False

        account_data = response.result["account_data"]
        balance_drops = int(account_data["Balance"])
        owner_count = int(account_data.get("OwnerCount", 0))

        # Calculate reserve using current rules (Mainnet as of 2024-06)
        min_reserve_xrp = BASE_RESERVE_XRP + OWNER_RESERVE_XRP * max(0, owner_count)
        min_reserve_drops = int(xrp_to_drops(min_reserve_xrp))
        print(f"Account balance: {drops_to_xrp(str(balance_drops))} XRP")
        print(f"Owner objects: {owner_count}")
        print(f"Minimum reserve required for deletion: {min_reserve_xrp} XRP (Base: {BASE_RESERVE_XRP} + Owner: {OWNER_RESERVE_XRP} * {owner_count})")
        print("Note: If you have only two trust lines and no other objects, the reserve may be lower due to XRPL rules. If deletion fails, remove objects and try again.")
        if balance_drops < min_reserve_drops:
            print("Insufficient balance to delete account. Remove all objects (trustlines, offers, etc) and ensure at least the minimum reserve is available.")
            time.sleep(3.5)
            clear_screen()
            return False

        # Calculate the amount to be sent to the destination: full balance minus 0.2 XRP (network fee)
        network_fee_xrp = 0.2
        network_fee_drops = int(xrp_to_drops(network_fee_xrp))
        amount_to_send_drops = balance_drops - network_fee_drops
        if amount_to_send_drops < 0:
            print("Insufficient balance to cover the network fee for account deletion.")
            time.sleep(3.5)
            clear_screen()
            return False

        # Confirm with user
        print("\nWARNING: This will permanently delete your XRP account and send the reserve to the destination address.")
        print("This action is IRREVERSIBLE. You will lose access to this account and its address forever.")
        print("For more info, see: https://xrpl.org/accountdelete.html")
        print(f"Destination for reserve: {destination}")
        print(f"Amount to be sent: {drops_to_xrp(str(amount_to_send_drops))} XRP (full balance minus 0.2 XRP network fee)")
        confirm = input("Type 'IAMDELETINGMYWALLET' (exactly) to confirm: ").strip()
        if confirm != "IAMDELETINGMYWALLET":
            print("Account deletion cancelled.")
            time.sleep(3.5)
            clear_screen()
            return False

        # Try all endpoints for AccountDelete
        print("Submitting AccountDelete transaction...")
        resp = try_all_clients(_submit_account_delete, wallet, destination)
        if resp and resp.is_successful():
            print("AccountDelete transaction successful!")
            print(f"Hash: {resp.result['hash']}")
            print(f"Result: {resp.result['meta']['TransactionResult']}")
            log_transaction({
                "destination": destination,
                "amount_xrp": drops_to_xrp(str(amount_to_send_drops)),
                "account_delete": True,
                "hash": resp.result.get('hash'),
                "result": resp.result['meta'].get('TransactionResult')
            })
            print("You may now delete your wallet file from disk if you wish.")
            pause()
            clear_screen()
            return True
        else:
            print(f"AccountDelete failed: {getattr(resp, 'result', resp)}")
            log_transaction({
                "destination": destination,
                "amount_xrp": drops_to_xrp(str(amount_to_send_drops)),
                "account_delete": True,
                "result": "FAILED",
                "error": str(getattr(resp, 'result', resp))
            })
            time.sleep(3.5)
            clear_screen()
            return False
    except Exception as e:
        settings = load_settings()
        debug = settings.get("debug", False)
        print(f"Error during account deletion: {e}")
        if debug:
            print("DEBUG: Exception traceback:")
            traceback.print_exc()
        log_transaction({
            "destination": destination,
            "account_delete": True,
            "result": "ERROR",
            "error": str(e)
        })
        time.sleep(3.5)
        clear_screen()
        return False

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
        settings = load_settings()
        print("\nSettings Menu:")
        print("1. Manage frequent addresses")
        print("2. Toggle 'Never require dtag' (currently: {})".format("ON" if settings.get("never_require_dtag") else "OFF"))
        print("3. Toggle destination tag sanity check (currently: {})".format("ON" if settings.get("sanity_check_dtag") else "OFF"))
        print("4. Toggle transaction log (currently: {})".format("ON" if settings.get("tx_log_enabled") else "OFF"))
        print("5. View transaction log")
        print("6. Delete wallet file (dangerous!)")
        print("7. Delete XRP account (permanently, send reserve) [DANGEROUS!]")
        print("8. Show developer information and build details")
        print("9. Toggle debug output (currently: {})".format("ON" if settings.get("debug", False) else "OFF"))
        print("b. Back to main menu")
        choice = input("Select a settings option: ").strip().lower()
        if choice == "1":
            manage_frequent_addresses(settings)
        elif choice == "2":
            settings["never_require_dtag"] = not settings.get("never_require_dtag", False)
            print(f"'Never require dtag' set to: {'ON' if settings['never_require_dtag'] else 'OFF'}")
            save_settings(settings)
        elif choice == "3":
            settings["sanity_check_dtag"] = not settings.get("sanity_check_dtag", True)
            print(f"Sanity check for destination tag set to: {'ON' if settings['sanity_check_dtag'] else 'OFF'}")
            save_settings(settings)
        elif choice == "4":
            settings["tx_log_enabled"] = not settings.get("tx_log_enabled", True)
            print(f"Transaction log set to: {'ON' if settings['tx_log_enabled'] else 'OFF'}")
            save_settings(settings)
        elif choice == "5":
            print_tx_log()
        elif choice == "6":
            print("Danger! This will delete your wallet file from disk.")
            deleteWalletFile()
        elif choice == "7":
            print("\nDANGER: This will permanently delete your XRP account from the ledger and send the reserve to another address.")
            print("You must have your wallet loaded and unlocked to proceed.")
            if wallet is None:
                print("No wallet loaded/unlocked. Please load your wallet in the main menu and return here if you wish to delete the account.")
                time.sleep(3.5)
                continue
            dest = input("Enter destination address to receive the XRP reserve (or 'q' to cancel): ").strip()
            if dest.lower() in ['q', 'quit']:
                continue
            # Confirm destination address format
            if not dest or not dest.startswith("r") or len(dest) < 25:
                print("Invalid destination address.")
                time.sleep(3.5)
                continue
            # Confirm again
            print(f"\nYou are about to delete your XRP account and send the reserve to: {dest}")
            print("This action removes the reserve amount from your account and sends it to the destination address.")
            print("This action is not permanent, but the address must be re-activated by sending another reserve minimum of XRP to the address before the account can be used again.")
            print("For more info, see: https://xrpl.org/accountdelete.html")
            print(f"Reserve calculation: Base Reserve = {BASE_RESERVE_XRP} XRP, Owner Reserve = {OWNER_RESERVE_XRP} XRP per object.")
            print("If you have only two trust lines and no other objects, the reserve may be lower due to XRPL rules. If deletion fails, remove objects and try again.")
            # Show the amount to be sent (full balance minus 0.2 XRP)
            try:
                def _get_account_info(client_obj, wallet):
                    acctInfo = AccountInfo(
                        account=wallet.address,
                        ledger_index="validated"
                    )
                    return client_obj.request(acctInfo)
                response = try_all_clients(_get_account_info, wallet)
                if response and response.is_successful():
                    account_data = response.result["account_data"]
                    balance_drops = int(account_data["Balance"])
                    network_fee_xrp = 0.2
                    network_fee_drops = int(xrp_to_drops(network_fee_xrp))
                    amount_to_send_drops = balance_drops - network_fee_drops
                    print(f"Amount to be sent: {drops_to_xrp(str(amount_to_send_drops))} XRP (full balance minus 0.2 XRP network fee)")
                else:
                    print("Could not fetch account balance for preview.")
                    time.sleep(3.5)
            except Exception as e:
                settings = load_settings()
                debug = settings.get("debug", False)
                print(f"Could not fetch account balance for preview: {e}")
                if debug:
                    print("DEBUG: Exception traceback:")
                    traceback.print_exc()
                time.sleep(3.5)
            confirm = input("Type 'IAMDELETINGMYWALLET' (exactly) to confirm: ").strip()
            if confirm != "IAMDELETINGMYWALLET":
                print("Account deletion cancelled.")
                time.sleep(3.5)
                continue
            # Final confirmation
            result = sendAccountDelete(wallet, dest)
            if result:
                print("Account deletion process complete. You may now delete your wallet file from disk if you wish, or retain it for later re-activation.")
                pause()
        elif choice == "8":
            show_dev_info()
        elif choice == "9":
            settings["debug"] = not settings.get("debug", False)
            print(f"Debug output set to: {'ON' if settings['debug'] else 'OFF'}")
            save_settings(settings)
        elif choice == "b":
            clear_screen()
            break
        else:
            print("Invalid option.")
            time.sleep(2)  # or use pause()
            clear_screen()

def manage_frequent_addresses(settings):
    while True:
        clear_screen()
        print("\nFrequent Addresses:")
        fa = settings.get("frequent_addresses", [])
        if not fa:
            print("  (none)")
        else:
            for idx, entry in enumerate(fa):
                tags = entry.get("tags", [])
                tagstr = ", ".join(str(t) for t in tags) if tags else "none"
                print(f"  {idx+1}. {entry['nickname']} - {entry['address']} (tags: {tagstr})")
        print("a. Add new address")
        print("e. Edit address")
        print("d. Delete address")
        print("b. Back")
        choice = input("Select: ").strip().lower()
        if choice == "a":
            nickname = input("Enter nickname: ").strip()
            address = input("Enter address: ").strip()
            tags_input = input("Enter tags (comma separated, or leave blank): ").strip()
            tags = []
            if tags_input:
                for t in tags_input.split(","):
                    t = t.strip()
                    if t.isdigit():
                        tags.append(int(t))
            fa.append({"nickname": nickname, "address": address, "tags": tags})
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
                new_tags = input(f"New tags (comma separated, or Enter to keep '{', '.join(str(t) for t in entry.get('tags', []))}'): ").strip()
                if new_nick:
                    entry['nickname'] = new_nick
                if new_addr:
                    entry['address'] = new_addr
                if new_tags:
                    tags = []
                    for t in new_tags.split(","):
                        t = t.strip()
                        if t.isdigit():
                            tags.append(int(t))
                    entry['tags'] = tags
                fa[idx] = entry
                settings["frequent_addresses"] = fa
                save_settings(settings)
                print("Address updated.")
            else:
                print("Invalid selection.")
                time.sleep(3.5)
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
                time.sleep(3.5)
        elif choice == "b":
            clear_screen()
            break
        else:
            print("Invalid option.")
            time.sleep(3.5)

def select_frequent_address(settings):
    clear_screen()
    fa = settings.get("frequent_addresses", [])
    if not fa:
        return None, None
    print("\nFrequent Addresses:")
    for idx, entry in enumerate(fa):
        tags = entry.get("tags", [])
        tagstr = ", ".join(str(t) for t in tags) if tags else "none"
        print(f"  {idx+1}. {entry['nickname']} - {entry['address']} (tags: {tagstr})")
    print("b. Back")
    choice = input("Select address to use (number): ").strip().lower()
    if choice == "b":
        clear_screen()
        return None, None
    if choice.isdigit() and 1 <= int(choice) <= len(fa):
        entry = fa[int(choice)-1]
        # If multiple tags, ask which one
        if entry.get("tags"):
            print("Available tags: " + ", ".join(str(t) for t in entry["tags"]))
            tag_choice = input("Select tag (number or leave blank for none): ").strip()
            if tag_choice.isdigit():
                clear_screen()
                return entry["address"], int(tag_choice)
            else:
                clear_screen()
                return entry["address"], None
        else:
            clear_screen()
            return entry["address"], None
    else:
        print("Invalid selection.")
        time.sleep(3.5)
        clear_screen()
        return None, None

def show_dev_info():
    clear_screen()
    print("Dev Info:")
    print(f"XRPurr Version: {VERSION}")
    print(f"Base directory: {BASEDIR}")
    print(f"Wallets directory: {wallets_dir}")
    print(f"Current Loaded Settings: {SETTINGS_FILE}")
    print(f"Tx log file: {TX_LOG_FILE}")
    print(f"XRPL client URLs: {', '.join(XRPL_ENDPOINTS)}")
    print(f"Python version: {os.sys.version}")
    print(f"Developer Info: ruby")
    print(f"Repo: https://github.com/rubyatmidnight/xrpurr")
    print(f"Contact: rubyaftermidnight@gmail.com")
    print("\nPress Enter to return to settings menu.")
    input()
    clear_screen()

def dtag_sanity_check(tag, settings):
    # Sanity: tag should be integer 0 <= tag < 2^32, also skips if it's on 
    fa = settings.get("frequent_addresses", [])
    if not settings.get("sanity_check_dtag", True):
        return True
    try:
        tag = int(tag)
        if tag < 0 or tag > 4294967295:
            print("Warning: Destination tag is outside the valid range (0 to 4294967295). Double check!")
            confirm = input("Proceed anyway? (y/n): ").strip().lower()
            return confirm == "y"
        # Warn for suspiciously large or small tags
        if not fa:
            if tag == 0:
                print("Note: Tag 0 is valid and can be used to send to non-custodial wallets, but double check if this is intended.")
            if tag > 1000000:
                print("Warning: Tag is very large. Double check!")
            confirm = input("Proceed anyway? (y/n): ").strip().lower()
            return confirm == "y"
        return True
    except Exception:
        print("Invalid tag for sanity check; please double check.")
        time.sleep(3.5)
        return False

def main():
    clear_screen()
    print(f"/xrpurr/ CLI Wallet")
    print(f"{getGreeting()}!")
    wallet = None
    settings = load_settings()
    
    while True:
        print("\nMenu:")
        print("1. Load existing wallet") 
        print("2. Send XRP to an address")
        print("3. Send XRP to a saved address")
        print("4. Show wallet balance and address")
        print("5. Create new wallet (random fresh address)")
        print("6. Settings")
        print("q. Exit")
        
        choice = getUserChoice()
        
        if choice == "1":
            wallet = loadWallet()
        elif choice == "2":
            # Send XRP to an address (manual)
            if wallet:
                send_xrp_manual(wallet, settings)
            else:
                print("No wallet loaded.")
                time.sleep(3.5)
        elif choice == "3":
            # Send XRP to a saved address
            if wallet:
                send_xrp_saved(wallet, settings)
            else:
                print("No wallet loaded.")
                time.sleep(3.5)
        elif choice == "4":
            clear_screen()
            if wallet:
                try: 
                    print("\n")
                    getBalance(wallet.address)
                    print("\n")
                    print(f"Wallet address: {wallet.address}")
                    print("\n")
                except Exception as e:
                    print(f"Error getting balance: {e}")
                    time.sleep(3.5)
            else:
                print("No wallet loaded.")
                time.sleep(3.5)
        elif choice == "5":
            wallet = createWallet()
        elif choice == "6":
            settings_menu(wallet)
            settings = load_settings()  # reload in case changed
        elif choice == "q":
            print("Goodbye!")
            clear_screen()
            break
        elif choice == "vanity":
            # Hidden vanity finder
            try:
                prefix = input("Enter desired address prefix (e.g., rABC, 'q' to cancel): ").strip()
                if prefix.lower() not in ['q', 'quit']:
                    findVanityAddr(prefix)
            except KeyboardInterrupt:
                print("\nVanity search cancelled.")
                time.sleep(3.5)
                clear_screen()
        elif choice == "donate":
            clear_screen()
            print("\nThank you for considering a donation! :3")
            print("XRP donation address: rLTmPhvoAH4J4B1L36eoXUDGK3rY4BcBTG")
            print("No destination tag is required.")
            print("Your support means a lot! 💖\n")
            time.sleep(5)
        elif choice == "wen":
            clear_screen()
            print("Wen u sen first :3")
            time.sleep(3)
        else:
            print("Invalid option.")
            time.sleep(3.5)

def send_xrp_manual(wallet, settings):
    while True:
        clear_screen()
        try:
            print("\nSend XRP to an address:")
            dest = input("Destination address (or 'q' to cancel): ").strip()
            if dest.lower() in ['q', 'quit']:
                clear_screen()
                return
            destTag = None

            # Check if destination is in the dtag_accounts_without_flag list
            dtag_accounts = fetch_dtag_accounts_without_flag()
            dest_requires_tag = dest in dtag_accounts

            never_require_dtag = settings.get("never_require_dtag", False)
            override_dtag = False

            if dest_requires_tag and not never_require_dtag:
                print(f"\n⚠️  IMPORTANT: The destination address you entered, '{dest}', is on the list of accounts that do NOT have the 'Require Destination Tag (DT)' flag set, despite requiring a DT.")
                print("This means you MUST include a DT for your payment to be properly credited by the recipient (e.g. exchanges, custodial services).")
                print("See: https://xrpl.org/accounts.html#requiredest")
                print("")

            if never_require_dtag:
                override_dtag = True
                destTag = None
            else:
                tagInput = input("Destination tag if required (press Enter to skip): ").strip()
                if tagInput.lower() in ['q', 'quit']:
                    clear_screen()
                    return
                if tagInput:
                    if tagInput.lower() == "forced" and dest_requires_tag:
                        print("Override: You are forcing the transaction to proceed WITHOUT a destination tag, despite the address being known to require one. If you have gotten to this point without knowing what to do, be cautious of where you are sending your XRP.")
                        override_dtag = True
                        destTag = None
                    else:
                        try:
                            if dtag_sanity_check(tagInput, settings):
                                destTag = int(tagInput)
                            else:
                                clear_screen()
                                return
                        except ValueError:
                            print("Invalid destination tag. Must be a number or 'forced'.")
                            time.sleep(3.5)
                            clear_screen()
                            return
                elif dest_requires_tag:
                    print(f"Warning! You did not enter a destination tag, but the recipient address is known to require one.")
                    print(f"Please verify your inputs were correct and you intended to send the transaction with those parameters.\n"
                          f"If you know what you are doing, input the override word `forced` as the destination tag, or enable 'never require dtag' in settings.")
                    time.sleep(3.5)
                    clear_screen()
                    return

            if dest_requires_tag and destTag is None and not (override_dtag or never_require_dtag):
                print("Transaction cancelled due to missing destination tag.")
                time.sleep(3.5)
                clear_screen()
                return
            try:
                bal = getBalance(wallet.address)
                bal_xrp = float(drops_to_xrp(str(bal)))
                spendable = max(0, bal_xrp - 1.0)
                print(f"Spendable: {spendable} XRP")
            except Exception as e:
                print(f"Could not fetch balance: {e}")
                pause()
            
            amtInput = input("Amount in XRP: ").strip()
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

            print(f"\nSending {amt} XRP to {dest}")
            if destTag is not None:
                print(f"Destination tag: {destTag}")
            elif dest_requires_tag and (override_dtag or never_require_dtag):
                print("Proceeding WITHOUT a destination tag (override).")

            confirm = input("Confirm transaction? (y/n): ").strip().lower()
            if confirm == 'y':
                settings = load_settings()
                debug = settings.get("debug", False)
                if debug:
                    print("DEBUG: About to call sendXrp from send_xrp_manual")
                sendXrp(wallet, dest, amt, destTag)
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

def send_xrp_saved(wallet, settings):
    while True:
        clear_screen()
        try:
            print("\nSend XRP to a saved address:")
            fa = settings.get("frequent_addresses", [])
            if not fa:
                print("No saved addresses found.")
                time.sleep(3.5)
                clear_screen()
                return
            for idx, entry in enumerate(fa):
                tags = entry.get("tags", [])
                tagstr = ", ".join(str(t) for t in tags) if tags else "none"
                print(f"  {idx+1}. {entry['nickname']} - {entry['address']} (tags: {tagstr})")
            print("b. Back")
            choice = input("Select address to use (number): ").strip().lower()
            if choice == "b":
                clear_screen()
                return
            if choice.isdigit() and 1 <= int(choice) <= len(fa):
                entry = fa[int(choice)-1]
                dest = entry["address"]
                tags = entry.get("tags", [])
                destTag = None
                if tags:
                    print("Available tags for this address:")
                    for i, t in enumerate(tags, 1):
                        print(f"  {i}. {t}")
                    print("  o. Other (enter a custom tag)")
                    tag_choice = input("Select a tag by number, 'o' to enter a different tag from pre-saved ones, or press Enter to skip: ").strip()
                    if tag_choice == "":
                        destTag = None
                    elif tag_choice.lower() == "o":
                        custom_tag = input("Enter custom destination tag: ").strip()
                        if custom_tag.isdigit():
                            destTag = int(custom_tag)
                        else:
                            print("Invalid custom tag.")
                            time.sleep(3.5)
                            clear_screen()
                            return
                    elif tag_choice.isdigit() and 1 <= int(tag_choice) <= len(tags):
                        destTag = tags[int(tag_choice)-1]
                    else:
                        print("Invalid tag selection.")
                        time.sleep(3.5)
                        clear_screen()
                        return
                # else: no tags, destTag stays None
                try:
                    bal = getBalance(wallet.address)
                    bal_xrp = float(drops_to_xrp(str(bal)))
                    spendable = max(0, bal_xrp - 1.0)
                    print(f"Spendable balance: {spendable} XRP")
                except Exception as e:
                    print(f"Could not fetch balance: {e}")
                    pause()
                
                amtInput = input("Amount in XRP: ").strip()
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

                print(f"\nSending {amt} XRP to {dest}")
                if destTag is not None:
                    print(f"Destination tag: {destTag}")

                confirm = input("Confirm transaction? (y/n): ").strip().lower()
                if confirm == 'y':
                    settings = load_settings()
                    debug = settings.get("debug", False)
                    if debug:
                        print("DEBUG: About to call sendXrp from send_xrp_saved")
                    sendXrp(wallet, dest, amt, destTag)
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

if __name__ == "__main__":
    main()