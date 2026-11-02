# Thuyết minh Slide 11: Kết luận & Định hướng phát triển

**Thời lượng khuyến nghị**: 1 phút 15 giây (12:15 - 13:30)

**Nội dung thuyết minh chi tiết**:

Kính thưa Quý Thầy Cô trong Hội đồng, để khép lại phần nội dung chuyên môn, em xin phép được tổng kết lại các dấu ấn nổi bật và thẳng thắn nhìn nhận những định hướng cần tiếp tục hoàn thiện của đề tài:

Về **Các kết quả nghiên cứu đã đạt được**:
1. Đề tài đã xây dựng thành công **HyperAgent** — một công cụ phân tích mã độc Hybrid hoàn chỉnh gồm 9 giai đoạn tự động, kết nối linh hoạt giữa IDA Pro và x64dbg thông qua giao thức chuẩn mở Model Context Protocol (MCP), vận hành an toàn trong mạng nội bộ On-Premise với máy ảo cô lập.
2. Giải quyết triệt để vấn đề "ảo giác" của AI thông qua cơ chế ràng buộc bằng chứng 3 mức (*Được phép, Có điều kiện, Bị cấm*) và kỹ thuật phòng vệ Prompt Injection bằng cách ly dữ liệu mẫu thô.
3. Hoàn thành bộ thực nghiệm quy mô lớn trên 3.000 mẫu PE từ DikeDataset, đạt **Precision 98,5%, Recall 86,2% và F1-Score 91,9%**. Khung nghiên cứu loại trừ đã chứng minh một cách khoa học rằng: nguồn bằng chứng động đóng vai trò chi phối lớn hơn, và lượt phân tích tĩnh thứ hai sau giải nén giúp tăng 5,7 điểm phần trăm khả năng bóc trần mã độc.
4. Đóng góp sản phẩm nguồn mở minh bạch, đóng vai trò là học liệu thực hành giá trị cho sinh viên và công cụ hỗ trợ thiết thực cho các trung tâm SOC.

Về **Hạn chế và Định hướng phát triển tiếp theo**:
Nhóm nghiên cứu nhận thấy đề tài vẫn còn 3 điểm cần tiếp tục đẩy mạnh:
- **Thứ nhất là tối ưu hóa thời gian xử lý**: Hiện nay, thời gian trung vị 89,4 phút mỗi mẫu còn tương đối dài đối với các tình huống cần ứng cứu khẩn cấp. Trong thời gian tới, nhóm sẽ song song hóa việc trích xuất tĩnh và tối ưu hóa giải thuật tự động dừng breakpoint để rút ngắn thời gian xử lý xuống dưới 30 phút.
- **Thứ hai là mở rộng đa nền tảng**: Hiện tại hệ thống mới chỉ phân tích tệp PE trên Windows. Nhóm dự kiến sẽ mở rộng sang định dạng ELF cho môi trường Linux/IoT và tệp APK cho các thiết bị di động Android.
- **Thứ ba là công bố khoa học**: Toàn bộ dữ liệu thực nghiệm phong phú từ 3.000 mẫu đang được nhóm tổng hợp để hoàn thiện bài báo khoa học chất lượng cao, hướng tới việc gửi đăng tại các hội thảo và tạp chí chuyên ngành An toàn thông tin uy tín.

Sau đây, em xin chuyển sang trang kết thúc và mở đầu cho phiên hỏi đáp của Hội đồng.
