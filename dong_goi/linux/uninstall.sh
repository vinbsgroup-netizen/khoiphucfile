#!/bin/sh
# Gỡ Khôi Phục File (không đụng tới file đã cứu). Chạy: sudo ./uninstall.sh
set -e
if [ "$(id -u)" -ne 0 ]; then
    echo "Cần quyền root. Chạy lại: sudo ./uninstall.sh"
    exit 1
fi
rm -rf /opt/khoiphucfile
rm -f /usr/bin/khoiphucfile /usr/bin/khoiphuc \
    /usr/share/applications/khoiphucfile.desktop \
    /usr/share/polkit-1/actions/vn.vinbs.khoiphucfile.policy \
    /usr/share/icons/hicolor/256x256/apps/khoiphucfile.png
echo "Đã gỡ xong."
