"""New Interview setup page's auto-analysis endpoint.

Separate from `/api/v1/ask` and `/api/v1/interviews/analyze` — runs before
any interview session exists, purely to summarize pasted/uploaded CV and JD
text into a short "Interview Focus" shown on the setup page.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.schemas.setup_analysis import SetupAnalysisRequest, SetupAnalysisResponse
from app.services.setup_analysis_service import get_setup_analysis_service

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/setup", tags=["setup"])


@router.post("/analyze", response_model=SetupAnalysisResponse)
async def analyze_setup(request: SetupAnalysisRequest) -> SetupAnalysisResponse:
    logger.info(
        "[API] POST /api/v1/setup/analyze resume_len=%d jd_len=%d",
        len(request.resume_text or ""),
        len(request.job_description_text or ""),
    )
    service = get_setup_analysis_service()
    return await service.analyze(request)
