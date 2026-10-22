# LangGraph examples with Groq

All LLM calls in this package use `ChatGroq`, including the deep agent and its
subagents. Add your key to the repository-root `.env`:

```dotenv
GROQ_API_KEY=your-api-key
AGENT_MODEL=openai/gpt-oss-20b
```

All examples share `AGENT_MODEL`, which defaults to `openai/gpt-oss-20b`.
This package ignores the shared `PROVIDER` and the old Ollama model settings.
Search tools still require `SERPER_API_KEY`.

Optional overrides:

| Variable                | Default                                            |
| ----------------------- | -------------------------------------------------- |
| `GROQ_BASE_URL`         | `https://api.groq.com` (the SDK adds `/openai/v1`) |

Token limits and reasoning effort use Groq's defaults.

Run the example selected in `__main__.py` (currently the deep agent):

```sh
uv run agent-by-langgraph
```
