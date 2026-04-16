"""
contextmenu.py — Context menu entry for Kodi 21
================================================
Kodi calls this when building the context menu.
We add "Subtitle Translator" as a menu item.
When tapped Kodi executes the RunScript builtin.
"""
import sys
import xbmc
import xbmcgui
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")


def main():
    # Kodi 21 context menu: return a list of (label, action) tuples
    # via sys.argv or via the contextmenu API depending on build.
    # The safest approach that works on all Kodi 21 builds:
    try:
        handle = int(sys.argv[1])
    except (IndexError, ValueError):
        handle = -1

    import xbmcplugin
    item = xbmcgui.ListItem(label="Subtitle Translator")
    item.setArt({"icon": "DefaultSubtitles.png"})
    item.setProperty("IsPlayable", "false")

    xbmcplugin.addDirectoryItem(
        handle=handle,
        url="plugin://{}/?action=menu".format(ADDON_ID),
        listitem=item,
        isFolder=False
    )
    xbmcplugin.endOfDirectory(handle)


if __name__ == "__main__":
    # When called as plugin:// — launch the main script
    xbmc.executebuiltin("RunScript({})".format(
        xbmcaddon.Addon().getAddonInfo("id")))
