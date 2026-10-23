"""生成页面：模板 + 数据 + k.js → 单文件 HTML；有密码时整页加密，套上密码页（page/gate.html）。
没有密码就不生成要发布的页面（绝不发布明文），只在本机生成预览。"""
import json, os

from qx import crypt

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(HERE, "page")


def html(data):
    tpl = open(os.path.join(PAGE, "template.html"), encoding="utf-8").read()
    js = open(os.path.join(PAGE, "k.js"), encoding="utf-8").read()
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    script = "<script>\nconst RAW = " + raw + ";\n" + js + "\n</script>"
    assert '<script src="k.js"></script>' in tpl
    return tpl.replace('<script src="k.js"></script>', script)


def gate(page_html, password):
    tpl = open(os.path.join(PAGE, "gate.html"), encoding="utf-8").read()
    return tpl.replace("__PAYLOAD__", json.dumps(crypt.encrypt_page(page_html, password)))


def write(data, out_dir, password=None, preview=None):
    """out_dir/index.html：加密页（有密码才写）。preview：本机明文预览的路径（不发布）。"""
    h = html(data)
    if preview:
        os.makedirs(os.path.dirname(preview), exist_ok=True)
        open(preview, "w", encoding="utf-8").write(h)
    if password:
        os.makedirs(out_dir, exist_ok=True)
        open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(gate(h, password))
        open(os.path.join(out_dir, ".nojekyll"), "w").close()
        return True
    return False
