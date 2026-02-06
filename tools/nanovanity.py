import multiprocessing
import argparse
import time
import os
import sys
import getpass
import hashlib
import base64
from cryptography.fernet import Fernet

# Add parent dir for nano_crypto import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nano_crypto

# Nano base32 charset
NANO_BASE32 = "13456789abcdefghijkmnopqrstuwxyz"


def showAllowedChars():
    chars = "nano_" + NANO_BASE32
    print(f"Allowed characters for Nano addresses:\n{chars}")
    print(f"\nNano addresses are 65 chars: nano_ + 52 key chars + 8 checksum chars")
    print(f"First char after nano_ is always 1 or 3.")
    print(f"More than 4-5 chars after prefix gets exponentially harder.\n")


def worker_process(prefix_bytes, case_sensitive, worker_id, result_queue, stop_flag, stats_dict):
    """Worker that runs in its own process."""
    attempts = 0
    plen = len(prefix_bytes)
    prefix_lower = prefix_bytes.lower() if not case_sensitive else prefix_bytes
    start_time = time.time()

    # Hot-path references
    _urandom = os.urandom
    _gen_addr = nano_crypto.generate_address_fast

    while not stop_flag.value:
        seed_bytes = _urandom(32)
        addr = _gen_addr(seed_bytes)

        check = addr[:plen] if case_sensitive else addr[:plen].lower()
        if check == prefix_lower:
            seed_hex = seed_bytes.hex()
            addr_str = addr.decode('ascii')
            result_queue.put({
                'address': addr_str,
                'seed': seed_hex,
                'attempts': attempts,
                'workerId': worker_id
            })
            stop_flag.value = True
            stats_dict[worker_id] = attempts
            return

        attempts += 1

        # Update shared stats periodically
        if attempts % 50000 == 0:
            stats_dict[worker_id] = attempts

    stats_dict[worker_id] = attempts


def validate_nano_prefix(prefix):
    """Validate prefix, return error string or None."""
    if not prefix.startswith("nano_"):
        return "Prefix must start with 'nano_'."

    if len(prefix) < 6:
        return "Prefix too short. Need at least nano_ + 1 character."

    after = prefix[5:]

    # First char must be 1 or 3
    if after[0] not in ("1", "3"):
        return (
            f"First character after 'nano_' must be '1' or '3', got '{after[0]}'.\n"
            f"Nano addresses always start with nano_1 or nano_3."
        )

    # Check each character
    bad_chars = []
    suggestions = {
        '0': 'o', '2': '3', 'l': '1',
        'v': 'u', 'O': 'o', 'I': 'i',
        'L': '1', 'V': 'u',
    }
    for c in after:
        if c.lower() not in NANO_BASE32:
            hint = suggestions.get(c, '')
            bad_chars.append((c, hint))

    if bad_chars:
        msg = "Invalid character(s) in prefix:\n"
        for ch, hint in bad_chars:
            if hint:
                msg += f"  '{ch}' - not in Nano base32. Try '{hint}' instead?\n"
            else:
                msg += f"  '{ch}' - not in Nano base32.\n"
        msg += f"Allowed chars: {NANO_BASE32}"
        return msg

    return None


def getEncryptionKey():
    pw = getpass.getpass("Enter a password to encrypt your seed: ").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(pw).digest())
    return key


def saveEncryptedSeed(seed, filename="nanovanity_wallet.dat"):
    key = getEncryptionKey()
    f = Fernet(key)
    token = f.encrypt(seed.encode())
    wallets_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "wallets"
    )
    os.makedirs(wallets_dir, exist_ok=True)
    filepath = os.path.join(wallets_dir, filename)
    with open(filepath, "wb") as out:
        out.write(token)
    print(f"Seed encrypted and saved to {filepath}.")


