import concurrent.futures
import threading
import time
import os
from xrpl.wallet import Wallet
from cryptography.fernet import Fernet
import getpass
import string

def showAllowedChars():
    allowed = "r + base58check (no 0, O, I, l), length 25-35. More than 4-5 characters is increasingly difficult to find a match for."
    chars = "r" + ''.join([c for c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"])
    print(f"Allowed characters for XRP addresses:\n{chars}\n\nSummary: {allowed}")

def generateWorker(prefix, caseSensitive, stopEvent, resultDict, workerId):
    create = Wallet.create
    plen = len(prefix)
    prefixC = prefix if caseSensitive else prefix.lower()
    attempts = 0
    while not stopEvent.is_set():
        w = create()
        addrPart = w.address[:plen] if caseSensitive else w.address[:plen].lower()
        if addrPart == prefixC:
            # Only first thread to succeed sets result
            if not stopEvent.is_set():
                resultDict['address'] = w.address
                resultDict['seed'] = w.seed
                resultDict['attempts'] = attempts
                resultDict['workerId'] = workerId
                stopEvent.set()
            break
        attempts += 1
        if attempts % 10000 == 0:
            print(f"Attempts: {attempts}... still searching.")

def getEncryptionKey():
    import base64
    import hashlib
    pw = getpass.getpass("Enter a password to encrypt your seed: ").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(pw).digest())
    return key

def saveEncryptedSeed(seed, filename="vanity_wallet.dat"):
    key = getEncryptionKey()
    f = Fernet(key)
    token = f.encrypt(seed.encode())
    with open(filename, "wb") as out:
        out.write(token)
    print(f"Seed encrypted and saved to {filename}.")

def main():
    showAllowedChars()
    prefix = input("Enter desired prefix (e.g., rMiaCat): ").strip()
    if not prefix.startswith("r") or len(prefix) < 2:
        print("Prefix must start with 'r' and be at least 2 chars."); return
    caseSel = input("Case sensitive match? (y/N): ").strip().lower()
    caseSensitive = caseSel == "y"
    cpuTotal = os.cpu_count() or 4
    cpu = max(1, int(cpuTotal * 0.75))
    stopEvent = threading.Event()
    resultDict = {}
    csText = "case-sensitive" if caseSensitive else "case-insensitive"
    print(f"Searching for address beginning with: '{prefix}...' ({csText}); Using {cpu} of {cpuTotal} threads...")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=cpu) as executor:
        futures = []
        for i in range(cpu):
            futures.append(executor.submit(generateWorker, prefix, caseSensitive, stopEvent, resultDict, i+1))
        # Wait for any thread to finish
        while not stopEvent.is_set():
            time.sleep(0.05)
        # Cancel all threads
        for f in futures:
            f.cancel()
    elapsed = time.time() - t0
    addr = resultDict.get('address')
    seed = resultDict.get('seed')
    attempts = resultDict.get('attempts', 0)
    workerId = resultDict.get('workerId', '?')
    print(f"\nFound {addr}\nBy thread {workerId} after {attempts} attempts")
    print(f"Time: {elapsed:.2f}s | Rate: {int(attempts*cpu/elapsed)} attempts/sec")
    saveEncryptedSeed(seed)

if __name__ == "__main__":
    main()