from xrpl.wallet import Wallet
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import AccountSet
from xrpl.transaction import submit_and_wait

jsonRpcUrl = "https://xrplcluster.com/"
client = JsonRpcClient(jsonRpcUrl)

main_address = input("Enter the main (Ledger) address (the one you want to re-enable master key for): ").strip()
regular_key_seed = input("Enter the secret seed for the regular key (the one set as regular key): ").strip()

regular_wallet = Wallet.from_seed(regular_key_seed)

tx = AccountSet(
    account=main_address,
    set_flag=None,
    clear_flag=4  # asfDisableMaster
)

print(f"Submitting AccountSet to re-enable master key for {main_address} (signed by regular key)...")
resp = submit_and_wait(tx, client, regular_wallet)
if resp.is_successful():
    print("Master key re-enabled! :3")
    print("Transaction hash:", resp.result.get("hash"))
else:
    print("Failed to re-enable master key.")
    print(resp.result)