# -*- coding: utf-8 -*-
"""
Seduca school portal API client.
Adapted from original to support configurable base_url for multi-tenant use.
"""
import html
import re
from typing import Dict, List, Optional

import requests


class SeducaClient:
    def __init__(self, username: str, password: str, base_url: str = "https://lasalle.gsepty.com"):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/99.0.4844.51 Safari/537.36"
            )
        })

    def login(self) -> bool:
        url = f"{self.base_url}/2/parent/login_manual_check"
        self.session.get(f"{self.base_url}/2/parent/login")
        payload = {
            "_out_referer": "/2/parent/",
            "_password": self.password,
            "_username": self.username,
        }
        headers = {
            "Content-Type": "application/json",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/2/parent/login",
            "Accept": "*/*",
            "User-Agent": self.session.headers["User-Agent"],
        }
        try:
            res = self.session.post(url, json=payload, headers=headers)
            if res.status_code not in (200, 302):
                print("Login failed with status:", res.status_code)
                return False
            warmup_pages = [
                f"{self.base_url}/2/parent/",
                f"{self.base_url}/2/parent/assignments/index",
            ]
            for page in warmup_pages:
                warmup = self.session.get(page, allow_redirects=True)
                if warmup.status_code != 200:
                    print("Warm-up session failed.")
                    return False
            return True
        except requests.RequestException as e:
            print(f"Login error: {e}")
            return False

    def switch_child(self, child_id: int) -> bool:
        url = f"{self.base_url}/2/parent/change/child?eid={child_id}"
        try:
            res = self.session.get(url)
            return res.status_code == 200
        except requests.RequestException as e:
            print(f"Switch child error: {e}")
            return False

    def fetch_assignment_list(self) -> List[Dict]:
        url = f"{self.base_url}/2/parent/assignments/list"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self.base_url}/2/parent/assignments/index",
            "X-Requested-With": "XMLHttpRequest",
        }
        payload: Dict = {"draw": 1, "start": 0, "length": 1000, "page": 1}
        columns = [
            "asigNombre", "asigTipo", "asigMateriaNombre", "asigEducadorNombre",
            "asigPeriodoInternoNombre", "asigFecha", "asigCreado", "asigAdjunto",
            "asigMateriaId", "asigPeriodoInternoId", "asigId",
        ]
        for i, field in enumerate(columns):
            base = f"columns[{i}]"
            payload[f"{base}[data]"] = field
            payload[f"{base}[name]"] = ""
            payload[f"{base}[searchable]"] = "true"
            payload[f"{base}[orderable]"] = "false"
            payload[f"{base}[search][value]"] = ""
            payload[f"{base}[search][regex]"] = "false"
        try:
            res = self.session.post(url, headers=headers, data=payload)
            return res.json().get("data", [])
        except Exception as e:
            print(f"Failed to fetch assignments list: {e}")
            return []

    def fetch_assignment_description(self, asig_id: int) -> Optional[str]:
        url = f"{self.base_url}/2/parent/assignments/show?id={asig_id}"
        try:
            res = self.session.get(url)
            if res.status_code != 200:
                return None
            match = re.search(r"var htmlContent = '([^']+)';", res.text)
            if not match:
                return None
            raw_encoded = match.group(1)
            decoded = raw_encoded.encode("utf-8").decode("unicode_escape")
            return html.unescape(decoded).strip()
        except Exception as e:
            print(f"Error fetching description for {asig_id}: {e}")
            return None

    def fetch_students(self) -> List[Dict]:
        """
        Scrape the list of children from the parent portal dropdown.
        Returns [{"id": int, "name": str, "grade": str}, ...]
        """
        url = f"{self.base_url}/2/parent/assignments/index"
        try:
            res = self.session.get(url)
            if res.status_code != 200:
                return []
            # Each child appears as: changeUser(ID,...) ... <span data-halfname="...">Name - Grade</span>
            blocks = re.findall(
                r'changeUser\((\d+)[^)]*\).*?<span[^>]*data-halfname[^>]*>\s*([^<]+?)\s*</span>',
                res.text,
                re.DOTALL,
            )
            students = []
            for child_id, name_grade in blocks:
                parts = name_grade.strip().rsplit(" - ", 1)
                name = parts[0].strip()
                grade = parts[1].strip() if len(parts) > 1 else ""
                students.append({"id": int(child_id), "name": name, "grade": grade})
            return students
        except Exception as e:
            print(f"fetch_students error: {e}")
            return []

    def fetch_calendar(self, start: str, end: str) -> Optional[List[Dict]]:
        url = f"{self.base_url}/2/parent/calendar/json"
        params = {"start": start, "end": end, "timeZone": "America/Panama"}
        try:
            res = self.session.get(url, params=params)
            res.raise_for_status()
            return res.json()
        except requests.RequestException as e:
            print(f"Calendar fetch error: {e}")
            return None
