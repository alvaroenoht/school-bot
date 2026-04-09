import requests
import json

BASE_URL = "http://localhost:8000/api/admin"

def test_otp_request(phone):
    print(f"--- Requesting OTP for {phone} ---")
    try:
        response = requests.post(f"{BASE_URL}/auth/otp-request", json={"phone": phone})
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # This assumes the FastAPI server is running locally (e.g. via uvicorn)
    # uvicorn app.main:app --reload
    print("Welcome to SchoolBot Admin API Preview")
    phone = input("Enter your admin phone number (digits only): ")
    test_otp_request(phone)
