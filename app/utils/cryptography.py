import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from app.config import config


def encrypt_wp_id(wp_id: str) -> str:
    """
    Шифрует wp_id с использованием AES-CBC.
    """
    cipher = AES.new(config.AES_KEY, AES.MODE_CBC, config.AES_IV)
    encrypted_data = cipher.encrypt(pad(wp_id.encode(), AES.block_size))
    return base64.b64encode(encrypted_data).decode()

def decrypt_wp_id(encrypted_wp_id: str) -> str:
    """
    Расшифровывает зашифрованный wp_id.
    """
    cipher = AES.new(config.AES_KEY, AES.MODE_CBC, config.AES_IV)
    decrypted_data = unpad(cipher.decrypt(base64.b64decode(encrypted_wp_id)), AES.block_size)
    return decrypted_data.decode()
