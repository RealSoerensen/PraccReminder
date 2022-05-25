import requests
from bs4 import BeautifulSoup

def get_week():
    r = requests.get("https://ugenr.dk/")
    soup = BeautifulSoup(r.text, "html.parser")
    # Find span
    return soup.find("span", {"id": "ugenr"}).text