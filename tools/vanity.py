import concurrent.futures
import threading
import argparse
import time
import os
from xrpl.wallet import Wallet
from cryptography.fernet import Fernet
import getpass
import string
from collections import defaultdict

def showAllowedChars():
    allowed = "r + base58check (no 0, O, I, l), length 25-35. More than 4-5 characters is increasingly difficult to find a match for."
    chars = "r" + ''.join([c for c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"])
    print(f"Allowed characters for XRP addresses:\n{chars}\n\nSummary: {allowed}")

def generateWorker(prefix, caseSensitive, stopEvent, resultDict, workerId, printLock, statsDict):
    create = Wallet.create
    plen = len(prefix)
    prefixC = prefix if caseSensitive else prefix.lower()
    attempts = 0
    start_time = time.time()
    
    # Initialize stats immediately so monitor knows worker is active
    statsDict[workerId] = {
        'attempts': 0,
        'active': True,
        'start_time': start_time,
        'last_update': start_time
    }
    
    while not stopEvent.is_set():
        w = create()
        addrPart = w.address[:plen] if caseSensitive else w.address[:plen].lower()
        if addrPart == prefixC:
            if not stopEvent.is_set():
                resultDict['address'] = w.address
                resultDict['seed'] = w.seed
                resultDict['attempts'] = attempts
                resultDict['workerId'] = workerId
                stopEvent.set()
            statsDict[workerId] = {'attempts': attempts, 'active': False, 'last_update': time.time()}
            return {'address': w.address, 'seed': w.seed, 'attempts': attempts, 'workerId': workerId}
        
        attempts += 1
        
        # Only update stats every 100k attempts to minimize overhead
        if attempts % 100000 == 0:
            statsDict[workerId] = {
                'attempts': attempts,
                'active': True,
                'start_time': start_time,
                'last_update': time.time()
            }
            if not stopEvent.is_set():
                with printLock:
                    elapsed = time.time() - start_time
                    rate = attempts / elapsed if elapsed > 0 else 0
                    print(f"Worker {workerId}: {attempts:,} attempts ({rate:.0f} attempts/sec)")
    
    statsDict[workerId] = {'attempts': attempts, 'active': False, 'last_update': time.time()}
    return None

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

BASE58_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def validate_xrp_prefix(prefix):
    """Validate prefix, return error string or None."""
    if not prefix.startswith("r"):
        return "Prefix must start with 'r'."

    if len(prefix) < 2:
        return "Prefix too short. Need at least 'r' + 1 character."

    after = prefix[1:]
    bad_chars = []
    suggestions = {
        '0': 'o or O', 'O': '(valid, but easily confused with 0)',
        'I': '(not in base58, try i or 1)',
        'l': '(not in base58, try L or 1)',
    }
    for c in after:
        if c not in BASE58_CHARS:
            hint = suggestions.get(c, '')
            bad_chars.append((c, hint))

    if bad_chars:
        msg = "Invalid character(s) in prefix:\n"
        for ch, hint in bad_chars:
            if hint:
                msg += f"  '{ch}' - not in base58. {hint}\n"
            else:
                msg += f"  '{ch}' - not in base58.\n"
        msg += f"Allowed: {BASE58_CHARS}"
        return msg

    return None


def main():
    parser = argparse.ArgumentParser(
        description="XRP vanity address finder",
        add_help=True
    )
    parser.add_argument(
        "-t", "--threads", type=int, default=0,
        help="Number of worker threads (default: 75%% of CPU cores)"
    )
    parser.add_argument(
        "-p", "--prefix", type=str, default=None,
        help="Desired address prefix (e.g. rMiaCat)"
    )
    parser.add_argument(
        "-c", "--case-sensitive", action="store_true",
        help="Case sensitive matching"
    )
    args = parser.parse_args()

    showAllowedChars()

    prefix = args.prefix
    if not prefix:
        prefix = input("Enter desired prefix (e.g., rMiaCat): ").strip()
    err = validate_xrp_prefix(prefix)
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
    stopEvent = threading.Event()
    resultDict = {}
    statsDict = defaultdict(dict)
    printLock = threading.Lock()
    csText = "case-sensitive" if caseSensitive else "case-insensitive"
    print(f"Searching for address beginning with: '{prefix}...' ({csText}); Using {cpu} of {cpuTotal} threads...")
    print("Press Ctrl+C to stop search\n")
    t0 = time.time()
    last_stats_time = time.time()
    
    def monitor_thread():
        """Monitor thread activity and report stats"""
        while not stopEvent.is_set():
            time.sleep(15)  # Check every 15 seconds (less frequent to reduce overhead)
            if stopEvent.is_set():
                break
            
            current_time = time.time()
            active_workers = 0
            total_attempts = 0
            total_rate = 0
            stuck_workers = []
            
            # Quick snapshot of stats to minimize lock time
            stats_snapshot = {}
            for worker_id in range(1, cpu + 1):
                stats_snapshot[worker_id] = statsDict.get(worker_id, {}).copy()
            
            with printLock:
                print(f"\n--- Status Update ({time.strftime('%H:%M:%S')}) ---")
                for worker_id in range(1, cpu + 1):
                    stats = stats_snapshot.get(worker_id, {})
                    # Consider worker active if it has stats and last update was recent, or if marked active
                    is_active = stats.get('active', False) or (stats.get('last_update', 0) > 0 and (current_time - stats.get('last_update', 0)) < 30)
                    if is_active:
                        active_workers += 1
                        attempts = stats.get('attempts', 0)
                        start_time = stats.get('start_time', current_time)
                        last_update = stats.get('last_update', 0)
                        time_since_update = current_time - last_update
                        
                        # Calculate rate from total attempts and elapsed time
                        elapsed_total = current_time - start_time
                        rate = attempts / elapsed_total if elapsed_total > 0 else 0
                        
                        total_attempts += attempts
                        total_rate += rate
                        
                        # Check if thread appears stuck (no update in 30 seconds)
                        if time_since_update > 30:
                            stuck_workers.append(worker_id)
                            print(f"Worker {worker_id}: {attempts:,} attempts | ⚠️  STUCK (no update in {time_since_update:.0f}s)")
                        else:
                            print(f"Worker {worker_id}: {attempts:,} attempts | {rate:.0f} attempts/sec | Active")
                    else:
                        print(f"Worker {worker_id}: Inactive or finished")
                
                print(f"\nTotal: {active_workers}/{cpu} workers active | Combined rate: {total_rate:.0f} attempts/sec")
                
                if stuck_workers:
                    print(f"⚠️  WARNING: {len(stuck_workers)} worker(s) appear stuck: {stuck_workers}")
                
                if active_workers == 0 and not resultDict:
                    print("⚠️  WARNING: No active workers detected!")
                
                # Check for significant slowdown
                if total_rate > 0 and total_rate < 1000:
                    print("⚠️  Performance warning: Combined rate is very low (<1000 attempts/sec)")
                
                print("---\n")
    
    # Start monitoring thread
    monitor = threading.Thread(target=monitor_thread, daemon=True)
    monitor.start()
    
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=cpu) as executor:
            futures = [executor.submit(generateWorker, prefix, caseSensitive, stopEvent, resultDict, i+1, printLock, statsDict) 
                       for i in range(cpu)]
            # Wait for first worker to find a match
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result is not None:
                    stopEvent.set()
                    break
    except KeyboardInterrupt:
        print("\n\nSearch interrupted by user.")
        stopEvent.set()
        time.sleep(1)  # Give threads time to stop
    
    elapsed = time.time() - t0
    addr = resultDict.get('address')
    seed = resultDict.get('seed')
    attempts = resultDict.get('attempts', 0)
    workerId = resultDict.get('workerId', '?')
    
    # Final stats
    total_attempts_all = sum(s.get('attempts', 0) for s in statsDict.values())
    
    if addr and seed:
        print(f"\n{'='*60}")
        print(f"✓ FOUND VANITY ADDRESS!")
        print(f"{'='*60}")
        print(f"Address: {addr}")
        print(f"Seed: {seed}")
        print(f"\nFound by Worker {workerId} after {attempts:,} attempts")
        print(f"Total time: {elapsed:.2f}s")
        print(f"Worker rate: {int(attempts/elapsed) if elapsed > 0 else 0} attempts/sec")
        if total_attempts_all > attempts:
            print(f"Total attempts across all workers: {total_attempts_all:,}")
            print(f"Combined rate: {int(total_attempts_all/elapsed) if elapsed > 0 else 0} attempts/sec")
        print(f"{'='*60}\n")
        saveEncryptedSeed(seed)
    else:
        print(f"\nSearch stopped without finding a match.")
        print(f"Total attempts: {total_attempts_all:,}")
        print(f"Time elapsed: {elapsed:.2f}s")
        print(f"Average rate: {int(total_attempts_all/elapsed) if elapsed > 0 else 0} attempts/sec")

if __name__ == "__main__":
    main()