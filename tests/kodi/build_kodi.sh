#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn
#
# Build Kodi 22 for X11 from source into $KODI_PREFIX (default /opt/kodi),
# with the tools the test suite needs (Xvfb, ImageMagick, ffmpeg).
# Written for Ubuntu 24.04, which has no Kodi 22 package; run as root.
# About an hour on four cores.
set -eu

KODI_REF=${KODI_REF:-22.0rc1-Piers}
KODI_PREFIX=${KODI_PREFIX:-/opt/kodi}
BUILD_DIR=${BUILD_DIR:-/opt/kodi-build}

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q autoconf automake autopoint autotools-dev cmake curl debhelper \
  default-jre-headless doxygen gawk gcc g++ gdc gettext gperf git \
  libasound2-dev libass-dev libavahi-client-dev libavahi-common-dev libbluray-dev libbz2-dev \
  libcdio-dev libcrossguid-dev libcurl4-openssl-dev libdbus-1-dev libdrm-dev libegl1-mesa-dev \
  libenca-dev libexiv2-dev libflac-dev libfmt-dev libfontconfig-dev libfreetype6-dev libfribidi-dev \
  libfstrcmp-dev libgcrypt-dev libgif-dev libgl1-mesa-dev libgles2-mesa-dev libglu1-mesa-dev \
  libgnutls28-dev libgpg-error-dev libiso9660-dev libjpeg-dev liblcms2-dev libltdl-dev liblzo2-dev \
  libmicrohttpd-dev libnfs-dev libogg-dev libpcre2-dev libplist-dev libpng-dev libpulse-dev \
  libsmbclient-dev libspdlog-dev libsqlite3-dev libssl-dev libtag1-dev libtiff5-dev libtinyxml-dev \
  libtinyxml2-dev libtool libudev-dev libunistring-dev libva-dev libvdpau-dev libvorbis-dev \
  libxmu-dev libxrandr-dev libxslt1-dev libxt-dev lsb-release meson nasm ninja-build \
  nlohmann-json3-dev python3-dev python3-pil python3-pip swig unzip uuid-dev zip zlib1g-dev \
  libflatbuffers-dev flatbuffers-compiler bison flex libcec-dev liblirc-dev libdisplay-info-dev \
  libxkbcommon-dev libinput-dev libgbm-dev \
  xvfb x11-utils imagemagick mesa-utils libgl1-mesa-dri sqlite3 ffmpeg

# Only the packages (Kodi itself restored from a cache, as in CI).
if [ "${KODI_DEPS_ONLY:-0}" = 1 ]; then
  exit 0
fi

mkdir -p "$BUILD_DIR"
[ -d "$BUILD_DIR/src" ] || git clone --depth 1 --branch "$KODI_REF" https://github.com/xbmc/xbmc.git "$BUILD_DIR/src"
mkdir -p "$BUILD_DIR/build"
cd "$BUILD_DIR/build"
cmake ../src -G Ninja -DCMAKE_INSTALL_PREFIX="$KODI_PREFIX" -DCMAKE_BUILD_TYPE=Release \
  -DCORE_PLATFORM_NAME=x11 -DAPP_RENDER_SYSTEM=gl \
  -DENABLE_INTERNAL_SWIG=ON -DENABLE_INTERNAL_FFMPEG=ON \
  -DENABLE_INTERNAL_CROSSGUID=ON -DENABLE_INTERNAL_FLATBUFFERS=ON \
  -DENABLE_AIRTUNES=OFF -DENABLE_BLUETOOTH=OFF -DENABLE_CEC=OFF -DENABLE_LIRCCLIENT=OFF \
  -DENABLE_OPTICAL=OFF -DENABLE_DVDCSS=OFF -DENABLE_MARIADBCLIENT=OFF -DENABLE_MYSQLCLIENT=OFF \
  -DENABLE_TESTING=OFF -DENABLE_VAAPI=OFF -DENABLE_VDPAU=OFF -DENABLE_PULSEAUDIO=OFF -DENABLE_PIPEWIRE=OFF
ninja
ninja install
"$KODI_PREFIX/bin/kodi" --version | head -1
