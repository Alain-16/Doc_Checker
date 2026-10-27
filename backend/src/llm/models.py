from enum import StrEnum

from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel

from src.config.settings import get_settings
from src.models.chunk import EMBEDDING_DIMENSIONS

REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRIES = 3
EMBEDDING_MODEL = "text-embedding-3-large" 


class LlmTask(StrEnum):
    CLASSIFY_DOCUMENT = "classify_document"
    IDENTIFY_VENDOR = "identify_vendor"
    LABEL_DATES = "label_dates"
    EXTRACT_KEY_ATTRIBUTES = "extract_key_attributes"


# Which model each task uses. The PRD leaves the final choice to the Feature 13
# benchmarks ("cheapest passing tier per task"); these are starting points.
# All are narrow tasks on a few pages of text, so they start on the small tier.
MODEL_BY_TASK: dict[LlmTask, str] = {
    LlmTask.CLASSIFY_DOCUMENT: "gpt-5",
    LlmTask.IDENTIFY_VENDOR: "gpt-5",
    LlmTask.LABEL_DATES: "gpt-5",
    LlmTask.EXTRACT_KEY_ATTRIBUTES: "gpt-5",
}


def structured_llm(task: LlmTask, schema: type[BaseModel]) -> Runnable:
    """A chat model that must answer in the shape of `schema`.

    with_structured_output sends the Pydantic schema to OpenAI as a strict JSON
    schema, so the reply is guaranteed to parse, and returns a `schema` object
    instead of free text. Call it with .invoke(messages).
    """
    model = ChatOpenAI(
        model=MODEL_BY_TASK[task],
        api_key=get_settings().openai_api_key,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )
    return model.with_structured_output(schema, method="json_schema", strict=True)


def embedding_model() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        # Ask OpenAI for the shortened vector the chunks column stores (1536,
        # not the model's full 3072). text-embedding-3 models are trained so a
        # shortened vector keeps most of the quality.
        dimensions=EMBEDDING_DIMENSIONS,
        api_key=get_settings().openai_api_key,
        max_retries=MAX_RETRIES,
    )