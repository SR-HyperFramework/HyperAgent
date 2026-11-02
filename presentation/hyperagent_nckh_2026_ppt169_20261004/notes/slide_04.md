# Thuyết minh Slide 04: Ba điểm mới và Tính sáng tạo cốt lõi

**Thời lượng khuyến nghị**: 1 phút 15 giây (03:15 - 04:30)

**Nội dung thuyết minh chi tiết**:

Kính thưa Hội đồng, đóng góp học thuật và tính sáng tạo của đề tài HyperAgent được thể hiện cô đọng qua **3 điểm mới cốt lõi** so với các nghiên cứu trong và ngoài nước hiện nay:

**Điểm mới thứ nhất — Hợp nhất Tĩnh và Động ở mức Quy trình (Process-level Fusion)**:
Nếu như các công trình nghiên cứu hiện nay thường chỉ kết hợp phân tích tĩnh và động ở mức đặc trưng (trích xuất vector đặc trưng rồi ghép lại) hoặc ở mức đầu ra (cho hai mô hình dự đoán rồi lấy trung bình có trọng số), thì HyperAgent là một trong những hệ thống tiên phong hợp nhất ở **mức quy trình thích ứng**. 
Hệ thống vận hành theo chuỗi 9 giai đoạn với chu trình kín: *Tĩnh lần 1 → Giải nén (Unpacking) → Tĩnh lần 2 → Động*. Kết quả của giai đoạn trước quyết định trực tiếp công cụ và hành vi của giai đoạn sau. Đặc biệt, việc bổ sung lượt phân tích tĩnh thứ hai sau khi đã bung nén thành công cho phép bóc trần toàn bộ các API độc hại và chuỗi ký tự vốn bị che giấu kỹ lưỡng dưới các lớp vỏ mã hóa.

**Điểm mới thứ hai — Ràng buộc kết luận theo bằng chứng & Phòng chống Prompt Injection**:
Để triệt tiêu hoàn toàn vấn đề nhức nhối của các mô hình LLM là "ảo giác", HyperAgent xây dựng giai đoạn đối chiếu nghiêm ngặt: mọi khẳng định kỹ thuật trước khi được ghi vào báo cáo cuối cùng đều bị phân loại vào một trong 3 nhóm: *Được phép (Allowed)*, *Kèm điều kiện (Conditional)*, hoặc *Bị cấm (Forbidden)*. Nếu không trích xuất được địa chỉ bộ nhớ hay lệnh Assembly làm bằng chứng, nhận định đó sẽ bị gạt bỏ.
Đồng thời, toàn bộ dữ liệu trích từ mẫu PE chỉ được hệ thống coi là dữ liệu thô thụ động (Untrusted Data), đi qua bộ lọc Anonymizer và Injection Guard, ngăn chặn tuyệt đối nguy cơ tin tặc gài lệnh tiêm nhiễm để điều khiển AI.

**Điểm mới thứ ba — Khung đánh giá loại trừ có đối chứng chặt chẽ (Ablation Framework)**:
Nhóm nghiên cứu không chỉ đưa ra một mô hình hoàn chỉnh mà còn thiết lập một khung thực nghiệm loại trừ có đối chứng quy mô lớn trên 3.000 mẫu PE thực tế. Bằng việc so sánh cấu hình đầy đủ (FULL) với cấu hình bỏ phân tích tĩnh (A1) và bỏ phân tích động (A2), chúng em đã chứng minh được một cách định lượng sự đóng góp cụ thể của từng luồng dữ kiện trên một hệ thống AI Agent tự động.

Sau đây, em xin đi sâu vào kiến trúc tổng thể và cơ chế kết nối các thành phần trong HyperAgent.
