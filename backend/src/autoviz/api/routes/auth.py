"""Authentication routes — registration and login (Day 3-4 implementation).

Planned endpoints:

    POST /auth/register   Create a new user account (FR-01–FR-03)
    POST /auth/login      Authenticate and return a session token (FR-04–FR-06)
    POST /auth/logout     Terminate the active session (FR-08)
"""

from fastapi import APIRouter

router = APIRouter(tags=["auth"])
