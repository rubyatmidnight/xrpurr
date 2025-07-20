import multiprocessing, time, os
from xrpl.wallet import Wallet
from cryptography.fernet import Fernet
import getpass
import string

def showAllowedChars():
    allowed = "r + base58check (no 0, O, I, l), length 25-35"
    chars = "r" + ''.join([c for c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"])
    print(f"Allowed characters for XRP addresses:\n{chars}\n\nSummary: {allowed}")

def generate(prefix, queue, stop, pid, caseSensitive):
    attempts = 0
    create = Wallet.create
    plen = len(prefix)
    prefixC = prefix if caseSensitive else prefix.lower()
    while not stop.is_set():
        w = create()
        addrPart = w.address[:plen] if caseSensitive else w.address[:plen].lower()
        if addrPart == prefixC:
            queue.put((w.address, w.seed, attempts, pid))
            stop.set()
            break
        attempts += 1

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
    cpuTotal = multiprocessing.cpu_count()
    cpu = max(1, int(cpuTotal * 0.75))
    mgr = multiprocessing.Manager()
    queue, stop = mgr.Queue(), mgr.Event()
    csText = "case-sensitive" if caseSensitive else "case-insensitive"
    print(f"Searching for address beginning with: '{prefix}...' ({csText}); Using {cpu} of {cpuTotal} cores...")
    t0 = time.time()
    procs = [multiprocessing.Process(target=generate, args=(prefix, queue, stop, i+1, caseSensitive)) for i in range(cpu)]
    for p in procs: p.start()
    addr, seed, attempts, pid = queue.get()
    elapsed = time.time() - t0
    print(f"\nFound {addr}\nBy process {pid} after {attempts} attempts")
    print(f"Time: {elapsed:.2f}s | Rate: {int(attempts*cpu/elapsed)} attempts/sec")
    saveEncryptedSeed(seed)
    stop.set()
    for p in procs:
        p.terminate()
        p.join(timeout=2)

if __name__ == "__main__":
    main()