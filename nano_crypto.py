# Pure-Python Nano crypto using pynacl + hashlib.blake2b
# Implements ed25519-blake2b signing, key derivation,
# Nano Base32 encoding, and address generation.

import os
import hashlib
import binascii
from nacl.bindings import (
    crypto_scalarmult_ed25519_base_noclamp,
    crypto_core_ed25519_scalar_reduce,
    crypto_core_ed25519_scalar_add,
    crypto_core_ed25519_scalar_mul,
)

# Nano Base32 alphabet
NANO_B32_ALPHABET = b"13456789abcdefghijkmnopqrstuwxyz"
NANO_B32_MAP = {c: i for i, c in enumerate(NANO_B32_ALPHABET)}


def bytes_to_nbase32(data):
    """Encode bytes to Nano Base32."""
    # Convert to bit string
    bits = bin(int.from_bytes(data, 'big'))[2:]
    bits = bits.zfill(len(data) * 8)
    # Pad to multiple of 5
    pad = (5 - len(bits) % 5) % 5
    bits = '0' * pad + bits
    result = []
    for i in range(0, len(bits), 5):
        idx = int(bits[i:i+5], 2)
        result.append(NANO_B32_ALPHABET[idx:idx+1])
    return b"".join(result)


def nbase32_to_bytes(encoded):
    """Decode Nano Base32 to bytes."""
    if isinstance(encoded, str):
        encoded = encoded.encode('ascii')
    bits = []
    for c in encoded:
        # bytes iteration yields ints
        idx = NANO_B32_MAP.get(c)
        if idx is None:
            raise ValueError(f"Invalid Nano Base32 char: {chr(c)}")
        bits.append(format(idx, '05b'))
    bitstring = "".join(bits)
    # Remove leading padding
    byte_count = len(bitstring) // 8
    trim = len(bitstring) - byte_count * 8
    bitstring = bitstring[trim:]
    result = int(bitstring, 2).to_bytes(byte_count, 'big')
    return result


def _clamp_key(h32):
    """Clamp ed25519 scalar."""
    a = bytearray(h32)
    a[0] &= 0xF8
    a[31] = (a[31] & 0x7F) | 0x40
    return bytes(a)


def derive_public_key(private_key_bytes):
    """Derive ed25519 public key using blake2b."""
    h = hashlib.blake2b(private_key_bytes, digest_size=64).digest()
    a = _clamp_key(h[:32])
    pk = crypto_scalarmult_ed25519_base_noclamp(a)
    return pk


def sign_message(message, private_key_bytes, public_key_bytes):
    """ed25519-blake2b signature."""
    h = hashlib.blake2b(private_key_bytes, digest_size=64).digest()
    a = _clamp_key(h[:32])
    # Nonce: H(h[32:64] + message)
    r_hash = hashlib.blake2b(
        h[32:64] + message, digest_size=64
    ).digest()
    r = crypto_core_ed25519_scalar_reduce(r_hash)
    # R = r * B
    R = crypto_scalarmult_ed25519_base_noclamp(r)
    # k = H(R + pk + message) mod l
    k_hash = hashlib.blake2b(
        R + public_key_bytes + message, digest_size=64
    ).digest()
    k = crypto_core_ed25519_scalar_reduce(k_hash)
    # S = (r + k * a) mod l
    ka = crypto_core_ed25519_scalar_mul(k, a)
    S = crypto_core_ed25519_scalar_add(r, ka)
    return R + S


def generate_seed():
    """Generate random 64-char hex seed."""
    return os.urandom(32).hex()


def derive_private_key(seed_hex, index):
    """Derive account private key from seed."""
    seed_bytes = binascii.unhexlify(seed_hex)
    index_bytes = index.to_bytes(4, 'big')
    h = hashlib.blake2b(digest_size=32)
    h.update(seed_bytes)
    h.update(index_bytes)
    return h.hexdigest()


