from app.schemas.analysis import QuestionAnalysis
from app.schemas.interview import QuestionAnswer, RetrievedChunk
from app.services.prompt_builder import build_overall_prompt, build_question_prompt


def _qa(**overrides) -> QuestionAnswer:
    defaults = dict(
        question_id="q1",
        question="Can you explain the RAG architecture you implemented?",
        candidate_answer="I built a retrieval pipeline using embeddings.",
        timestamp="00:12:32",
        retrieved_context=[
            RetrievedChunk(
                text="Implemented a RAG pipeline using FastAPI and pgvector.",
                source_filename="RAG_Project.pdf",
                document_type="PROJECT",
                score=0.87,
            )
        ],
    )
    defaults.update(overrides)
    return QuestionAnswer(**defaults)


def test_question_prompt_includes_role_company_job_description():
    system, user = build_question_prompt(
        _qa(), role="AI/ML Engineer", company="Example Co", job_description="Build ML systems."
    )
    assert "AI/ML Engineer" in user
    assert "Example Co" in user
    assert "Build ML systems." in user


def test_question_prompt_includes_the_question_and_answer():
    system, user = build_question_prompt(_qa(), role=None, company=None, job_description=None)
    assert "Can you explain the RAG architecture you implemented?" in user
    assert "I built a retrieval pipeline using embeddings." in user


def test_question_prompt_includes_retrieved_context():
    system, user = build_question_prompt(_qa(), role=None, company=None, job_description=None)
    assert "RAG_Project.pdf" in user
    assert "Implemented a RAG pipeline using FastAPI and pgvector." in user


def test_question_prompt_handles_missing_retrieved_context():
    system, user = build_question_prompt(_qa(retrieved_context=[]), role=None, company=None, job_description=None)
    assert "No relevant context" in user


def test_question_prompt_handles_missing_role_company_jd():
    system, user = build_question_prompt(_qa(), role=None, company=None, job_description=None)
    assert "No role/company/job description provided" in user


def test_system_prompt_contains_hallucination_control_instructions():
    system, user = build_question_prompt(_qa(), role=None, company=None, job_description=None)
    assert "do not invent experience" in system.lower()
    assert "not established from the supplied candidate context" in system.lower()
    assert "contradicts" in system.lower() or "contradict" in system.lower()


def test_system_prompt_requires_json_only_output():
    system, user = build_question_prompt(_qa(), role=None, company=None, job_description=None)
    assert "json" in system.lower()


def test_question_prompt_includes_rubric_dimensions():
    system, user = build_question_prompt(_qa(), role=None, company=None, job_description=None)
    for dimension in ["Technical Knowledge", "Communication", "Practical Experience", "Clarity", "Confidence"]:
        assert dimension in user


def test_overall_prompt_includes_role_company_job_description():
    qa_result = QuestionAnalysis(
        question_id="q1",
        question="Explain RAG.",
        candidate_answer="I built...",
        assessment="Good technical depth.",
        score=80,
        strengths=["Clear explanation"],
        issues=["Missed deployment detail"],
    )
    system, user = build_overall_prompt(
        [qa_result], role="AI/ML Engineer", company="Example Co", job_description="Build ML systems."
    )
    assert "AI/ML Engineer" in user
    assert "Example Co" in user
    assert "Build ML systems." in user


def test_overall_prompt_includes_per_question_results_not_raw_transcript():
    qa_result = QuestionAnalysis(
        question_id="q1",
        question="Explain RAG.",
        candidate_answer="I built...",
        assessment="Good technical depth.",
        score=80,
    )
    system, user = build_overall_prompt([qa_result], role=None, company=None, job_description=None)
    assert "Good technical depth." in user
    assert "Score: 80" in user


def test_overall_prompt_excludes_failed_questions_from_analysis_block():
    ok = QuestionAnalysis(question_id="q1", question="Q1", candidate_answer="A1", assessment="Fine.", score=70)
    failed = QuestionAnalysis(
        question_id="q2", question="Q2", candidate_answer="A2", assessment="", score=0, failed=True
    )
    system, user = build_overall_prompt([ok, failed], role=None, company=None, job_description=None)
    assert "Q1" in user
    assert "Fine." in user


def test_overall_prompt_handles_all_questions_failed():
    failed = QuestionAnalysis(
        question_id="q1", question="Q1", candidate_answer="A1", assessment="", score=0, failed=True
    )
    system, user = build_overall_prompt([failed], role=None, company=None, job_description=None)
    assert "No question-level analyses completed successfully" in user
