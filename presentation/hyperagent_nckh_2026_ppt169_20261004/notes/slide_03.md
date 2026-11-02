# Thuyết minh Slide 03: Mục tiêu nghiên cứu & Hướng tiếp cận HyperAgent

**Thời lượng khuyến nghị**: 1 phút (02:15 - 03:15)

**Nội dung thuyết minh chi tiết**:

Kính thưa Hội đồng, để giải quyết triệt để các hạn chế vừa nêu, nhóm chúng em đã xác định 4 mục tiêu nghiên cứu cụ thể cùng 3 triết lý thiết kế cốt lõi của công cụ HyperAgent:

Về **Mục tiêu nghiên cứu**, đề tài hướng tới:
1. Xây dựng một đường ống tự động hóa phân tích Hybrid kết hợp tĩnh và động dành riêng cho định dạng tệp thực thi PE trên hệ điều hành Windows.
2. Thay đổi hoàn toàn vai trò của AI: Không để AI đóng vai trò mô hình phân loại nhị phân hộp đen, mà định hình AI như một **Agent điều phối chiến lược (Orchestrator)**. AI là người đọc tình huống, ra quyết định kích hoạt công cụ ở từng chặng và đọc dữ liệu có cấu trúc.
3. Thiết lập cơ chế phán quyết dựa trên bằng chứng kỹ thuật (Evidence-bound Verdict), xóa bỏ tình trạng suy đoán vô căn cứ.
4. Xây dựng một giải pháp có thể vận hành 100% On-Premise trên một máy trạm kỹ thuật thông thường có cài đặt máy ảo, loại bỏ hoàn toàn việc gửi dữ liệu ra bên ngoài.

Để hiện thực hóa các mục tiêu này, HyperAgent được xây dựng dựa trên **3 triết lý thiết kế then chốt**:
- **Thứ nhất là Tách bạch quyền hạn**: AI tập trung vào khả năng tư duy logic và điều phối; việc dịch ngược disassembly hay bắt breakpoint được giao trọn vẹn cho các công cụ chuẩn công nghiệp là IDA Pro và x64dbg.
- **Thứ hai là Quản lý trạng thái và Đảm bảo tính tái lập**: Giữa các giai đoạn, hệ thống giao tiếp thông qua các tệp Artifact JSON được kiểm tra nghiêm ngặt theo JSON Schema. Bất kỳ giai đoạn nào bị gián đoạn đều có thể khôi phục tiếp tục nhờ tệp STATE.json.
- **Thứ ba là Cô lập an toàn**: Mọi hành vi thực thi động chỉ diễn ra trong máy ảo Windows cô lập, và hệ thống tự động hoàn nguyên về bản chụp sạch (snapshot revert) ngay khi kết thúc phân tích động, bảo đảm máy chủ luôn an toàn tuyệt đối.
