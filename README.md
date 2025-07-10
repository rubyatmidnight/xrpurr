# xrpurr

Instructions:
Clone this repository in cli
```bash
git clone https://github.com/rubyatmidnight/xrpurr
```

On Windows? Here's a cool trick. Open Powershell and type 
```ps
notepad $PROFILE
```

and enter this: (alternatively, python or python3 as the beginning)
```
function xrp {
	py C:\path\to\the\repo\xrpurr\xrpurr.py
}	
```

then, when you type 'xrp' by itself into Powershell, you will instantly run it. 
## Features

- Create new XRP wallets (with secure, encrypted seed storage)
- Load and manage existing wallets (including encrypted files)
- Send XRP to any address, with destination tag support and safety checks, plus a check on some addresses which require them but don't enforce it on the network
- Manage frequent addresses for quick access
- View your wallet balance and transaction log
- Delete wallet files or even accountdelete your XRP account (with reserve return) easily, no extra-utility or software required
- Vanity address generator (hidden option or included as a separate file)
- Settings menu for advanced options



## Usage

1. **Install dependencies:**
   ```bash
   pip install xrpl cryptography
   ```

2. **Run the wallet:**
   ```bash
   python xrpurr.py
   ```

3. **Follow the on-screen menu!**  
   - Load or create a wallet  
   - Send XRP  
   - Manage addresses and settings  
   - View logs and balances



## Considerations

- Wallets are automatically encrypted with fernet keys by password from the vanity tool, so you can leave it running without someone seeing a found seed on your screen or something like that
- You can also potentially find other people's wallets this way- but that would be extremely unlikely (a collision, effectively)

- Requires Python 3.7+

- Uses public XRPL nodes by default (`xrplcluster.com`)

- For advanced users: a hidden "vanity" option lets you search for custom address prefixes. This can be highly intensive and take a long time looking for anything more than 3-4 letters. Simply write in 'vanity' for the menu option (intead of 1,2,3,etc)

- Other easter eggs: 'donate' and 'wen'. 

## Extra Tools:

These are some nice extra tools I had a need for, and do their job. They don't need the wallet to function and can be used separately. 

### decryptwallet.py 
- will give you your secret key (Seed) if you need it from your .dat file, by entering in your password. This is not an extremely secure way of keeping it stored, so be sure to keep that file only when you are actively using the wallet. A future solution will hopefully be better

### enablemaster.py
- did you disable the master key on a ledger, or other hardware wallet, and have a regular wallet you have the seed for that's able to complete the transaction, but it asks you to use a hardware wallet? then you can use this to create that enable master key transaction to fix the the other address. 


## Disclaimer

- Use at your own risk! This is a hobbyist tool and not affiliated with Ripple, any exchange, and I offer no tech support! If you lose your XRP, it's not my problem!
- Always back up your wallet and test with small amounts first.


## Further improvements?

- If you have any suggestions for additional features or UX improvements, feel free to open an issue or email me at <ruby@stakestats.net>.

- Remember this is a small project and nothing professional. I think it's still faster than most though
