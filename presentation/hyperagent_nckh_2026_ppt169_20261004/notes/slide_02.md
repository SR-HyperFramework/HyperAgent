# Thuyết minh Slide 02: Đặt vấn đề & Thách thức thực tiễn

**Thời lượng khuyến nghị**: 1 phút 15 giây (01:00 - 02:15)

**Nội dung thuyết minh chi tiết**:

Kính thưa Hội đồng, để làm rõ tính cấp thiết của đề tài, trước hết em xin điểm qua 3 nút thắt chí tử mà các chuyên viên an ninh mạng và đội ứng cứu sự cố (CSIRT) đang phải đối mặt hàng ngày trong công tác phân tích tệp thực thi độc hại (PE malware):

Thứ nhất là **Sự rời rạc của các công cụ và gánh nặng phụ thuộc con người**: 
Hiện nay, một quy trình dịch ngược mã độc chuẩn mực đòi hỏi chuyên viên phải mở cùng lúc nhiều phần mềm riêng lẻ: từ IDA Pro để phân tích tĩnh cú pháp mã máy, x64dbg để gỡ lỗi và theo dõi thanh ghi động, cho tới các sandbox nội bộ và nền tảng tình báo như VirusTotal. Việc chuyển đổi ngữ cảnh thủ công giữa các công cụ này tiêu tốn từ 2 đến 3 tiếng cho mỗi mẫu nghi vấn, dễ sai sót, và báo cáo kết quả hoàn toàn phụ thuộc vào kinh nghiệm chủ quan của từng cá nhân.

Thứ hai là **Rào cản bảo mật của các Sandbox đám mây thương mại**: 
Hầu hết các giải pháp phân tích hành vi tự động hiện đại đều chạy dưới dạng dịch vụ Cloud thương mại khép kín. Để sử dụng, doanh nghiệp bắt buộc phải tải tệp thực thi ra môi trường bên ngoài biên giới tổ chức. Điều này tiềm ẩn nguy cơ rò rỉ các tệp tin nội bộ, bí mật kinh doanh, hoặc vi phạm nghiêm ngặt quy định an toàn thông tin quốc gia.

Thứ ba là **Nguy cơ tiềm ẩn khi áp dụng AI trực tiếp theo kiểu "Hộp đen"**: 
Một số nghiên cứu gần đây cố gắng đưa mô hình ngôn ngữ lớn (LLM) vào việc đọc mã dịch ngược và kết luận ngay xem mẫu đó có độc hại hay không. Cách tiếp cận này dẫn tới 2 rủi ro rất lớn: một là hiện tượng "ảo giác" (hallucination) khiến AI đưa ra nhận định không có căn cứ; hai là nguy cơ bị tấn công Prompt Injection — kẻ viết mã độc có thể gài các chuỗi văn bản đánh lừa ngay trong thân tệp PE để thao túng câu trả lời của mô hình.

Xuất phát từ 3 thực trạng đó, bài toán đặt ra là: Chúng ta cần một hệ thống có khả năng tự động hóa quy trình phân tích kết hợp cả tĩnh và động, vận hành an toàn trong hạ tầng nội bộ, trong đó AI không phải là thẩm phán phán quyết tùy tiện, mà đóng vai trò là một **Agent điều phối chiến lược** có trách nhiệm đối chiếu bằng chứng minh bạch. Đó chính là lý do đề tài HyperAgent ra đời.
