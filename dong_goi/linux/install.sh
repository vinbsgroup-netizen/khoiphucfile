#!/bin/sh
# Cài Khôi Phục File vào /opt/khoiphucfile. Chạy: sudo ./install.sh
set -e
if [ "$(id -u)" -ne 0 ]; then
    echo "Cần quyền root. Chạy lại: sudo ./install.sh"
    exit 1
fi
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
rm -rf /opt/khoiphucfile
cp -a "$here/khoiphucfile" /opt/khoiphucfile
chown -R root:root /opt/khoiphucfile
chmod 755 /opt/khoiphucfile
ln -sf /opt/khoiphucfile/khoiphucfile /usr/bin/khoiphucfile
ln -sf /opt/khoiphucfile/khoiphuc /usr/bin/khoiphuc
install -D -m 644 "$here/khoiphucfile.desktop" /usr/share/applications/khoiphucfile.desktop
install -D -m 644 "$here/vn.vinbs.khoiphucfile.policy" /usr/share/polkit-1/actions/vn.vinbs.khoiphucfile.policy
install -D -m 644 "$here/khoiphucfile.png" /usr/share/icons/hicolor/256x256/apps/khoiphucfile.png
echo "Đã cài xong. Mở từ menu ứng dụng, hoặc gõ: khoiphucfile"
