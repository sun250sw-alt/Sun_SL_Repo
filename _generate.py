"""
_generate.py — Run this from Sun_SL_Repo/ after any addon update.
Rebuilds addons.xml, addons.xml.md5 and individual addon ZIPs.

Usage:  python3 _generate.py
"""
import os, hashlib, zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
SKIP = {"_generate.py", ".git", ".gitignore", "addons.xml",
        "addons.xml.md5", "README.md"}


def addon_dirs():
    for name in sorted(os.listdir(ROOT)):
        full = os.path.join(ROOT, name)
        if not os.path.isdir(full):
            continue
        if name in SKIP or name.startswith("."):
            continue
        if os.path.isfile(os.path.join(full, "addon.xml")):
            yield name, full


def build_addons_xml():
    addons = ET.Element("addons")
    for name, full in addon_dirs():
        try:
            root = ET.parse(os.path.join(full, "addon.xml")).getroot()
            addons.append(root)
            print("  + {}".format(name))
        except Exception as e:
            print("  ! skip {} — {}".format(name, e))

    tree = ET.ElementTree(addons)
    ET.indent(tree, space="    ")
    out = os.path.join(ROOT, "addons.xml")
    with open(out, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)
    print("Wrote addons.xml")
    return out


def build_md5(path):
    md5 = hashlib.md5(open(path, "rb").read()).hexdigest()
    with open(path + ".md5", "w") as f:
        f.write(md5)
    print("Wrote addons.xml.md5  [{}]".format(md5))


def build_zips():
    for name, full in addon_dirs():
        try:
            ver = ET.parse(os.path.join(full, "addon.xml")).getroot().get("version", "1.0.0")
        except Exception:
            ver = "1.0.0"
        zip_name = "{}-{}.zip".format(name, ver)
        zip_path = os.path.join(full, zip_name)
        # Remove old zips first
        for f in os.listdir(full):
            if f.endswith(".zip"):
                os.remove(os.path.join(full, f))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, dirs, files in os.walk(full):
                dirs[:] = [d for d in dirs
                           if d not in ("__pycache__",) and not d.startswith(".")]
                for fname in files:
                    if fname.endswith(".pyc") or fname == zip_name:
                        continue
                    abs_p = os.path.join(dirpath, fname)
                    arc_p = os.path.relpath(abs_p, ROOT)
                    zf.write(abs_p, arc_p)
        print("  ZIP: {}".format(zip_name))


if __name__ == "__main__":
    print("\n=== Building Sun SL Repository ===\n")
    print("Collecting addons:")
    xml_path = build_addons_xml()
    build_md5(xml_path)
    print("\nBuilding addon ZIPs:")
    build_zips()
    print("\nDone! Commit and push everything to GitHub.")
