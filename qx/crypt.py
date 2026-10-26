"""加密（2026-10-23，用户定的做法 A：公开仓库，网页要密码，判断和不公开的数据加密存放）。

两种钥匙：
  PAGE_PASSWORD  网页密码（用户自己在 GitHub Secrets 里设，代码里没有）。整页 HTML 先 gzip，再用 PBKDF2-SHA256（60 万次）
                 从密码导出 AES-256-GCM 钥匙加密；页面在浏览器里用 WebCrypto 解开。盐是固定的（只有一个密码），每次加密换随机 IV。
  DATA_KEY       32 字节随机钥匙（base64，放 GitHub Secrets 和本机 ~/.config/qx/data_key），加密两样东西：
                 data 分支上的 data.enc（data/ 下所有攒下来的小文件，包括 private/ 里的 AAII 和以后的判断），和完整期权链存档。
                 钥匙丢了，攒下来的历史就打不开了：本机那份要留好。
"""
import base64, functools, gzip, io, json, os, tarfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PAGE_SALT = b"qx-page-v1"
PAGE_ITER = 600_000
KEY_FILE = os.path.expanduser("~/.config/qx/data_key")


@functools.lru_cache(maxsize=4)
def page_key(password):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=PAGE_SALT, iterations=PAGE_ITER).derive(password.encode("utf-8"))


def encrypt_page(html, password):
    """→ {"iv", "ct"}（base64）。明文是 gzip 过的 HTML。"""
    iv = os.urandom(12)
    ct = AESGCM(page_key(password)).encrypt(iv, gzip.compress(html.encode("utf-8"), 9), None)
    return {"iv": base64.b64encode(iv).decode(), "ct": base64.b64encode(ct).decode(), "salt": PAGE_SALT.decode(), "iter": PAGE_ITER}


def encrypt_blob(text, password):
    """按需加载的小文件（第四轮第 2 步：每个标的的 K 线 site/k/*.enc）：iv(12 字节) + AES-GCM(gzip(明文))，
    和整页同一把钥匙（页面解锁后留在 window.QX_KEY），浏览器用 WebCrypto 解。"""
    iv = os.urandom(12)
    return iv + AESGCM(page_key(password)).encrypt(iv, gzip.compress(text.encode("utf-8"), 9), None)


def data_key():
    k = os.environ.get("DATA_KEY", "").strip()
    if not k and os.path.exists(KEY_FILE):
        k = open(KEY_FILE).read().strip()
    if not k:
        return None
    b = base64.b64decode(k)
    assert len(b) == 32, "DATA_KEY 要是 32 字节的 base64"
    return b


def seal(data, key):
    iv = os.urandom(12)
    return b"QX1" + iv + AESGCM(key).encrypt(iv, data, None)


def unseal(blob, key):
    assert blob[:3] == b"QX1", "不是加密文件"
    return AESGCM(key).decrypt(blob[3:15], blob[15:], None)


def pack_dir(src, out, key, skip=()):
    """把目录打成 tar.gz 再加密，写到 out。skip：不打包的子目录名。"""
    buf = io.BytesIO()
    drop = tuple("./" + x for x in skip)
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(src, arcname=".", filter=lambda ti: None if ti.name in drop or ti.name.startswith(tuple(d + "/" for d in drop)) else ti)
    with open(out, "wb") as f:
        f.write(seal(buf.getvalue(), key))


def unpack_dir(blob_path, dst, key):
    with open(blob_path, "rb") as f:
        data = unseal(f.read(), key)
    os.makedirs(dst, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        t.extractall(dst, filter="data")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["newkey"]:
        print(base64.b64encode(os.urandom(32)).decode())
