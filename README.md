# Khôi Phục File

Cứu ảnh, video, âm thanh và tài liệu từ ổ đĩa đã xoá, format hoặc bị ghi đè. Chạy trên Windows, macOS và Linux.
Nhà phát triển: VINBS (vinbsgroup@gmail.com). Sử dụng miễn phí theo
[Điều khoản sử dụng](khoiphucfile/van_ban/dieu_khoan_su_dung.md) và [Nội quy sử dụng](khoiphucfile/van_ban/noi_quy_su_dung.md).

Ứng dụng đọc thô từng sector của ổ (chỉ đọc), nhận ra đầu file và chép file ra một ổ khác. Vì không cần bảng tên file nên
vẫn cứu được khi bảng đó đã mất; đổi lại tên gốc không còn, file được đặt tên theo ngày chụp/tạo và vị trí trên ổ.

## Cài đặt

| Hệ điều hành | Tải | Cách cài |
| --- | --- | --- |
| Windows 10/11 64-bit | `.msi` | Nháy đúp, đồng ý điều khoản, bấm Cài đặt. Có biểu tượng ở Desktop và Start. |
| Windows, không cài | `-khong-can-cai.zip` | Giải nén, chạy `KhoiPhucFile.exe`. |
| macOS 12 trở lên | `.dmg` | Kéo vào Applications. |
| Ubuntu, Debian, Mint | `.deb` | `sudo apt install ./KhoiPhucFile-1.0.1-linux-amd64.deb` |
| Linux khác | `.tar.gz` | Giải nén, `sudo ./install.sh` |
| Mọi hệ có Python 3.10+ | `.whl` | `pipx install ./khoiphucfile-1.0.1-py3-none-any.whl` rồi gõ `khoiphucfile` |

Bộ cài chưa ký số nên lần đầu hệ điều hành sẽ cảnh báo:

- Windows SmartScreen: **More info › Run anyway**.
- macOS: mở một lần, rồi vào **System Settings › Privacy & Security › Open Anyway**.

Quyền đọc ổ: Windows hỏi UAC khi mở ứng dụng; macOS và Linux hỏi mật khẩu quản trị lúc bắt đầu quét. Trên macOS, nếu nhập
đúng mật khẩu mà vẫn bị từ chối, bật **Full Disk Access** cho Khôi Phục File.

## Dùng

1. Chọn ổ cần cứu, hoặc một file ảnh đĩa (`.img`, `.dd`, `.iso`).
2. Chọn thư mục lưu **trên ổ khác** và loại file. Ứng dụng từ chối nếu thư mục lưu nằm trên chính ổ đang cứu.
3. Bấm Bắt đầu quét. Có thể dừng bất cứ lúc nào và quét tiếp sau, kể cả khi rút ổ hay mất điện.

Dòng lệnh (dùng được trong script, khi không có màn hình):

```
khoiphuc disks
khoiphuc scan HM160HI --out D:\KhoiPhuc --start-gb 9.6
khoiphuc scan /dev/sdb --out ~/KhoiPhuc --types anh,video
khoiphuc about
```

## Giới hạn

- Chỉ lấy trọn vẹn file nằm liền một mạch. Ảnh JPEG bị đứt được lưu phần đầu trong thư mục `jpg_khong_tron_ven`.
- Không cứu được dữ liệu SSD đã TRIM, hay ổ đang mã hoá (BitLocker, FileVault, LUKS) vì đọc thô chỉ thấy dữ liệu đã mã hoá.
  Máy Mac chip Apple và Mac có chip T2 luôn mã hoá ổ trong; ứng dụng hữu ích với ổ ngoài, thẻ nhớ, USB.

## Phát triển

```
python -m venv .venv
.venv/Scripts/python -m pip install -r dong_goi/requirements.txt     (Linux, macOS: .venv/bin/python)
.venv/Scripts/python -m khoiphucfile                                 mở giao diện
.venv/Scripts/python -m unittest discover -s tests -t .              chạy test
.venv/Scripts/python dong_goi/build.py                               đóng gói vào ban_phat_hanh/
```

Mỗi bản phải đóng gói trên đúng hệ điều hành của nó. `.github/workflows/dong_goi.yml` làm việc đó cho cả ba hệ trên
GitHub Actions: đẩy mã lên GitHub rồi tải các bản cài ở tab Actions; đẩy thẻ `v1.0.1` thì tự tạo bản phát hành.

- Thông tin nhà phát triển (website, điện thoại, địa chỉ): [khoiphucfile/developer.py](khoiphucfile/developer.py)
- Điều khoản, nội quy: [khoiphucfile/van_ban/](khoiphucfile/van_ban/). Sửa xong nhớ đổi `TERMS_VERSION` trong developer.py.
- Biểu tượng: thay `dong_goi/icons/nguon.png` rồi chạy `python dong_goi/make_icons.py`.
