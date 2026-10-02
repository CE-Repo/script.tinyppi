# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Build the Kodi profile template every test run copies (driver.make_home).

The template has Kodi's web server on (JSON-RPC on 8080, user kodi/kodi),
debug logging, short resume thresholds (the test clips are short), the two
media sources with their content set, script.module.sidedata and the test
helper add-on.  ``--force`` builds it again.
"""

import os
import shutil
import subprocess
import sys
import time

import config
import driver

GUI_SETTINGS = """<settings version="2">
    <setting id="services.webserver">true</setting>
    <setting id="services.webserverport">8080</setting>
    <setting id="services.webserverauthentication">true</setting>
    <setting id="services.webserverusername">kodi</setting>
    <setting id="services.webserverpassword">kodi</setting>
    <setting id="services.esenabled">true</setting>
    <setting id="general.addonupdates">2</setting>
    <setting id="general.addonnotifications">false</setting>
    <setting id="videoplayer.usevaapi">false</setting>
    <setting id="videoplayer.usevdpau">false</setting>
    <setting id="locale.language">resource.language.en_gb</setting>
</settings>
"""
ADVANCED_SETTINGS = """<advancedsettings version="1.0">
    <loglevel>1</loglevel>
    <video>
        <ignoresecondsatstart>5</ignoresecondsatstart>
        <ignorepercentatend>3</ignorepercentatend>
    </video>
</advancedsettings>
"""
SOURCES = f"""<sources>
    <video>
        <default pathversion="1"></default>
        <source><name>Movies</name><path pathversion="1">{config.MEDIA}/movies/</path><allowsharing>true</allowsharing></source>
        <source><name>TV</name><path pathversion="1">{config.MEDIA}/tv/</path><allowsharing>true</allowsharing></source>
    </video>
</sources>
"""


def sidedata(addons):
    """Fetch TinyPPI's dependency (its native parser is for aarch64 only)."""
    dest = os.path.join(addons, "script.module.sidedata")
    cache = os.path.join(config.ROOT, "script.module.sidedata")
    if not os.path.isdir(cache):
        subprocess.run(["git", "clone", "--depth", "1", config.SIDEDATA_URL, cache], check=True)
    shutil.copytree(cache, dest, ignore=shutil.ignore_patterns(".git"))


def main():
    if os.path.isdir(config.TEMPLATE) and "--force" not in sys.argv:
        print(f"template exists: {config.TEMPLATE}")
        return
    shutil.rmtree(config.TEMPLATE, ignore_errors=True)
    userdata = os.path.join(config.TEMPLATE, ".kodi", "userdata")
    addons = os.path.join(config.TEMPLATE, ".kodi", "addons")
    os.makedirs(userdata)
    os.makedirs(addons)
    for name, text in (("guisettings.xml", GUI_SETTINGS), ("advancedsettings.xml", ADVANCED_SETTINGS),
                       ("sources.xml", SOURCES)):
        with open(os.path.join(userdata, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    sidedata(addons)
    driver.install_helper(config.TEMPLATE)

    kodi = driver.Kodi(config.TEMPLATE)
    print(f"Kodi answered after {kodi.start():.1f} s")
    driver.enable("script.module.sidedata", "script.tinyppi.testhelper")
    time.sleep(3)
    kodi.quit()
    kodi.stop_display()
    driver.set_path_content(config.TEMPLATE)
    os.remove(kodi.log_path)
    print(f"template ready: {config.TEMPLATE}")


if __name__ == "__main__":
    main()
