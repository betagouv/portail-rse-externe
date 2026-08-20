from unittest.mock import patch

import pytest

from flask_app.app import app


@pytest.fixture
def client():
    with app.test_client() as client:
        yield client


def test_ping(client):
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.get_json() == {"status": "alive", "msg": "API is alive and well"}


@patch("flask_jwt_extended.view_decorators.verify_jwt_in_request")
@patch("flask_app.app.tasks.analyser.delay")
@patch("flask_app.app._fetch_s3_document")
def test_run_task(mock_fetch_s3_document, mock_delay, mock_verify_jwt, client):
    mock_fetch_s3_document.return_value = "./workspace/document_1"

    response = client.post(
        "/run-task",
        data={
            "document_id": "1",
            "document_url": "https://example.com/fichier.pdf",
            "callback_url": "https://example.com/callback",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "pending"}
    mock_fetch_s3_document.assert_called_once_with("https://example.com/fichier.pdf", "1")
    mock_delay.assert_called_once_with("1", "./workspace/document_1", "https://example.com/callback")


@patch("flask_jwt_extended.view_decorators.verify_jwt_in_request")
@patch("flask_app.app.tasks.analyser.delay")
@patch("flask_app.app._fetch_s3_document")
def test_run_task_requete_incorrecte(mock_fetch_s3_document, mock_delay, mock_verify_jwt, client):
    mock_fetch_s3_document.return_value = "./workspace/document_1"

    response = client.post(
        "/run-task",
        data={},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "error"
    assert mock_fetch_s3_document.called is False
    assert mock_delay.called is False
