import requests
import os
import argparse

parser = argparse.ArgumentParser(description="Upload a file to the API")
parser.add_argument("-file", type=str, help="Path to the file to upload")
args = parser.parse_args()

url = "http://localhost:8000/analysis/scan"

try:
    # Read the file content into memory before making the request
    file_content = None
    with open(args.file, "rb") as f:
        file_content = f.read()

    # Pass the file content directly, along with the filename
    files = {"file": (os.path.basename(args.file), file_content, "application/octet-stream")}
    response = requests.post(url, files=files)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")