import requests
import os

# Create a dummy file
with open("test_sample.bin", "wb") as f:
    f.write(b"dummy content")

url = "http://localhost:8000/analysis/scan"
files = {"file": open("test_sample.bin", "rb")}

try:
    response = requests.post(url, files=files)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
finally:
    files["file"].close()
    if os.path.exists("test_sample.bin"):
        os.remove("test_sample.bin")
