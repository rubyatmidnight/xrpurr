from xrpl.wallet import Wallet
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import AccountSet
from xrpl.transaction import submit_and_wait

XRPL_ENDPOINTS = [
    "https://s1.ripple.com:51234/",
    "https://xrplcluster.com/",
    "https://xrpl.ws/",
]


def submit_with_fallback(tx, wallet):
    last_response = None
    for url in XRPL_ENDPOINTS:
        try:
            print(f"Trying endpoint: {url}")
            client = JsonRpcClient(url)
            response = submit_and_wait(tx, client, wallet)
            if response.is_successful():
                print(f"Success via: {url}")
                return response
            last_response = response
            print(f"Endpoint returned failure: {url}")
        except Exception as exc:
            print(f"Endpoint error: {url} ({exc})")
    return last_response

main_address = input("Enter the main (Ledger) address (the one you want to re-enable master key for): ").strip()
regular_key_seed = input("Enter the secret seed for the regular key (the one set as regular key): ").strip()

regular_wallet = Wallet.from_seed(regular_key_seed)

tx = AccountSet(
    account=main_address,
    set_flag=None,
    clear_flag=4  # asfDisableMaster
)

print(f"Submitting AccountSet to re-enable master key for {main_address} (signed by regular key)...")
resp = submit_with_fallback(tx, regular_wallet)
if resp and resp.is_successful():
    print("Master key re-enabled! :3")
    print("Transaction hash:", resp.result.get("hash"))
else:
    print("Failed to re-enable master key.")
    if resp:
        print(resp.result)