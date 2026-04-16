"""
_generate_repo.py
=================
Run this script from the Sun_SL_Repo root folder whenever you
update an addon. It rebuilds addons.xml and addons.xml.md5.

Usage:
  python3 _generate_repo.py
"""

import os
import hashlib
import xml.etree.ElementTree as ET

REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def get_addon_xml(folder):
    path = os.path.join(REPO_DIR, folder, "addon.xml")
    if os.path.isfile(path):
        return path
    return None


def build_addons_xml():
    addons = ET.Element("addons")

    for folder in sorted(os.listdir(REPO_DIR)):
        full = os.path.join(REPO_DIR, folder)
        if not os.path.isdir(full):
            continue
        if folder.startswith(".") or folder.startswith("_"):
            continue

        xml_path = get_addon_xml(folder)
        if not xml_path:
            continue

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            addons.append(root)
            print("  + {}".format(folder))
        except Exception as e:
            print("  ! Skipping {} — {}".format(folder, e))

    tree = ET.ElementTree(addons)
    ET.indent(tree, space="  ")

    out_path = os.path.join(REPO_DIR, "addons.xml")
    with open(out_path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)

    print("\nWrote: addons.xml")
    return out_path


def build_md5(addons_xml_path):
    with open(addons_xml_path, "rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    md5_path = addons_xml_path + ".md5"
    with open(md5_path, "w") as f:
        f.write(md5)
    print("Wrote: addons.xml.md5  ({})".format(md5))


def build_addon_zips():
    """Create/update individual addon ZIPs that Kodi downloads."""
    import zipfile

    for folder in sorted(os.listdir(REPO_DIR)):
        full = os.path.join(REPO_DIR, folder)
        if not os.path.isdir(full):
            continue
        if folder.startswith(".") or folder.startswith("_"):
            continue
        if not get_addon_xml(folder):
            continue

        # Read version from addon.xml
        try:
            tree = ET.parse(os.path.join(full, "addon.xml"))
            version = tree.getroot().get("version", "1.0.0")
        except Exception:
            version = "1.0.0"

        zip_name = "{}-{}.zip".format(folder, version)
        zip_path = os.path.join(REPO_DIR, folder, zip_name)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(full):
                # Skip hidden and pycache
                dirs[:] = [d for d in dirs
                           if not d.startswith(".") and d != "__pycache__"]
                for file in files:
                    if file.endswith(".pyc") or file == zip_name:
                        continue
                    abs_path = os.path.join(root, file)
                    arc_path = os.path.relpath(abs_path, REPO_DIR)
                    zf.write(abs_path, arc_path)

        print("  ZIP: {}".format(zip_name))


if __name__ == "__main__":
    print("Building Sun SL Repository...\n")
    print("Collecting addons:")
    xml_path = build_addons_xml()
    build_md5(xml_path)
    print("\nBuilding addon ZIPs:")
    build_addon_zips()
    print("\nDone! Commit and push all files to GitHub.")
