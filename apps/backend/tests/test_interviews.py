from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ENDPOINT = "/api/v1/interviews/analyze"


def _valid_payload(**overrides):
    payload = {
        "session_id": "local-session-id",
        "role": "AI/ML Engineer",
        "company": "Example Company",
        "job_description": "AI/ML Engineer responsible for...",
        "candidate_context": {
            "resume": "Experienced engineer...",
            "projects": ["RAG Security Copilot", "CIS Security Platform"],
        },
        "transcript": {
            "duration_seconds": 2840,
            "segments": [
                {
                    "timestamp": "00:00:04",
                    "source": "SYSTEM_AUDIO",
                    "text": "Can you tell me about yourself?",
                },
                {
                    "timestamp": "00:00:25",
                    "source": "MICROPHONE",
                    "text": "Sure, I have experience...",
                },
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_valid_interview_with_no_questions_returns_200_with_empty_analysis():
    # No question_answers supplied -> no LLM calls happen at all; the service
    # short-circuits to an explicit "no questions identified" result rather
    # than calling an LLM stage with nothing to analyze.
    response = client.post(ENDPOINT, json=_valid_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "local-session-id"
    assert body["status"] == "completed"
    assert body["overall_score"] == 0
    assert body["technical_score"] == 0
    assert body["communication_score"] == 0
    assert body["questions"] == []
    assert "no" in body["message"].lower() or "no" in body["summary"].lower()


def test_missing_transcript_returns_422():
    payload = _valid_payload()
    del payload["transcript"]
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_source_returns_422():
    payload = _valid_payload()
    payload["transcript"]["segments"][0]["source"] = "UNKNOWN"
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


def test_empty_transcript_segments_is_accepted_with_zero_duration():
    payload = _valid_payload()
    payload["transcript"] = {"duration_seconds": 0, "segments": []}
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"


def test_missing_session_id_returns_422():
    payload = _valid_payload()
    del payload["session_id"]
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


def test_blank_segment_text_returns_422():
    payload = _valid_payload()
    payload["transcript"]["segments"][0]["text"] = "   "
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


def test_malformed_timestamp_returns_422():
    payload = _valid_payload()
    payload["transcript"]["segments"][0]["timestamp"] = "not-a-timestamp"
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


def test_negative_duration_returns_422():
    payload = _valid_payload()
    payload["transcript"]["duration_seconds"] = -1
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


def test_large_transcript_is_accepted():
    segments = [
        {
            "timestamp": f"{(i // 60) % 60:02}:{i % 60:02}",
            "source": "SYSTEM_AUDIO" if i % 2 == 0 else "MICROPHONE",
            "text": f"This is transcript segment number {i} with some representative content.",
        }
        for i in range(2000)
    ]
    payload = _valid_payload()
    payload["transcript"] = {"duration_seconds": 7200, "segments": segments}
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"


def test_minimal_payload_without_optional_fields():
    payload = {
        "session_id": "minimal-session",
        "transcript": {"duration_seconds": 10, "segments": []},
    }
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 200


def test_response_never_reflects_fabricated_scores_with_no_questions():
    # Regression guard: with no questions (and thus no LLM calls), scores must
    # stay at 0 rather than defaulting to something that looks like a real
    # assessment.
    response = client.post(ENDPOINT, json=_valid_payload())
    body = response.json()
    assert body["overall_score"] == 0
    assert body["technical_score"] == 0
    assert body["communication_score"] == 0


def test_question_answers_with_mock_provider_returns_mock_scores():
    # With no LLM_PROVIDER configured in the test environment, the service
    # falls back to MockLLMProvider — verifies the question_answers path is
    # accepted and produces a structurally valid (if score=0) response, not
    # that it necessarily looks like a `no questions` short-circuit.
    payload = _valid_payload(
        question_answers=[
            {
                "question_id": "q1",
                "question": "Can you explain the RAG architecture you implemented?",
                "candidate_answer": "I built a retrieval pipeline using embeddings and a vector store.",
                "timestamp": "00:12:32",
                "retrieved_context": [
                    {
                        "text": "Implemented a RAG pipeline using FastAPI and pgvector.",
                        "source_filename": "RAG_Project.pdf",
                        "document_type": "PROJECT",
                        "score": 0.87,
                    }
                ],
            }
        ]
    )
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "local-session-id"
    assert len(body["questions"]) == 1
    assert body["questions"][0]["question_id"] == "q1"
    assert body["questions"][0]["failed"] is False


def test_question_answers_with_invalid_source_type_returns_422():
    payload = _valid_payload(
        question_answers=[
            {
                "question_id": "q1",
                "question": "Test question?",
                "candidate_answer": "Test answer.",
                "timestamp": "00:00:10",
                "retrieved_context": [
                    {
                        "text": "some text",
                        "source_filename": "a.pdf",
                        "document_type": "PROJECT",
                        "score": 1.5,  # invalid: score must be <= 1.0
                    }
                ],
            }
        ]
    )
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422


def test_malformed_question_timestamp_returns_422():
    payload = _valid_payload(
        question_answers=[
            {
                "question_id": "q1",
                "question": "Test question?",
                "candidate_answer": "Test answer.",
                "timestamp": "not-a-timestamp",
                "retrieved_context": [],
            }
        ]
    )
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422
