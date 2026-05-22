from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.responses import created


class _Out(BaseModel):
    id: int


def test_created_sets_location_header():
    app = FastAPI()

    @app.post("/things", status_code=201, response_model=_Out)
    def make(response: Response):
        return created(_Out(id=42), location="/things/42", response=response)

    with TestClient(app) as c:
        r = c.post("/things")
        assert r.status_code == 201
        assert r.headers["location"] == "/things/42"
        assert r.json() == {"id": 42}
