# Thuyết minh Slide 09: Nghiên cứu loại trừ (Ablation Study) & Đóng góp thành phần

**Thời lượng khuyến nghị**: 1 phút 30 giây (09:30 - 11:00)

**Nội dung thuyết minh chi tiết**:

Kính thưa Quý Thầy Cô trong Hội đồng, điểm đắt giá nhất về mặt phương pháp luận khoa học của đề tài chính là **Nghiên cứu loại trừ (Ablation Study)** được thể hiện qua **Hình 2**.

Chúng em đã thiết lập thực nghiệm đối chứng trực tiếp giữa 3 cấu hình trên cùng một tập mẫu thử:
- **Cấu hình FULL (Đầy đủ cả 9 giai đoạn)**
- **Cấu hình A1 (Loại bỏ nhánh phân tích tĩnh)**
- **Cấu hình A2 (Loại bỏ nhánh phân tích động)**

Từ biểu đồ và bảng số liệu so sánh, đề tài rút ra **3 kết luận định lượng mang tính học thuật sâu sắc**:

**Kết luận 1 — Phân tích động đóng góp trọng số lớn hơn phân tích tĩnh trong quyết định của Agent**:
- Khi chúng em loại bỏ phân tích động (cấu hình A2), độ thu hồi Recall bị sụt giảm nghiêm trọng tới **11,2 điểm phần trăm** (từ 86,2% rơi xuống chỉ còn 75,0%), kéo theo F1-score giảm từ 91,9% xuống 84,5%.
- Trong khi đó, nếu loại bỏ phân tích tĩnh (cấu hình A1), Recall giảm **6,6 điểm phần trăm** (từ 86,2% xuống 79,6%).
- Điều này chứng minh rằng: Mặc dù phân tích tĩnh giúp định hình bản đồ hàm ban đầu, nhưng chính việc thực thi mẫu trong máy ảo để "bắt tận tay" các hành vi tạo tiến trình con, ghi registry và kết nối mạng mới là bằng chứng đanh thép nhất để AI ra kết luận kết tội mã độc. Cả hai nguồn bằng chứng đều không thể thiếu, trong đó phân tích động mang tính quyết định cao hơn.

**Kết luận 2 — Giá trị đột phá của Lượt phân tích tĩnh thứ hai sau giải nén (Pass 2 after Unpack)**:
- Một điểm sáng tạo độc đáo của HyperAgent là giai đoạn 04: đưa tệp payload đã bung nén quay lại IDA Pro để quét tĩnh lần 2.
- Dữ liệu thực nghiệm chứng minh: Lượt tĩnh thứ 2 này đã giúp nâng tỉ lệ mẫu có phát hiện được xác nhận (Confirmed Detection Rate) từ **78,7% lên tới 84,4% — tức tăng thêm 5,7 điểm phần trăm!**
- Đây là minh chứng rõ ràng cho thấy: Việc kết hợp giải nén động bằng x64dbg để bóc lớp vỏ obfuscated rồi tiếp tục đào sâu tĩnh bằng IDA Pro là một mắt xích cực kỳ hiệu quả đối với các dòng mã độc hiện đại.

**Kết luận 3 — Thời gian xử lý và Định vị bài toán áp dụng**:
- Thời gian xử lý trung vị của hệ thống là **89,4 phút mỗi mẫu**. Con số này phản ánh chiều sâu phân tích và sự kỹ lưỡng trong từng bước dò tìm OEP và đặt breakpoint.
- Vì vậy, về mặt ứng dụng thực tế, HyperAgent không sinh ra để làm công cụ quét antivirus hàng triệu tệp theo thời gian thực (real-time streaming), mà được định vị là **vũ khí phân tích chuyên sâu (Deep-dive investigation)** dành cho các mẫu mã độc nguy hiểm, phức tạp, có chủ đích (APT) đã vượt qua các lớp tường lửa ban đầu.

Tiếp theo, em xin báo cáo về các giá trị đóng góp kinh tế - xã hội, giáo dục và khả năng ứng dụng thực tiễn của đề tài.
