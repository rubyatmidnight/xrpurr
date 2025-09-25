# xrpurr

## Updates


9/20/2025: Version 1.2
I'm sad I wasn't able to work on this much, but I have not had ANY issues since the last time and I have used it regularly. Therefore, I am continuing this project towards hopefully an executible release, as well as a timelock vault.
Everything has been cleaned up and optimized
Erroneous error messages and unhelpful ones have been rewritten
The settings menu was reorganized and cleaned up
No more annyoing y/n prompts: just do what you intend to
Soon: timevault. I think this is really important! 

8/7/2025: Hotfix 1.1a
Added validation for instances where the node fails, it falls back, but the node actually didn't fail; and it ends up double sending. This seemed to happen in fringe cases where the primary node. I already pushed an update which should solve this, but be wary.

7/16/2025: Version 1.1
Fixed json txlog issue (it will no longer error or malform i hope!)
Now show spendable balance on send xrp screen (doesnt include reserve amount in total)


7/11/2025: Version 1.0
I had issues with the main xrpl node today, and couldn't sign any transactions. So I had to add some redundancy when it fails to send a transaction, it will attempt to connect to a different node and send it. 

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

- Create new XRP wallets (with secure, encrypted seed storage using Fernet keys)
- Load and manage existing valid XRP wallet seeds
- Send XRP to any address, with destination tag support and safety checks, plus a check on some addresses which require them but don't enforce it on the network. These warnings may optionally be turned off
- Manage frequent addresses for quick access. Able to save multiple different tags per address for quick selection, like oldschool speed-dial
- View your wallet balance and transaction log easily through the ui, save and archive the transaction log, angostic to address for easy financial tracking
- Conversion to usd, more currencies later
- Delete wallet files securely or even accountdelete your XRP account (with reserve return) easily, no extra-utility or software required
- Vanity address generator (hidden option or included as a separate file with multithreading.)
- Settings menu for advanced options and debugging display



## Usage

### For Beginners & Non-Power Users

1. **Install Python:**
   - Go to [python.org/downloads](https://www.python.org/downloads/) and download Python 3.7 or newer for your operating system.
   - Run the installer. **Be sure to check the box that says "Add Python to PATH"** before clicking "Install Now".

2. **Download xrpurr:**
   - Click the green "Code" button on the [GitHub page](https://github.com/rubyatmidnight/xrpurr) and choose "Download ZIP".
   - Extract the ZIP file to a folder you can find easily (like your Desktop).

3. **Open a Terminal or Command Prompt:**
   - **Windows:** Press `Win + R`, type `cmd`, and press Enter.
   - **Mac:** Open "Terminal" from Applications > Utilities.
   - **Linux:** Open your terminal app.

4. **Navigate to the xrpurr folder:**
   - Type `cd Desktop\xrpurr-main` (or wherever you extracted it) and press Enter.

5. **Install dependencies:**
   ```bash
   pip install xrpl cryptography --break
   ```
   - If you get an error, try `pip3` instead of `pip`.

6. **Run the wallet:**
   ```bash
   python xrpurr.py
   ```
   - If you get an error, try `python3 xrpurr.py`.

7. **Follow the on-screen menu!**  
   - Load or create a wallet  
   - Send XRP  
   - Manage addresses and settings  
   - View logs and balances

---

### For Power Users

1. **Clone the repo:**
   ```bash
   git clone https://github.com/rubyatmidnight/xrpurr
   cd xrpurr
   ```

2. **Install dependencies:**
   ```bash
   pip install xrpl cryptography --break
   ```

3. **Run the wallet:**
   ```bash
   python xrpurr.py
   ```

### For rebuilding the binary
pip install -r requirement.txt
pyinstaller --onefile xrpurr.py
sha256sum dist/xrpurr

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
