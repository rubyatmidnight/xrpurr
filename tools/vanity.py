import multiprocessing, time, os
from xrpl.wallet import Wallet
from cryptography.fernet import Fernet, InvalidToken
import getpass

def generate(prefix, queue, stop, pid):
    attempts = 0
    create = Wallet.create
    plen = len(prefix)
    while not stop.is_set():
        w = create()
        attempts += 1
        if w.address[:plen] == prefix:
            queue.put((w.address, w.seed, attempts, pid))
            stop.set()
            break

def get_encryption_key():
    # Prompt for password and derive a Fernet key from it
    import base64
    import hashlib
    pw = getpass.getpass("Enter a password to encrypt your seed: ").encode()
    # Derive a 32-byte key using SHA256, then base64 encode for Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(pw).digest())
    return key

def save_encrypted_seed(seed, filename="vanity_wallet.dat"):
    key = get_encryption_key()
    f = Fernet(key)
    token = f.encrypt(seed.encode())
    with open(filename, "wb") as out:
        out.write(token)
    print(f"Seed encrypted and saved to {filename}.")

def main():
    prefix = input("Enter desired prefix (e.g., rRUBY): ").strip()
    if not prefix.startswith("r") or len(prefix) < 2:
        print("Prefix must start with 'r' and be at least 2 chars."); return
    cpu_total = multiprocessing.cpu_count()
    cpu = max(1, int(cpu_total * 0.75))
    mgr = multiprocessing.Manager()
    queue, stop = mgr.Queue(), mgr.Event()
    print(f"Searching for address beginning with: '{prefix}...';  Using {cpu} of {cpu_total} cores...")
    t0 = time.time()
    procs = [multiprocessing.Process(target=generate, args=(prefix, queue, stop, i+1)) for i in range(cpu)]
    for p in procs: p.start()
    addr, seed, attempts, pid = queue.get()
    elapsed = time.time() - t0
    print(f"\nFound {addr}\nBy process {pid} after {attempts} attempts")
    print(f"Time: {elapsed:.2f}s | Rate: {int(attempts*cpu/elapsed)} attempts/sec")
    save_encrypted_seed(seed)
    stop.set()
    for p in procs: p.terminate(), p.join(timeout=2)

if __name__ == "__main__":
    main()