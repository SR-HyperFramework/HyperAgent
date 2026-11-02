# Thuyết minh Slide 06: Quy trình 9 giai đoạn chi tiết

**Thời lượng khuyến nghị**: 1 phút 15 giây (05:45 - 07:00)

**Nội dung thuyết minh chi tiết**:

Kính thưa Hội đồng, slide này thể hiện chi tiết **Quy trình 9 giai đoạn** của HyperAgent, được chia thành hai pha kế tiếp nhau vô cùng mạch lạc:

**Pha thứ nhất: Thu thập bằng chứng đa tầng (Giai đoạn 01 đến 05)**:
- **Giai đoạn 01 (Chuẩn bị - 01-prepare-env)**: Hệ thống thực hiện kiểm tra tính sẵn sàng của môi trường, kiểm tra kết nối tới máy ảo guest VM, xác nhận snapshot sạch và gán định danh SHA256 cho mẫu.
- **Giai đoạn 02 (Tĩnh lần 1 - 02-static-pass1)**: Kích hoạt IDA Pro để trích xuất cấu trúc PE Header, bảng phân vùng Sections, mức độ entropy, và danh sách các API Imports/Exports ban đầu.
- **Giai đoạn 03 (Giải nén - 03-unpack)**: Nếu mẫu có dấu hiệu bị nén (packed) hoặc làm rối (obfuscated), AI sẽ điều phối x64dbg trong máy ảo để dò tìm điểm vào gốc (Original Entry Point - OEP), chạy vượt qua các lớp giải mã và trích xuất (dump) tệp thực thi sạch ra đĩa.
- **Giai đoạn 04 (Tĩnh lần 2 - 04-static-pass2)**: Đây là một bước đột phá then chốt của đề tài. Hệ thống đưa tệp mã vừa giải nén quay trở lại IDA Pro để phân tích tĩnh lần 2. Nhờ đó, các chuỗi kết nối máy chủ điều khiển (C2), địa chỉ IP, và các API độc hại vốn bị giấu kín hoàn toàn lộ diện trước mắt điều tra viên.
- **Giai đoạn 05 (Động - 05-dynamic)**: Mẫu được cho thực thi trong môi trường máy ảo có kiểm soát. x64dbg gắn các breakpoint để ghi nhận hành vi can thiệp Registry, tạo tiến trình con, và kết nối mạng. Ngay khi giai đoạn này kết thúc, máy ảo sẽ tự động khôi phục sạch bản chụp (Snapshot Revert).

**Pha thứ hai: Đối chiếu và Lập báo cáo có kiểm chứng (Giai đoạn 06 đến 09)**:
- **Giai đoạn 06 (Tình báo - 06-intel)**: Tra cứu mã băm trên VirusTotal. Giai đoạn này được vẽ nét đứt vì nó mang tính tùy chọn (opt-in) — khi triển khai trong môi trường mạng quân sự hoặc cô lập không có internet, hệ thống hoàn toàn có thể bỏ qua bước này mà vẫn vận hành trơn tru.
- **Giai đoạn 07 (Đối chiếu chuyên sâu - 07-deepdive)**: AI thực hiện suy luận chéo giữa bằng chứng tĩnh và động, áp dụng bộ lọc 3 trạng thái phán quyết: *Được phép, Có điều kiện, hoặc Bị cấm*, loại bỏ mọi suy diễn không có căn cứ.
- **Giai đoạn 08 (Báo cáo - 08-report)**: Tự động biên soạn báo cáo kỹ thuật toàn diện dưới dạng Markdown, trích dẫn chi tiết từng offset địa chỉ và mã ASM thực tế.
- **Giai đoạn 09 (Tóm tắt - 09-summary)**: Xuất ra tệp JSON phán quyết có cấu trúc chứa thông tin phân loại nhị phân và danh mục các chỉ số nhận diện IoC để giao diện Web Dashboard đọc và cảnh báo cho chuyên viên SOC.
