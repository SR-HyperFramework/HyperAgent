# Thuyết minh Slide 05: Kiến trúc tổng thể hệ thống & Giao thức MCP

**Thời lượng khuyến nghị**: 1 phút 15 giây (04:30 - 05:45)

**Nội dung thuyết minh chi tiết**:

Kính thưa Hội đồng, trên màn hình là **Hình 1 — Sơ đồ kiến trúc tổng thể và cơ chế giao tiếp của HyperAgent**. Kiến trúc này được thiết kế phân tầng mạch lạc thành 3 khối chính:

**Khối thứ nhất — Tầng Đầu vào & Ràng buộc khởi tạo**:
Đầu vào duy nhất của hệ thống là mẫu tệp thực thi PE được định danh bảo mật bằng mã băm SHA256. Để đảm bảo tính chuẩn hóa, mỗi lượt phân tích đều được nạp kèm tệp cấu hình kỹ năng chuyên trách (`SKILL.md`) và bộ JSON Schema bắt buộc cho từng giai đoạn, giúp định hình chính xác phạm vi công cụ mà AI được phép sử dụng.

**Khối thứ hai — Lõi điều phối AI (Orchestration Engine) qua giao thức MCP**:
Đây chính là "bộ não" của hệ thống. Thay vì gọi qua các tiến trình phụ cồng kềnh, HyperAgent xây dựng vòng lặp `AgentLoop` trực tiếp qua SDK LLM. AI điều phối toàn bộ các công cụ phân tích ngoại vi thông qua **Model Context Protocol (MCP)** — giao thức kết nối chuẩn mở tiên tiến nhất hiện nay:
- Về phân tích tĩnh: AI giao tiếp với **IDA Pro MCP server** để thực hiện dịch ngược mã máy, phân tích cấu trúc Header, PE Sections, trích xuất bảng Imports/Exports và các chuỗi khả nghi.
- Về phân tích động: AI điều phối công cụ **x64dbg** đặt trong một máy ảo Windows hoàn toàn cô lập thông qua cầu nối RPC an toàn. AI có thể điều khiển đặt Breakpoint tại Original Entry Point (OEP), bước từng dòng lệnh, đọc bộ nhớ và thanh ghi. Điều quan trọng nhất: ngay sau khi kết thúc phân tích động, máy ảo sẽ tự động khôi phục về snapshot sạch (Clean Snapshot Revert), triệt tiêu hoàn toàn khả năng mã độc lây nhiễm ngược ra máy trạm.
- Về tình báo mối đe dọa: Tùy chọn kết nối với VirusTotal API để làm giàu thông tin nhận diện mối nguy.

**Khối thứ ba — Tầng Đầu ra đa cấp độ**:
Kết thúc quy trình, HyperAgent sản sinh ra hệ thống đầu ra phong phú:
- Toàn bộ các Artifact JSON trung gian của từng giai đoạn được lưu lại đầy đủ theo đúng schema quy chuẩn, phục vụ mục đích kiểm toán và nghiên cứu.
- Bản báo cáo điều tra kỹ thuật hoàn chỉnh dưới định dạng Markdown (`08-report.md`) cung cấp đầy đủ chuỗi bằng chứng.
- Tệp tóm tắt phán quyết (`09-summary.json`) định dạng có cấu trúc để hiển thị trực tiếp lên giao diện Web Dashboard cho chuyên viên theo dõi.
- Cuối cùng là bộ dữ liệu đo lường Telemetry ghi nhận chi tiết số lượng token tiêu thụ, chi phí API và thời gian xử lý từng chặng.

Tiếp theo, em xin đi sâu vào chi tiết của từng giai đoạn trong quy trình 9 bước này.