def main():
    parser = argparse.ArgumentParser(
        description="Nano vanity address finder",
        add_help=True
    )
    parser.add_argument(
        "-t", "--threads", type=int, default=0,
        help="Number of worker processes (default: 75%% of CPU cores)"
    )
    parser.add_argument(
        "-p", "--prefix", type=str, default=None,
        help="Desired address prefix (e.g. nano_1cat)"
    )
    parser.add_argument(
        "-c", "--case-sensitive", action="store_true",
        help="Case sensitive matching"
    )
    args = parser.parse_args()

    showAllowedChars()

    prefix = args.prefix
    if not prefix:
        prefix = input("Enter desired prefix (e.g., nano_1mia or nano_1cat): ").strip()

    err = validate_nano_prefix(prefix)
    if err:
        print(err)
        return

    if args.case_sensitive:
        caseSensitive = True
    else:
        caseSel = input("Case sensitive match? (y/N): ").strip().lower()
        caseSensitive = caseSel == "y"

    cpuTotal = os.cpu_count() or 4
    if args.threads > 0:
        cpu = min(args.threads, cpuTotal)
    else:
        cpu = max(1, int(cpuTotal * 0.75))

    prefix_bytes = prefix.encode('ascii')

    # Multiprocessing shared state
    manager = multiprocessing.Manager()
    result_queue = multiprocessing.Queue()
    stop_flag = multiprocessing.Value('b', False)
    stats_dict = manager.dict()

    csText = "case-sensitive" if caseSensitive else "case-insensitive"
    print(f"\nSearching for: '{prefix}...' ({csText})")
    print(f"Using {cpu} of {cpuTotal} CPU cores (multiprocessing)")
    print("Press Ctrl+C to stop\n")
    t0 = time.time()

    # Launch worker processes
    processes = []
    for i in range(cpu):
        p = multiprocessing.Process(
            target=worker_process,
            args=(prefix_bytes, caseSensitive, i + 1, result_queue, stop_flag, stats_dict)
        )
        p.daemon = True
        p.start()
        processes.append(p)

    # Monitor loop in main process
    try:
        while True:
            # Check for result
            try:
                result = result_queue.get(timeout=5)
                stop_flag.value = True
                break
            except Exception:
                result = None

            # Print status
            elapsed = time.time() - t0
            total = sum(stats_dict.get(i + 1, 0) for i in range(cpu))
            rate = total / elapsed if elapsed > 0 else 0
            alive = sum(1 for p in processes if p.is_alive())
            print(f"[{time.strftime('%H:%M:%S')}] {alive} workers | {total:,} attempts | {rate:,.0f}/sec combined")

    except KeyboardInterrupt:
        print("\n\nSearch interrupted.")
        stop_flag.value = True
        result = None

    # Wait for workers to finish
    for p in processes:
        p.join(timeout=2)
        if p.is_alive():
            p.terminate()

    elapsed = time.time() - t0
    total_all = sum(stats_dict.get(i + 1, 0) for i in range(cpu))

    if result:
        addr = result['address']
        seed = result['seed']
        attempts = result['attempts']
        workerId = result['workerId']

        print(f"\n{'='*60}")
        print(f"FOUND VANITY ADDRESS!")
        print(f"{'='*60}")
        print(f"Address: {addr}")
        print(f"Seed:    {seed}")
        print(f"\nFound by Worker {workerId} after {attempts:,} attempts")
        print(f"Total time: {elapsed:.2f}s")
        if elapsed > 0:
            print(f"Worker rate: {int(attempts/elapsed):,}/sec")
        if total_all > attempts:
            print(f"Combined attempts: {total_all:,}")
            if elapsed > 0:
                print(f"Combined rate: {int(total_all/elapsed):,}/sec")
        print(f"{'='*60}\n")

        # Verify
        verify = nano_crypto.create_wallet_from_seed(seed, 0)
        if verify['address'] == addr:
            print("Address verified OK.")
        else:
            print(f"WARNING: Verification mismatch! {verify['address']}")

        save = input("Save seed encrypted to disk? (y/N): ").strip().lower()
        if save == "y":
            saveEncryptedSeed(seed)
    else:
        print(f"\nNo match found.")
        print(f"Total attempts: {total_all:,}")
        print(f"Time: {elapsed:.2f}s")
        if elapsed > 0:
            print(f"Rate: {int(total_all/elapsed):,}/sec")


if __name__ == "__main__":
    main()
