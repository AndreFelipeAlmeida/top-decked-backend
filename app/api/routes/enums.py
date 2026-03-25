from fastapi import APIRouter
from app.utils.Enums import TCG

router = APIRouter(prefix="/tcgs", tags=["tcgs"])


@router.get("/")
def get_tcgs():
    return [
        {"label": tcg.label, "value": tcg.value}
        for tcg in TCG
    ]