def get_public_key_hex(private_key_hex):
    """Get public key hex from private key hex."""
    pk = derive_public_key(binascii.unhexlify(private_key_hex))
    return pk.hex()


def public_key_to_address(public_key_hex):
    """Convert public key to nano_ address."""
    pk_bytes = binascii.unhexlify(public_key_hex)
    # Encode public key
    account = bytes_to_nbase32(pk_bytes).decode('ascii')
    # Checksum: blake2b(pk, 5 bytes), reversed
    checksum = bytearray(
        hashlib.blake2b(pk_bytes, digest_size=5).digest()
    )
    checksum.reverse()
    checksum_b32 = bytes_to_nbase32(bytes(checksum)).decode('ascii')
    return f"nano_{account}{checksum_b32}"


def address_to_public_key(address):
    """Extract public key hex from nano_ address."""
    if not address.startswith("nano_") and not address.startswith("xrb_"):
        raise ValueError("Invalid address prefix")
    rest = address[address.index("_") + 1:]
    if len(rest) != 60:
        raise ValueError("Invalid address length")
    # First char must be 1 or 3
    if rest[0] not in ("1", "3"):
        raise ValueError("Invalid first char")
    account_b32 = rest[:52]
    checksum_b32 = rest[52:]
    # Decode
    pk_bytes = nbase32_to_bytes(account_b32)
    checksum_bytes = nbase32_to_bytes(checksum_b32)
    # Verify checksum
    expected = bytearray(
        hashlib.blake2b(pk_bytes, digest_size=5).digest()
    )
    expected.reverse()
    if bytes(expected) != checksum_bytes:
        raise ValueError("Invalid checksum")
    return pk_bytes.hex()


def is_valid_address(address):
    """Validate a Nano address."""
    try:
        address_to_public_key(address)
        return True
    except Exception:
        return False


def sign_block(block_hash_hex, private_key_hex):
    """Sign a block hash, return signature hex."""
    pk_bytes = derive_public_key(
        binascii.unhexlify(private_key_hex)
    )
    sig = sign_message(
        binascii.unhexlify(block_hash_hex),
        binascii.unhexlify(private_key_hex),
        pk_bytes
    )
    return sig.hex().upper()


def compute_block_hash(
    account_address, previous_hex, representative_address,
    balance_raw, link_hex
):
    """Compute state block hash."""
    # State block preamble
    preamble = b'\x00' * 31 + b'\x06'
    account_pk = binascii.unhexlify(
        address_to_public_key(account_address)
    )
    previous = binascii.unhexlify(previous_hex)
    rep_pk = binascii.unhexlify(
        address_to_public_key(representative_address)
    )
    balance_bytes = int(balance_raw).to_bytes(16, 'big')
    link_bytes = binascii.unhexlify(link_hex)
    data = (
        preamble + account_pk + previous +
        rep_pk + balance_bytes + link_bytes
    )
    return hashlib.blake2b(data, digest_size=32).hexdigest().upper()


def generate_address_fast(seed_bytes):
    """Fast address from raw seed bytes (no hex)."""
    # Derive private key: blake2b(seed + 0)
    h = hashlib.blake2b(digest_size=32)
    h.update(seed_bytes)
    h.update(b'\x00\x00\x00\x00')
    priv = h.digest()
    # Derive public key
    pk = derive_public_key(priv)
    # Encode to address
    account = bytes_to_nbase32(pk)
    checksum = bytearray(
        hashlib.blake2b(pk, digest_size=5).digest()
    )
    checksum.reverse()
    checksum_b32 = bytes_to_nbase32(bytes(checksum))
    return b"nano_" + account + checksum_b32


def create_wallet_from_seed(seed_hex, index=0):
    """Create wallet dict from seed."""
    priv = derive_private_key(seed_hex, index)
    pub = get_public_key_hex(priv)
    addr = public_key_to_address(pub)
    return {
        "seed": seed_hex,
        "private_key": priv,
        "public_key": pub,
        "address": addr,
        "index": index,
    }
