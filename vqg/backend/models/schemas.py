from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class ImageCategory(str, Enum):
    ANATOMICAL_DIAGRAM = "ANATOMICAL_DIAGRAM"
    CELLULAR_MOLECULAR = "CELLULAR_MOLECULAR"
    CHEMICAL_STRUCTURE = "CHEMICAL_STRUCTURE"
    FLOWCHART_PROCESS = "FLOWCHART_PROCESS"
    GEOGRAPHIC_MAP = "GEOGRAPHIC_MAP"
    ENGINEERING_SCHEMATIC = "ENGINEERING_SCHEMATIC"
    CLINICAL_PHOTO = "CLINICAL_PHOTO"
    HISTOLOGY_MICROSCOPY = "HISTOLOGY_MICROSCOPY"
    DATA_VISUALIZATION = "DATA_VISUALIZATION"
    TABLE_IMAGE = "TABLE_IMAGE"
    PROCEDURAL_STEP = "PROCEDURAL_STEP"
    TIMELINE = "TIMELINE"
    COMPARATIVE_DIAGRAM = "COMPARATIVE_DIAGRAM"
    DECORATIVE = "DECORATIVE"
    LOGO_WATERMARK_HEADER = "LOGO_WATERMARK_HEADER"
    PORTRAIT_PHOTO = "PORTRAIT_PHOTO"
    SPLASH_IMAGE = "SPLASH_IMAGE"
    ICON_LEGEND_ALONE = "ICON_LEGEND_ALONE"
    LOW_QUALITY = "LOW_QUALITY"


class QuizFormat(str, Enum):
    LABEL_BLANK = "LABEL_BLANK"
    SEQUENCE_ORDER = "SEQUENCE_ORDER"
    DATA_READING = "DATA_READING"
    REGION_CLICK = "REGION_CLICK"
    CONTEXT_MCQ = "CONTEXT_MCQ"
    SKIP = "SKIP"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    PARSING = "PARSING"
    TRIAGING = "TRIAGING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    PROCESSING = "PROCESSING"
    GENERATING = "GENERATING"
    EXPORTING = "EXPORTING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class TriageResult(BaseModel):
    category: ImageCategory
    has_labels: bool
    label_density: str  # LOW | MEDIUM | HIGH
    background_type: str  # WHITE | LIGHT | DARK | PHOTOGRAPHIC | COMPLEX
    domain: str  # MEDICINE | BIOLOGY | CHEMISTRY | GEOGRAPHY | ENGINEERING | PHYSICS | HISTORY | OTHER
    confidence: float
    worth_quizzing: bool
    reason: str
    estimated_label_count: int
    quiz_format: QuizFormat


class Label(BaseModel):
    id: str
    text: str
    meaning: str
    approximate_location: str  # TOP_LEFT | TOP_CENTER | ... | BOT_RIGHT
    label_type: str  # CALLOUT_TEXT | NUMBERED_POINTER | INLINE_TEXT | ARROW_LABEL


class LabelExtractionResult(BaseModel):
    labels: List[Label]
    total_labels: int
    suggested_quiz_labels: List[str]
    notes: Optional[str] = None


class QuizQuestion(BaseModel):
    label_id: str
    structure_name: str
    question: str
    distractors: List[str]
    difficulty: str  # EASY | MEDIUM | HARD
    explanation: str


class ProcessedImage(BaseModel):
    image_id: str
    original_path: str
    processed_path: Optional[str] = None
    method: str  # nano_banana_2 | numbered_box_fallback | skipped
    triage: Optional[TriageResult] = None
    labels: Optional[LabelExtractionResult] = None
    questions: Optional[List[QuizQuestion]] = None
    ssim_score: Optional[float] = None


class Job(BaseModel):
    job_id: str
    status: JobStatus
    pdf_filename: str
    total_images: int = 0
    processed_images: int = 0
    skipped_images: int = 0
    generated_images: int = 0
    quiz_count: int = 0
    export_path: Optional[str] = None
    html_export_path: Optional[str] = None
    pdf_export_path: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str
    user_id: Optional[str] = None
