
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials


download_pass = HTTPBasic()

def verify_basic(credentials: HTTPBasicCredentials = Depends(download_pass)):
    correct_username = "kgzakup@yandex.ru"
    correct_password = "Krainevgroup2024"
    if credentials.username != correct_username or credentials.password != correct_password:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
