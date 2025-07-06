from cryptography.fernet import Fernet, InvalidToken
import base64
import hashlib

def getFernetKeyFromPassword(password):
    key = hashlib.sha256(password.encode()).digest()
    return base64.urlsafe_b64encode(key)

filename = "src/xrpurr_wallet.dat"
password = input("Enter your wallet password: ")
key = getFernetKeyFromPassword(password)
f = Fernet(key)

with open(filename, "rb") as fp:
    enc = fp.read()

try:
    seed = f.decrypt(enc).decode()
    print("Your secret key (seed) is:", seed)
except InvalidToken:
    print("Incorrect password or corrupted file.")