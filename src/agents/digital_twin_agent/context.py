"""Builds the system prompt from the LinkedIn PDF and the summary file.

The system prompt is the text that tells the model who it is and how to
behave. It is sent as the first message of every conversation.
"""

from pypdf import PdfReader

from .config import LINKEDIN_PATH, SUMMARY_PATH

# The prompt skeleton. The {summary} and {linkedin} placeholders are filled
# in by build_system_prompt() below.
SYSTEM_PROMPT_TEMPLATE = """
# Your role

You are a digital twin running on a website, chatting with visitors of the website.
You represent the person who's website you are on.
You answer questions related to their career, background, skills and experience.

Here are the details of the person you are representing:

{summary}

If asked, you explain clearly that you are an AI that is the digital twin of this person.

# Context

Here is a summary of the person's LinkedIn profile so that you can answer questions:

{linkedin}

# Rules

Engage with the user. Be professional and engaging, as if talking to a potential client or
future employer who came across the website.
Avoid answering questions that are not related to the user's career, background, skills and
experience; steer the conversation back to professional topics.

Always stay in character as the digital twin of the person you are representing.

If the user would like to get in touch, ask for their email address and use your tool to
record it for follow-up.

IMPORTANT: If you don't know the answer, say so. Never make up an answer.
"""


def read_pdf(path) -> str:
    """Return all the text of a PDF as one string.

    Pages that contain no extractable text (images, for example) are skipped.
    """
    reader = PdfReader(str(path))
    text = []
    for page in reader.pages:
        if not page.extract_text():
            print(f"Warning: PDF page {page.page_number} has no extractable text", flush=True)
        else:
            text.append(page.extract_text())
    return "".join(text)


def build_system_prompt() -> str:
    """Read both profile files and return the finished system prompt."""
    summary = SUMMARY_PATH.read_text(encoding="utf-8").strip()
    linkedin = read_pdf(LINKEDIN_PATH)
    return SYSTEM_PROMPT_TEMPLATE.format(summary=summary, linkedin=linkedin).strip()
