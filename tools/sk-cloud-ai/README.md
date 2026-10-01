# Công cụ mã nguồn — Cloud AI, GitHub, Cursor, Xcode

CLI Python (chỉ thư viện chuẩn) để gọi OpenAI, một gateway Cloud AI tương thích OpenAI, kiểm tra GitHub, mở Cursor Cloud Agent, và cấu hình Xcode.

Key để trong `skai.env` hoặc biến môi trường. Không ghi vào git và không dán vào câu hỏi. Token GitHub chỉ gọi `api.github.com` từ máy này; lệnh Cursor không nhét token đó vào agent.

Tool này đứng riêng, không gắn vào framework HookKit và không đổi binary phát hành.

## Cấu hình

```bash
cp tools/sk-cloud-ai/skai.env.example skai.env
```

Điền key thật. Dòng còn giá trị mẫu được coi là chưa gắn.

| Biến | Dùng cho |
| --- | --- |
| `OPENAI_API_KEY` | `openai models`, `openai chat`, `openai edit` |
| `OPENAI_MODEL` | Mặc định `gpt-4o-mini` |
| `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID` | Gửi header `OpenAI-Organization` và `OpenAI-Project` khi có |
| `SK_CLOUD_AI_API_KEY` | `chat`, `edit`, `models`. Nếu còn giá trị mẫu thì dùng `OPENAI_API_KEY` |
| `SK_CLOUD_AI_BASE_URL` | Gốc có `/v1`, `POST /chat/completions` |
| `GITHUB_TOKEN` hoặc `GH_TOKEN` | `github`, `connect` |
| `CURSOR_API_KEY` | `cursor`, `connect` |
| `XCODE_PROJECT` hoặc `XCODE_WORKSPACE` | `xcode` |
| `XCODE_SCHEME` | Scheme Xcode. Bỏ trống nếu chỉ có một scheme |
| `XCODE_CONFIGURATION` | Mặc định `Debug` |
| `XCODE_DESTINATION` | Mặc định `generic/platform=iOS` |
| `XCODE_SDK` | Tuỳ chọn, ví dụ `iphoneos` |

`CURSOR_API_KEY` lấy ở [Cursor Dashboard → API Keys](https://cursor.com/dashboard/api). Repo phải cài Cursor GitHub App thì `GET /v1/repositories` mới thấy nó. API Cursor nhận Basic auth (`key` làm username, mật khẩu trống), đúng tài liệu Cloud Agents API v1.

Thứ tự ưu tiên: cờ `--base-url` / `--model`, rồi biến môi trường, rồi file. File được tìm ở `./skai.env`, sau đó `tools/sk-cloud-ai/skai.env`.

```bash
python3 tools/sk-cloud-ai/skai.py config
```

## OpenAI

Key dạng `sk-` lấy tại [platform.openai.com/api-keys](https://platform.openai.com/api-keys). Mặc định gọi `https://api.openai.com/v1`.

```bash
python3 tools/sk-cloud-ai/skai.py openai models
python3 tools/sk-cloud-ai/skai.py openai chat "hàm này làm gì" --file src/core/HKPlan.c
python3 tools/sk-cloud-ai/skai.py openai edit "sửa comment" --file src/core/HKPlan.c
```

`OPENAI_ORG_ID` và `OPENAI_PROJECT_ID` chỉ được gắn khi gọi OpenAI. Gateway khác không nhận hai header này.

## Cloud AI

Key `sk-ant-` (Anthropic) tự gọi `https://api.anthropic.com` bằng header `x-api-key`, model mặc định `claude-haiku-4-5-20251001`. Key gateway khác dùng `SK_CLOUD_AI_BASE_URL`. Incord Cloud AI: `https://api.incord.ai/v1/cloud`, header `Authorization: Bearer`. Chat cần key còn hạn và tài khoản còn credit.

```bash
python3 tools/sk-cloud-ai/skai.py models
python3 tools/sk-cloud-ai/skai.py chat "hàm rebind đang làm gì" --file src/core/HKPlan.c
python3 tools/sk-cloud-ai/skai.py edit "đổi comment ở đầu file" --file src/core/HKPlan.c
python3 tools/sk-cloud-ai/skai.py edit "đổi comment" --dry-run
```

`--root` giới hạn thư mục được đọc và ghi. `chat` không ghi file. File `.env`, `skai.env`, khóa riêng và đường dẫn chui ra ngoài `--root` bị từ chối.

## GitHub và Cursor

```bash
python3 tools/sk-cloud-ai/skai.py github whoami
python3 tools/sk-cloud-ai/skai.py github repos
python3 tools/sk-cloud-ai/skai.py cursor me
python3 tools/sk-cloud-ai/skai.py cursor models
python3 tools/sk-cloud-ai/skai.py cursor repos
python3 tools/sk-cloud-ai/skai.py connect --repo owner/name
```

`cursor repos` và `connect` gọi `GET /v1/repositories`. Cursor giới hạn endpoint này khoảng 1 lần/phút và 30 lần/giờ, và có thể chậm.

Mở agent trên repo, Cursor tự tạo nhánh mới và pull request:

```bash
python3 tools/sk-cloud-ai/skai.py cursor run "Thêm hướng dẫn build" \
  --repo https://github.com/owner/name \
  --ref master
```

Làm trên một pull request có sẵn:

```bash
python3 tools/sk-cloud-ai/skai.py cursor run "Xem lại diff" \
  --pr https://github.com/owner/name/pull/123
```

`--no-auto-pr` để không nhờ Cursor mở PR. Gửi tiếp việc cho agent đang chạy:

```bash
python3 tools/sk-cloud-ai/skai.py cursor follow bc-... "Thêm test cho chỗ vừa sửa"
```

## Xcode

Trong thư mục có `.xcodeproj` hoặc `.xcworkspace`:

```bash
python3 tools/sk-cloud-ai/skai.py xcode discover
python3 tools/sk-cloud-ai/skai.py xcode show
python3 tools/sk-cloud-ai/skai.py --dry-run xcode build
```

`build` và `test` gọi `xcodebuild` khi máy có Xcode. Không có `xcodebuild` thì lệnh dừng và không giả bộ đã build. `--dry-run` chỉ in lệnh.

Gắn vào Xcode: Settings → Behaviors → dấu + → Run, trỏ tới script in ra bởi:

```bash
python3 tools/sk-cloud-ai/skai.py xcode behavior
```

Script đọc workspace và scheme đang mở. Thêm đối số thì gửi câu đó cho `skai chat`.

## Kiểm tra

```bash
python3 -m unittest discover -s tools/sk-cloud-ai/tests -v
```

Các test này không gọi mạng.
