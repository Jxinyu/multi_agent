from __future__ import annotations

import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

REPO_ROOT = Path(__file__).resolve().parents[1]
KEY_DIR = REPO_ROOT / "multi_domain_enterprise_project" / "mcp_server"
PRIVATE_KEY = KEY_DIR / "private_key"
PUBLIC_KEY = KEY_DIR / "public_key"


def generate_keys(if_missing: bool) -> None:
    if if_missing and PRIVATE_KEY.is_file() and PUBLIC_KEY.is_file():
        return
    if PRIVATE_KEY.exists() or PUBLIC_KEY.exists():
        raise RuntimeError("密钥文件只存在一个或请求覆盖；请先人工确认并移走旧文件")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    PRIVATE_KEY.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    PUBLIC_KEY.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"开发密钥已生成: {KEY_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成本地 development JWT 密钥")
    parser.add_argument("--if-missing", action="store_true", help="两个密钥都存在时不做修改")
    args = parser.parse_args()
    generate_keys(args.if_missing)


if __name__ == "__main__":
    main()
