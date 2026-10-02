# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Make the test media: clips with HDR10 metadata, several tracks and
chapters, plain gray clips for the screenshot measurements, and a small
film and series library with NFO files and artwork.

Needs ffmpeg (libx264, libx265, eac3, aac) and ImageMagick.  Existing files
are kept; ``--force`` makes everything again.
"""

import os
import shutil
import subprocess
import sys

import config

SRC = os.path.join(config.MEDIA, "src")
HDR10_PARAMS = ("hdr-opt=1:repeat-headers=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:"
                "master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,50):"
                "max-cll=1000,400:log-level=error")
HDR10_COLOUR = ["-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"]
COLOURS = ["#7a1f1f", "#1f4f7a", "#2f6b2f", "#6b5a1f", "#4a1f6b", "#1f6b66"]


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def poster(path, size, colour, text=""):
    command = ["convert", "-size", size, f"xc:{colour}"]
    if text:
        command += ["-gravity", "center", "-pointsize", "48", "-fill", "white", "-annotate", "0", text]
    subprocess.run(command + [path], check=True)


def clips():
    os.makedirs(SRC, exist_ok=True)
    subs = os.path.join(SRC, "subs.srt")
    with open(subs, "w", encoding="utf-8") as handle:
        handle.write("1\n00:00:01,000 --> 00:00:05,000\nTinyPPI subtitle test\n\n"
                     "2\n00:00:10,000 --> 00:00:20,000\nSecond subtitle line\n")
    chapters = os.path.join(SRC, "chapters.txt")
    with open(chapters, "w", encoding="utf-8") as handle:
        handle.write(";FFMETADATA1\n" + "".join(
            f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start}\nEND={start + 30000}\ntitle=Part {n}\n"
            for n, start in enumerate((0, 30000, 60000), 1)))
    if not os.path.exists(config.HDR10_CLIP):
        # HDR10 HEVC 10-bit, E-AC-3 5.1 + AC-3 2.0, subtitles, three chapters.
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24000/1001:duration=90",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=90:sample_rate=48000",
               "-f", "lavfi", "-i", "sine=frequency=660:duration=90:sample_rate=48000",
               "-i", subs, "-i", chapters,
               "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s", "-map_metadata", "4", "-map_chapters", "4",
               "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le", "-x265-params", HDR10_PARAMS,
               *HDR10_COLOUR, "-c:a:0", "eac3", "-ac:a:0", "6", "-b:a:0", "384k",
               "-c:a:1", "ac3", "-ac:a:1", "2", "-b:a:1", "192k",
               "-metadata:s:a:0", "language=eng", "-metadata:s:a:0", "title=English 5.1",
               "-metadata:s:a:1", "language=deu", "-metadata:s:a:1", "title=Deutsch 2.0",
               "-c:s", "srt", "-metadata:s:s:0", "language=eng", config.HDR10_CLIP)
    sdr = os.path.join(SRC, "sdr.mp4")
    if not os.path.exists(sdr):
        ffmpeg("-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25:duration=60",
               "-f", "lavfi", "-i", "sine=frequency=330:duration=60:sample_rate=48000",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", sdr)
    if not os.path.exists(config.GRAY_HDR10):
        # A plain gray picture: the panels are measured on it by colour.
        ffmpeg("-f", "lavfi", "-i", "color=c=0x808080:size=1280x720:rate=24000/1001:duration=150",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=150:sample_rate=48000", "-i", subs,
               "-map", "0:v", "-map", "1:a", "-map", "2:s",
               "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le", "-x265-params", HDR10_PARAMS,
               *HDR10_COLOUR, "-c:a", "eac3", "-ac", "6", "-b:a", "384k", "-c:s", "srt", config.GRAY_HDR10)
    if not os.path.exists(config.GRAY_SDR):
        ffmpeg("-f", "lavfi", "-i", "color=c=0x808080:size=1280x720:rate=25:duration=150",
               "-f", "lavfi", "-i", "sine=frequency=330:duration=150:sample_rate=48000",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2",
               config.GRAY_SDR)
    return sdr


def library(sdr):
    """30 films (every third HDR10) and two series of 2 x 3 episodes."""
    movies = os.path.join(config.MEDIA, "movies")
    if os.path.isdir(movies):
        return
    titles = ["Dunkirk", "Oppenheimer"] + [f"Test Film {i:02d}" for i in range(1, 29)]
    for n, title in enumerate(titles):
        year = {"Dunkirk": 2017, "Oppenheimer": 2023}.get(title, 2000 + n)
        hdr = n % 3 == 0
        name = f"{title} ({year})"
        folder = os.path.join(movies, name)
        os.makedirs(folder)
        os.link(config.HDR10_CLIP if hdr else sdr, os.path.join(folder, f"{name}.{'mkv' if hdr else 'mp4'}"))
        with open(os.path.join(folder, f"{name}.nfo"), "w", encoding="utf-8") as handle:
            handle.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<movie><title>{title}</title>'
                         f"<originaltitle>{title}</originaltitle><year>{year}</year><plot>Plot of {title}.</plot>"
                         f"<runtime>{90 if hdr else 60}</runtime><ratings><rating name=\"imdb\" max=\"10\" default=\"true\">"
                         f"<value>{5 + n % 5 + 0.3:.1f}</value><votes>1000</votes></rating></ratings><genre>Drama</genre>"
                         f"<dateadded>2026-09-{n % 28 + 1:02d} 12:00:00</dateadded></movie>\n")
        # Every fourth poster is a PNG: Kodi's cache keeps it as JPEG.
        poster(os.path.join(folder, f"{name}-poster.{'png' if n % 4 == 1 else 'jpg'}"), "600x900",
               COLOURS[n % len(COLOURS)], title)
        if n < 4:
            poster(os.path.join(folder, f"{name}-fanart.jpg"), "1920x1080", COLOURS[(n + 2) % len(COLOURS)])
    for s, show in enumerate(["Test Show Alpha", "Test Show Beta"]):
        folder = os.path.join(config.MEDIA, "tv", show)
        os.makedirs(folder)
        with open(os.path.join(folder, "tvshow.nfo"), "w", encoding="utf-8") as handle:
            handle.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<tvshow><title>{show}</title><year>{2010 + s}</year>'
                         f'<plot>Plot.</plot><ratings><rating name="imdb" max="10" default="true"><value>8.{s}</value>'
                         "<votes>10</votes></rating></ratings></tvshow>\n")
        poster(os.path.join(folder, "poster.jpg"), "600x900", COLOURS[s + 3], show)
        for season in (1, 2):
            season_folder = os.path.join(folder, f"Season {season}")
            os.makedirs(season_folder)
            for episode in (1, 2, 3):
                name = f"{show} S{season:02d}E{episode:02d}"
                os.link(sdr, os.path.join(season_folder, f"{name}.mp4"))
                with open(os.path.join(season_folder, f"{name}.nfo"), "w", encoding="utf-8") as handle:
                    handle.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<episodedetails><title>Episode {season}x{episode}'
                                 f"</title><season>{season}</season><episode>{episode}</episode><plot>.</plot>"
                                 "<runtime>1</runtime></episodedetails>\n")


def main():
    if "--force" in sys.argv:
        shutil.rmtree(config.MEDIA, ignore_errors=True)
    library(clips())
    print(f"media ready in {config.MEDIA}")


if __name__ == "__main__":
    main()
