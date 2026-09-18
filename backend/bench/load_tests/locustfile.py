import random
import uuid
import time
from locust import HttpUser, task, between

class AutoVizUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """Register and login a unique user for this Locust session"""
        self.username = f"locust_{uuid.uuid4().hex[:8]}"
        self.email = f"{self.username}@test.com"
        self.password = "password123"
        
        # 1. Register
        self.client.post("/api/auth/register", json={
            "username": self.username,
            "email": self.email,
            "password": self.password
        })
        
        # 2. Login
        response = self.client.post("/api/auth/login", json={
            "email": self.email,
            "password": self.password
        })
        
        if response.status_code == 200:
            token = response.json().get("access_token")
            if token:
                self.client.headers.update({"Authorization": f"Bearer {token}"})

    @task(3)
    def fetch_dashboards(self):
        """Read-heavy load: Simulate fetching dashboards and lists"""
        self.client.get("/api/dashboards")
        
    @task(3)
    def fetch_datasets(self):
        """Read-heavy load: Simulate fetching available datasets"""
        self.client.get("/api/datasets")

    @task(1)
    def upload_dataset(self):
        """Write-heavy load: Upload a small CSV dataset"""
        csv_content = "id,name,value\n1,Alpha,10\n2,Beta,20\n3,Gamma,30"
        files = {
            'file': ('locust_test.csv', csv_content, 'text/csv')
        }
        self.client.post("/api/datasets/upload", files=files)
