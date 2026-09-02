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
def test_run_task_v1_par_defaut(mock_fetch_s3_document, mock_delay, mock_verify_jwt, client):
    """URL utilisée lorsqu"il n'y avait que la v1. Cette URL va disparaitre"""
    mock_fetch_s3_document.return_value = "./workspace/document_1"

    response = client.post(
        "/run-task",
        data={
            "document_id": "42",
            "document_url": "https://example.com/fichier.pdf",
            "callback_url": "https://example.com/callback",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "pending"}
    mock_fetch_s3_document.assert_called_once_with("https://example.com/fichier.pdf", "42", 1)
    mock_delay.assert_called_once_with("42", "./workspace/document_1", "https://example.com/callback", 1)

@patch("flask_jwt_extended.view_decorators.verify_jwt_in_request")
@patch("flask_app.app.tasks.analyser.delay")
@patch("flask_app.app._fetch_s3_document")
def test_run_task_v1(mock_fetch_s3_document, mock_delay, mock_verify_jwt, client):
    """URL utilisée avec l'existence de la v1 et la v2"""

    mock_fetch_s3_document.return_value = "./workspace/document_1"

    response = client.post(
        "/run-task/v1",
        data={
            "document_id": "42",
            "document_url": "https://example.com/fichier.pdf",
            "callback_url": "https://example.com/callback",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "pending"}
    mock_fetch_s3_document.assert_called_once_with("https://example.com/fichier.pdf", "42", 1)
    mock_delay.assert_called_once_with("42", "./workspace/document_1", "https://example.com/callback", 1)


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

@patch("flask_jwt_extended.view_decorators.verify_jwt_in_request")
@patch("flask_app.app.tasks.analyser.delay")
@patch("flask_app.app._fetch_s3_document")
def test_run_task_v2(mock_fetch_s3_document, mock_delay, mock_verify_jwt, client):
    """URL utilisée avec l'existence de la v1 et la v2"""
    mock_fetch_s3_document.return_value = "./workspace/document_1"

    response = client.post(
        "/run-task/v2",
        data={
            "document_id": "1",
            "document_url": "https://example.com/fichier.pdf",
            "callback_url": "https://example.com/callback",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "pending"}
    mock_fetch_s3_document.assert_called_once_with("https://example.com/fichier.pdf", "1", 2)
    mock_delay.assert_called_once_with("1", "./workspace/document_1", "https://example.com/callback", 2)